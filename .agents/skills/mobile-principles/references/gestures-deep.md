# Gestures Deep Dive

Deep dive on gestures across mobile platforms. Covers conflict resolution, momentum, and complex composition.

---

## Platform-specific gesture APIs

### Web - Pointer Events

The Pointer Events API unifies mouse, touch, and stylus into one event model. Use it instead of `touchstart`/`mousedown` to avoid double-handling on hybrid devices. CSS `touch-action` is the first lever: set it to `none` only on surfaces you fully own (drawing canvas, custom pan), or `pan-y` to keep vertical scroll while reserving horizontal pans.

```js
// Element CSS: touch-action: none;
let startX = 0, startY = 0, dragging = false;
el.addEventListener('pointerdown', (e) => {
  dragging = true;
  startX = e.clientX; startY = e.clientY;
  el.setPointerCapture(e.pointerId); // route move/up to el even if pointer leaves
});
el.addEventListener('pointermove', (e) => {
  if (!dragging) return;
  el.style.transform = `translate(${e.clientX - startX}px, ${e.clientY - startY}px)`;
});
el.addEventListener('pointerup', (e) => {
  dragging = false;
  el.releasePointerCapture(e.pointerId);
});
```

For multi-touch (pinch, rotate) and momentum, prefer a maintained library: `@use-gesture/react` (React-friendly, handles inertia) or Hammer.js (framework-agnostic, recognizes pinch, rotate, swipe, press).

### SwiftUI - Gesture composition

SwiftUI exposes `DragGesture`, `LongPressGesture`, `MagnifyGesture` (iOS 17+, was `MagnificationGesture`), `RotateGesture` (iOS 17+, was `RotationGesture`), and `TapGesture`. Combine via `.simultaneousGesture()`, `.highPriorityGesture()`, or operators (`SequenceGesture`, `SimultaneousGesture`, `ExclusiveGesture`).

```swift
struct DragToReveal: View {
  @State private var offset: CGSize = .zero

  var body: some View {
    let press = LongPressGesture(minimumDuration: 0.2)
    let drag = DragGesture()
      .onChanged { offset = $0.translation }
      .onEnded { _ in withAnimation(.spring) { offset = .zero } }

    return Card()
      .offset(offset)
      .gesture(press.sequenced(before: drag))
  }
}
```

`.sequenced(before:)` is the canonical "press, then drag" pattern: the drag only starts once the long-press has fired. Used by reorderable lists and draggable home-screen icons.

### Compose - Modifier-based gestures

Compose splits gestures into high-level modifiers (`Modifier.draggable`, `Modifier.scrollable`, `Modifier.transformable`) and a low-level pointer-input DSL (`detectDragGestures`, `detectTapGestures`, `awaitPointerEventScope`).

```kotlin
@Composable
fun CustomLongPressDrag(onCommit: (Offset) -> Unit) {
  var offset by remember { mutableStateOf(Offset.Zero) }
  Box(Modifier
    .offset { IntOffset(offset.x.toInt(), offset.y.toInt()) }
    .pointerInput(Unit) {
      awaitPointerEventScope {
        while (true) {
          val down = awaitFirstDown()
          val longPress = awaitLongPressOrCancellation(down.id) ?: continue
          drag(longPress.id) { it.consume(); offset += it.positionChange() }
          onCommit(offset)
        }
      }
    }
  )
}
```

For 90% of cases, use `Modifier.draggable` (1D) or `Modifier.transformable` (pan + zoom + rotate). Drop to `awaitPointerEventScope` only for custom state machines.

---

## Gesture conflicts and resolution

Two gestures can claim the same pointer stream. The system picks one, or runs them in parallel. Three recurring conflicts:

- **Vertical scroll vs horizontal swipe.** Whichever direction crosses the threshold first wins; the other is locked out for that sequence. iOS `UICollectionView` and Compose `LazyColumn` both implement this. Align with it.
- **Long-press vs drag.** Finger up before press threshold (~500ms) = tap; after = drag armed. SwiftUI: `LongPressGesture.sequenced(before: DragGesture)`. Compose: `detectDragGesturesAfterLongPress`.
- **Native back-swipe vs custom horizontal pan.** iOS reserves the left ~20pt edge for `UINavigationController` pop; the custom gesture must yield, otherwise navigation breaks. Bind your gesture to a non-edge area or filter pointer-downs by x.

**SwiftUI conflict resolution with `GestureMask`:**

```swift
ScrollView {
  ForEach(items) { item in
    Row(item)
      .simultaneousGesture(
        DragGesture(minimumDistance: 20)
          .onChanged(handleSwipeAction),
        including: .gesture // run our gesture, but let the ScrollView still handle vertical scroll
      )
  }
}
```

