# Recomposition and Animation

Recomposition is your friend until it's not. Animations change state every frame; if a frame's worth of state change recomposes a tree of 200 nodes, you ship a slideshow. This file covers when animations cause unnecessary recompositions and how to detect / fix them.

---

## Why Recomposition Matters for Animation

Compose recomposes any composable function that reads `MutableState` whose value changed. Animations change state every frame (16.67ms at 60fps, 8.33ms at 120fps). If a frame-rate state read happens at the composition phase, every reader recomposes every frame and you have jank.

The fix is to confine the state read to a phase that doesn't trigger recomposition:

- **Composition phase:** reading state here recomposes the function.
- **Layout phase:** reading state here re-runs measure/place but not composition.
- **Draw phase:** reading state here re-runs only drawing - the cheapest of the three.

The lambda-based modifiers (`Modifier.offset { ... }`, `Modifier.graphicsLayer { ... }`, `Modifier.drawBehind { ... }`) defer their state reads to layout or draw. The non-lambda variants read in composition and trigger recomposition.

---

## Diff: State Read in Composition vs Layout/Draw

```kotlin
// BAD - Modifier.offset(x) reads animatedX in composition.
//        Every frame: full composition for this Box.
val animatedX by animateFloatAsState(targetX, label = "x")
Box(Modifier.offset(x = animatedX.dp))
```

```kotlin
// GOOD - lambda defers read to placement (layout phase).
//         Composition runs once; placement re-runs each frame.
val animatedX by animateFloatAsState(targetX, label = "x")
Box(Modifier.offset { IntOffset(animatedX.roundToInt(), 0) })
```

Same idea for transforms:

```kotlin
// BAD
Box(Modifier.scale(animatedScale))
```

```kotlin
// GOOD - graphicsLayer reads in draw phase
Box(Modifier.graphicsLayer { scaleX = animatedScale; scaleY = animatedScale })
```

`graphicsLayer { ... }` is the right choice for any transform-only animation (translate, scale, rotate, alpha): composite-only, no layout pass, GPU-accelerated.

---

## `derivedStateOf` for Derived Values

When you compute a `Boolean` (or any cheap value) from a frequently-changing `State`, wrap it in `derivedStateOf` so readers only recompose when the derived value flips, not every time the source changes.

```kotlin
val lazyListState = rememberLazyListState()

// BAD - recomposes on every scroll position change (every pixel)
val isScrolled = lazyListState.firstVisibleItemIndex > 0 ||
    lazyListState.firstVisibleItemScrollOffset > 0

// GOOD - recomposes only when the boolean actually flips
val isScrolled by remember {
    derivedStateOf {
        lazyListState.firstVisibleItemIndex > 0 ||
            lazyListState.firstVisibleItemScrollOffset > 0
    }
}

if (isScrolled) Shadow()
```

Rule of thumb: if the predicate result changes far less often than its inputs, use `derivedStateOf`. If the predicate is expensive AND deterministic in its inputs, also use it (caches the result until inputs change).

---

## `key()` in Lists with Animation

```kotlin
// BAD - no keys; on insert/remove/reorder, items animate the WRONG slot
LazyColumn {
    items(list) { item ->
        AnimatedVisibility(item.expanded) { Row(item) }
    }
}
```

```kotlin
// GOOD - stable keys + Modifier.animateItem for reorder/insert/remove anim
LazyColumn {
    items(list, key = { it.id }) { item ->
        Row(modifier = Modifier.animateItem()) {
            AnimatedVisibility(item.expanded) { ItemRow(item) }
        }
    }
}
```

Without keys, Compose matches items by position - reorder the list, and item 0's visibility state slides into position 5's row. `Modifier.animateItem()` (Compose 1.7+, replaces the deprecated `Modifier.animateItemPlacement`) animates appearance, removal, and movement automatically when keys are stable.

---

## Layout Inspector (Recomposition Counts)

Android Studio's Layout Inspector exposes "Show recomposition counts" - it draws each composable with a counter and a "skipped" counter.

What to look for:

- A **static** component (header, footer, button you didn't touch) recomposing on every list scroll = somewhere up the tree, a state read leaks to the parent. Hoist the read.
- A node that recomposes 60 times per second during an animation = the animation state is being read at composition phase. Switch to lambda-based modifiers (`offset { }`, `graphicsLayer { }`).
- Skipped count high relative to recompositions = recomposition is happening but Compose is correctly detecting unchanged inputs and skipping the body. That's healthy.

Open it via Tools -> Layout Inspector while running on a connected device. Compose nodes show in the same tree as Android views.

---

## `Modifier.recomposeHighlighter()` (dev only)

Compose 1.6+ ships an opt-in `Modifier.recomposeHighlighter()` (you also find Cyril Pierre's standalone version on GitHub) that flashes a colored border on every recomposition. Drop it on suspicious nodes during dev:

```kotlin
@Composable
fun Header(title: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .recomposeHighlighter()                    // dev only
            .padding(16.dp),
    ) { Text(title) }
}
```

If the border flashes when you scroll a list further down the tree, you have a leak. Remove for prod.

---

## Macrobenchmark for Frame Timing

`androidx.benchmark:benchmark-macro` runs your app on a device or emulator and measures real frame timings via `FrameTimingMetric`.

```kotlin
@RunWith(AndroidJUnit4::class)
class ScrollBenchmark {
    @get:Rule val benchmarkRule = MacrobenchmarkRule()

    @Test fun scrollHomeFeed() = benchmarkRule.measureRepeated(
        packageName = "com.example.app",
        metrics = listOf(FrameTimingMetric()),
        iterations = 10,
        startupMode = StartupMode.WARM,
    ) {
        startActivityAndWait()
        val list = device.findObject(By.res("home-feed"))
        list.fling(Direction.DOWN)
        device.waitForIdle()
    }
}
```

Targets:
- **60Hz device:** p50 < 16.67ms, p99 < 30ms.
- **120Hz / ProMotion:** p50 < 8.33ms, p99 < 16ms.
- A single dropped frame is fine. A pattern of dropped frames during scroll = a fix needed.

---

## Baseline Profiles

Compose recomposition logic itself goes through JIT before AOT compilation kicks in - first launch and first scroll are the worst. Baseline Profiles bake hot paths into AOT at install time.

```kotlin
@RunWith(AndroidJUnit4::class)
class GenerateBaselineProfile {
    @get:Rule val rule = BaselineProfileRule()

    @Test fun generate() = rule.collect(packageName = "com.example.app") {
        startActivityAndWait()
        val list = device.findObject(By.res("home-feed"))
        list.fling(Direction.DOWN)
        device.waitForIdle()
    }
}
```

Run via the AGP `:app:generateBaselineProfile` task; commit the generated `baseline-prof.txt`. Typical wins: 20-40% reduction in jank on cold-start scrolls. Combine with Macrobenchmark to measure delta.

---

## Sources

- [Compose performance docs](https://developer.android.com/develop/ui/compose/performance)
- [Stability and recomposition](https://developer.android.com/develop/ui/compose/performance/stability)
- [Macrobenchmark](https://developer.android.com/topic/performance/benchmarking/macrobenchmark-overview)
- [Baseline Profiles](https://developer.android.com/topic/performance/baselineprofiles/overview)
