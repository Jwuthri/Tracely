# Gestures in Compose

Compose ships a layered gesture API: high-level modifiers for the common 90% (`clickable`, `draggable`, `transformable`, `anchoredDraggable`), and `pointerInput` for everything else. Climb up only when the abstraction breaks - don't reach for `awaitPointerEventScope` to handle a tap.

---

## Modifier-Based Gestures (the simple path)

```kotlin
// Tap
Modifier.clickable(onClick = onPress)

// Tap + long-press + double-tap
Modifier.combinedClickable(
    onClick = onPress,
    onLongClick = onHold,
    onDoubleClick = onDoubleTap,
)

// Single-axis drag
val dragState = rememberDraggableState { delta -> offsetX += delta }
Modifier.draggable(
    state = dragState,
    orientation = Orientation.Horizontal,
    onDragStopped = { velocity -> /* fling here */ },
)

// Scrollable content (when you can't use ScrollState/LazyListState directly)
val scrollState = rememberScrollableState { delta ->
    offset = (offset - delta).coerceIn(0f, max)
    delta
}
Modifier.scrollable(state = scrollState, orientation = Orientation.Vertical)

// Pinch + pan + rotate
val tState = rememberTransformableState { zoomChange, panChange, rotationChange ->
    scale *= zoomChange
    offset += panChange
    rotation += rotationChange
}
Modifier.transformable(state = tState)

// Swipeable / snap-points (Compose 1.6+, replaces deprecated swipeable)
val anchored = remember {
    AnchoredDraggableState(
        initialValue = DragValue.Center,
        anchors = DraggableAnchors {
            DragValue.Start at -1000f
            DragValue.Center at 0f
            DragValue.End at 1000f
        },
        positionalThreshold = { distance -> distance * 0.5f },
        velocityThreshold = { with(density) { 100.dp.toPx() } },
        snapAnimationSpec = spring(),
        decayAnimationSpec = splineBasedDecay(density),
    )
}
Modifier.anchoredDraggable(state = anchored, orientation = Orientation.Horizontal)
```

`AnchoredDraggableState` is the modern primitive behind swipe-to-dismiss, bottom sheets, and side drawers. The state exposes `currentValue`, `targetValue`, `progress`, and `offset` - everything you need to drive UI off the drag.

---

## `pointerInput` (low-level)

When the modifier API can't express your intent (multi-stage gestures, custom hit testing, fling chained with another animation), drop down to `pointerInput`.

```kotlin
Modifier.pointerInput(Unit) {
    detectDragGestures(
        onDragStart = { offset -> /* claim drag */ },
        onDrag = { change, dragAmount ->
            change.consume()
            offsetX += dragAmount.x
            offsetY += dragAmount.y
        },
        onDragEnd = { /* fling here */ },
        onDragCancel = { /* reset */ },
    )
}
```

Common detectors: `detectTapGestures`, `detectDragGestures`, `detectDragGesturesAfterLongPress`, `detectTransformGestures` (zoom + pan + rotate). All call `change.consume()` when they decide the event is theirs - omit it and parents get a second crack at the event.

The `key` parameter on `pointerInput(key)` is critical: when the key changes, the coroutine restarts. Use `Unit` for static handlers; pass the lambdas / state you depend on as keys when they can change.

---

## Custom Gesture Detector with `awaitPointerEventScope`

For detectors not provided by the standard library:

```kotlin
Modifier.pointerInput(Unit) {
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = true)
        val up = withTimeoutOrNull(viewConfiguration.longPressTimeoutMillis) {
            waitForUpOrCancellation()
        }
        if (up != null) {
            up.consume()
            onShortTap(down.position)
        } else {
            // pointer still down - either long-press or drag
            val drag = awaitTouchSlopOrCancellation(down.id) { change, _ ->
                change.consume()
            }
            if (drag != null) {
                onDrag(drag.position)
            } else {
                onLongPress(down.position)
            }
        }
    }
}
```

`awaitEachGesture` (Compose 1.6+, replaces `forEachGesture`) restarts cleanly per gesture and handles cancellation correctly. Always consume events you claim - unconsumed pointer events bubble to ancestors.

---

## `NestedScrollConnection`

When a scrolling container needs to coordinate with a parent (collapsing top-app-bar over a `LazyColumn`, swipe-to-refresh that intercepts the first vertical drag), implement `NestedScrollConnection`:

```kotlin
val maxHeader = with(LocalDensity.current) { 120.dp.toPx() }
var headerOffset by remember { mutableFloatStateOf(0f) }

val nestedScrollConnection = remember {
    object : NestedScrollConnection {
        override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
            // collapse header BEFORE the inner LazyColumn consumes scroll
            val delta = available.y
            val previous = headerOffset
            headerOffset = (headerOffset + delta).coerceIn(-maxHeader, 0f)
            val consumed = headerOffset - previous
            return Offset(0f, consumed)
        }

        override fun onPostScroll(
            consumed: Offset,
            available: Offset,
            source: NestedScrollSource,
        ): Offset {
            // re-expand header AFTER the inner reaches the top
            if (available.y > 0 && headerOffset < 0f) {
                val previous = headerOffset
                headerOffset = (headerOffset + available.y).coerceAtMost(0f)
                return Offset(0f, headerOffset - previous)
            }
            return Offset.Zero
        }
    }
}

Box(modifier = Modifier.nestedScroll(nestedScrollConnection)) {
    LazyColumn(
        contentPadding = PaddingValues(top = 120.dp),
        modifier = Modifier.fillMaxSize(),
    ) { /* items */ }

    Header(modifier = Modifier.offset { IntOffset(0, headerOffset.roundToInt()) })
}
```

Use case: collapsing toolbar with inner `LazyColumn`, swipe-to-refresh, parallax header. `onPreFling` and `onPostFling` exist for fling coordination too.

---

## Conflict Resolution Patterns

### Vertical scroll vs horizontal swipe

Compose's gesture system handles native nested scroll fine when you declare orientation explicitly. A `LazyColumn` (vertical) inside a `HorizontalPager` works out of the box: the pager only claims horizontal drags, the column only vertical. Don't reinvent it with `pointerInput` unless you have a reason.

### Tap vs drag

Use `awaitTouchSlopOrCancellation` to delay the "this is a drag" decision until the user has moved past the system slop threshold. Below the threshold, treat as a tap. The detectors above already handle this; if you write your own, mirror the pattern.

### System back gesture (Android 13+) vs custom horizontal pan

Android's predictive back gesture lives on the screen edges. If your custom horizontal pan starts from the edge, users will trigger back instead of your interaction half the time. Either:

- Avoid edge-starting horizontal pans (move the affordance inward by 24dp+).
- Opt into predictive back via `BackHandler { ... }` and skip your pan when back is in flight.
- Accept the conflict and document it (rare; usually a UX bug).

```kotlin
BackHandler(enabled = drawerOpen) { drawerOpen = false }
```

---

## Fling and Decay

Two paths:

**With `Animatable`:**
```kotlin
val offsetX = remember { Animatable(0f) }
val decay = splineBasedDecay<Float>(LocalDensity.current)

Modifier.draggable(
    state = rememberDraggableState { delta ->
        scope.launch { offsetX.snapTo(offsetX.value + delta) }
    },
    orientation = Orientation.Horizontal,
    onDragStopped = { velocity ->
        offsetX.animateDecay(velocity, decay)
    },
)
```

`splineBasedDecay` uses Android's standard fling friction (matches scrollers and `Scroller` exactly). For custom curves, `exponentialDecay(frictionMultiplier, absVelocityThreshold)`.

**With `AnchoredDraggableState`:**
The fling is wired automatically: when the drag stops, the state animates to the closest anchor honoring `velocityThreshold` and `positionalThreshold`. No manual decay needed.

---

## Common Patterns

### Pull-to-refresh (Material 3 1.3+)
```kotlin
PullToRefreshBox(isRefreshing = loading, onRefresh = ::refetch) {
    LazyColumn { items(list) { Row(it) } }
}
```

### Swipe-to-dismiss row (Material 3 1.2+)
```kotlin
val state = rememberSwipeToDismissBoxState()
SwipeToDismissBox(
    state = state,
    backgroundContent = { DismissBackground(state.dismissDirection) },
) { ItemRow(item) }

LaunchedEffect(state.currentValue) {
    if (state.currentValue == SwipeToDismissBoxValue.EndToStart) onDelete(item)
}
```

### Pinch-to-zoom image
```kotlin
var scale by remember { mutableFloatStateOf(1f) }
var offset by remember { mutableStateOf(Offset.Zero) }
val tState = rememberTransformableState { zoom, pan, _ ->
    scale = (scale * zoom).coerceIn(1f, 5f)
    offset += pan
}
Image(
    painter = painter,
    contentDescription = null,
    modifier = Modifier
        .graphicsLayer {
            scaleX = scale
            scaleY = scale
            translationX = offset.x
            translationY = offset.y
        }
        .transformable(tState),
)
```

---

## Sources

- [Android touch and input docs](https://developer.android.com/develop/ui/compose/touch-input)
- [Android nested scroll](https://developer.android.com/develop/ui/compose/touch-input/pointer-input/scroll)
- [AnchoredDraggable migration](https://developer.android.com/jetpack/androidx/releases/compose-foundation)