`including: .gesture` keeps the parent ScrollView's vertical scroll alive while the row's horizontal swipe is detected.

**Compose conflict resolution with `nestedScroll`:**

```kotlin
val connection = remember {
  object : NestedScrollConnection {
    override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
      // Consume vertical drag for header collapse before the inner list scrolls
      return Offset(0f, collapseHeader(available.y))
    }
  }
}
Box(Modifier.nestedScroll(connection)) { CollapsibleHeader(); LazyColumn { /* ... */ } }
```

`NestedScrollConnection` is the contract between an outer container and an inner scrollable: `onPreScroll` runs before the child consumes, `onPostScroll` after. Used by collapsing toolbars, pull-to-refresh, sheet drag.

---

## Momentum and fling

When the finger lifts mid-gesture, content should decelerate naturally, not stop dead.

**SwiftUI** - `DragGesture.Value.predictedEndTranslation` is the system's estimate of the landing point if released now. Project it and animate with a spring.

```swift
.onEnded { value in
  let projected = value.predictedEndTranslation.height
  let target = abs(projected) > 100 ? sign(projected) * sheetMaxOffset : 0
  withAnimation(.interpolatingSpring(stiffness: 200, damping: 25)) { offset = target }
}
```

iOS 17+ also exposes `.gestureVelocity` for raw velocity, which composes nicely with `phaseAnimator`.

**Compose** - `Animatable.animateDecay()` with `splineBasedDecay()` reproduces the Android system fling curve.

```kotlin
val offset = remember { Animatable(0f) }
val flingSpec = rememberSplineBasedDecay<Float>()

Modifier.pointerInput(Unit) {
  detectDragGestures(
    onDrag = { c, d -> scope.launch { offset.snapTo(offset.value + d.x) }; c.consume() },
    onDragEnd = { scope.launch { offset.animateDecay(velocity, flingSpec) } },
  )
}
```

**Web** - Two routes. For native snapping, `scroll-snap-type: y mandatory` + `scroll-snap-align: start` on children: the browser handles fling and snap. For custom canvases, capture velocity at `pointerup` and decay it in a `requestAnimationFrame` loop until below ~0.1 px/frame.

---

## Pull-to-refresh canonical implementation

The simplest gesture on the surface, still the most botched. Use the platform primitives, stop reimplementing.

**Compose - Material 3 1.3+:**

```kotlin
@Composable
fun Feed(items: List<Item>, onRefresh: suspend () -> Unit) {
  var isRefreshing by remember { mutableStateOf(false) }
  val scope = rememberCoroutineScope()
  PullToRefreshBox(
    isRefreshing = isRefreshing,
    onRefresh = { scope.launch { isRefreshing = true; onRefresh(); isRefreshing = false } },
  ) {
    LazyColumn { items(items) { Row(it) } }
  }
}
```

**SwiftUI - iOS 15+:**

```swift
List(items) { Row($0) }.refreshable { await viewModel.refresh() }
```

`.refreshable` propagates through the environment - inner `List` or `ScrollView` (iOS 16+) inherits the closure. Spinner, threshold, and haptic are platform-managed.

**Web - custom transform with overscroll-behavior:**

```js
// Container CSS: overflow-y:auto; overscroll-behavior: contain;
let startY = 0, pulled = 0, pulling = false;
scroll.addEventListener('pointerdown', (e) => {
  if (scroll.scrollTop === 0) { startY = e.clientY; pulling = true; }
});
scroll.addEventListener('pointermove', (e) => {
  if (!pulling) return;
  pulled = Math.max(0, e.clientY - startY);
  scroll.style.transform = `translateY(${Math.min(pulled * 0.5, 80)}px)`;
});
scroll.addEventListener('pointerup', async () => {
  if (!pulling) return;
  pulling = false;
  scroll.style.transition = 'transform 0.2s';
  scroll.style.transform = 'translateY(0)';
  if (pulled > 60) await refresh();
  setTimeout(() => scroll.style.transition = '', 200);
});
```

`overscroll-behavior: contain` blocks Safari's native bounce-to-reload and chained scroll, leaving you in control. An `IntersectionObserver` on a sentinel above the list can swap the manual pointer math for "trigger when the sentinel becomes fully visible".

---

## Sources

- Apple HIG, Gestures: https://developer.apple.com/design/human-interface-guidelines/gestures
- Material Design, Gestures: https://m3.material.io/foundations/interaction/gestures
- W3C Pointer Events: https://www.w3.org/TR/pointerevents/
