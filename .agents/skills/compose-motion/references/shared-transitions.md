# Shared Element Transitions in Compose

`SharedTransitionLayout` morphs an element's bounds, position, and (with `sharedBounds`) shape between two destinations. The receiver lays out both states in the same coordinate space and interpolates between them. Stable since Compose 1.7 - this is the canonical hero / detail / picture-in-picture pattern.

---

## Setup

The whole machinery lives behind two scopes:

- `SharedTransitionScope` - exposes the `Modifier.sharedElement(...)` and `Modifier.sharedBounds(...)` extensions.
- `AnimatedVisibilityScope` - the visibility context that drives the in/out transition (every `AnimatedContent` content lambda is one; every `composable<Route>` block in `NavHost` exposes one).

Wrap the screen swap in `SharedTransitionLayout` and pass both scopes down. `Modifier.sharedElement` is for elements that keep the same shape and aspect (an image moving across screens). `Modifier.sharedBounds` is for content whose size, shape, or content meaningfully changes (a card expanding into a full panel, a button morphing into a header).

Compose 1.7+ baseline. With androidx.navigation 2.8+ on Compose, scopes are exposed directly inside `composable<Route>` lambdas.

---

## Recipe 1 - Card to Detail

```kotlin
sealed interface Screen {
    data object List : Screen
    data class Detail(val item: Item) : Screen
}

@Composable
fun App() {
    var current by remember { mutableStateOf<Screen>(Screen.List) }

    SharedTransitionLayout {
        AnimatedContent(
            targetState = current,
            label = "screen",
            transitionSpec = { fadeIn() togetherWith fadeOut() },
        ) { screen ->
            when (screen) {
                Screen.List -> ListScreen(
                    onOpen = { current = Screen.Detail(it) },
                    sts = this@SharedTransitionLayout,
                    avs = this@AnimatedContent,
                )
                is Screen.Detail -> DetailScreen(
                    item = screen.item,
                    onBack = { current = Screen.List },
                    sts = this@SharedTransitionLayout,
                    avs = this@AnimatedContent,
                )
            }
        }
    }
}

@Composable
fun ListScreen(
    onOpen: (Item) -> Unit,
    sts: SharedTransitionScope,
    avs: AnimatedVisibilityScope,
) {
    LazyColumn { items(items, key = { it.id }) { item ->
        with(sts) {
            Card(
                onClick = { onOpen(item) },
                modifier = Modifier.sharedBounds(
                    sharedContentState = rememberSharedContentState("card-${item.id}"),
                    animatedVisibilityScope = avs,
                ),
            ) {
                Image(
                    painter = item.painter,
                    contentDescription = null,
                    modifier = Modifier.sharedElement(
                        state = rememberSharedContentState("image-${item.id}"),
                        animatedVisibilityScope = avs,
                    ),
                )
                Text(item.title)
            }
        }
    } }
}

@Composable
fun DetailScreen(
    item: Item,
    onBack: () -> Unit,
    sts: SharedTransitionScope,
    avs: AnimatedVisibilityScope,
) {
    with(sts) {
        Column(
            modifier = Modifier.sharedBounds(
                sharedContentState = rememberSharedContentState("card-${item.id}"),
                animatedVisibilityScope = avs,
            ),
        ) {
            Image(
                painter = item.painter,
                contentDescription = null,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(360.dp)
                    .sharedElement(
                        state = rememberSharedContentState("image-${item.id}"),
                        animatedVisibilityScope = avs,
                    ),
            )
            Text(item.title, style = MaterialTheme.typography.headlineLarge)
            Text(item.description)
        }
    }
}
```

The card outer shape uses `sharedBounds` (different size/shape between list and detail). The image uses `sharedElement` (same content, just translated and scaled). Keys are stable per item id.

---

## Recipe 2 - Image Hero

A photo grid that opens into a full-bleed photo detail. Same key on the `Image` composable on both sides; the framework interpolates the bounds.

```kotlin
// Grid:
Image(
    painter = item.painter,
    contentDescription = null,
    modifier = Modifier
        .aspectRatio(1f)
        .sharedElement(
            state = rememberSharedContentState("photo-${item.id}"),
            animatedVisibilityScope = avs,
            boundsTransform = { _, _ ->
                spring(stiffness = Spring.StiffnessMediumLow, dampingRatio = 0.85f)
            },
        ),
)

// Detail:
Image(
    painter = item.painter,
    contentDescription = null,
    contentScale = ContentScale.Fit,
    modifier = Modifier
        .fillMaxWidth()
        .sharedElement(
            state = rememberSharedContentState("photo-${item.id}"),
            animatedVisibilityScope = avs,
        ),
)
```

`boundsTransform` (declared on the source side typically, both is fine) controls the spring on the bounds interpolation. Default is a snappy spring; soften for a more cinematic feel.

---

## Recipe 3 - Tab Header Morph in `HorizontalPager`

A header strip whose accent pill morphs as the user swipes between tabs. `SharedTransitionLayout` wraps the pager; each page declares its own `sharedElement` with the SAME key for the morphing element.

```kotlin
SharedTransitionLayout {
    HorizontalPager(state = pagerState) { pageIndex ->
        AnimatedContent(
            targetState = pageIndex,
            label = "tabPage",
        ) { page ->
            Column {
                Box(
                    modifier = Modifier
                        .height(48.dp)
                        .background(palette[page], RoundedCornerShape(24.dp))
                        .sharedElement(
                            state = rememberSharedContentState("tab-pill"),
                            animatedVisibilityScope = this@AnimatedContent,
                        ),
                )
                TabContent(page)
            }
        }
    }
}
```

Note: real-world tab bars usually do this with a single backing layout reading the pager's settled offset directly - shared elements shine when the morph crosses screen boundaries, not strictly within a single fixed layout.

---

## `rememberSharedContentState` - Keys Discipline

**Rule:** keys must be stable AND unique per logical element across the screens that share it.

```kotlin
// BAD - index changes when the list reorders, transition mistargets
items.forEachIndexed { i, item ->
    Image(modifier = Modifier.sharedElement(rememberSharedContentState("hero-$i"), avs))
}
```

```kotlin
// GOOD - id-based
items.forEach { item ->
    Image(modifier = Modifier.sharedElement(rememberSharedContentState("hero-${item.id}"), avs))
}
```

If the same screen contains multiple shared elements, namespace them: `"image-${item.id}"`, `"title-${item.id}"`. Ambiguous keys = wrong element gets matched and you get a teleporting image.

---

## Bound Modifiers and `sharedBounds` Knobs

`Modifier.sharedBounds(...)` accepts:

- `enter` / `exit`: `EnterTransition` / `ExitTransition` for content INSIDE the morphing bounds (default `fadeIn()` / `fadeOut()`).
- `boundsTransform`: spring/tween for the bounds interpolation itself.
- `resizeMode`: `ScaleToBounds(contentScale, alignment)` (default - scales content to match bounds, useful when content shape matches) or `RemeasureToBounds` (re-measures content at every step, useful for text reflow).
- `clipInOverlayDuringTransition`: an `OverlayClip(shape)` applied while the element is in the overlay. Use a rounded shape that matches your destination card to avoid hard rectangle flashes.
- `placeHolderSize`: how the source slot reserves space during the transition (`PlaceHolderSize.contentSize` by default, `PlaceHolderSize.animatedSize` to animate the gap).

Quick template for a card-to-screen morph:

```kotlin
Modifier.sharedBounds(
    sharedContentState = rememberSharedContentState("card-${id}"),
    animatedVisibilityScope = avs,
    enter = fadeIn(tween(150)),
    exit = fadeOut(tween(80)),
    resizeMode = SharedTransitionScope.ResizeMode.RemeasureToBounds,
    clipInOverlayDuringTransition = OverlayClip(RoundedCornerShape(24.dp)),
)
```

---

## Compose Navigation Integration

With androidx.navigation 2.8+ for Compose, scopes are accessible directly inside `composable<Route>` lambdas via `LocalNavAnimatedVisibilityScope` and a `SharedTransitionLayout` wrapping the `NavHost`.

```kotlin
SharedTransitionLayout {
    NavHost(navController, startDestination = HomeRoute) {
        composable<HomeRoute> {
            HomeScreen(
                sts = this@SharedTransitionLayout,
                avs = this,                         // AnimatedVisibilityScope
                onOpen = { id -> navController.navigate(DetailRoute(id)) },
            )
        }
        composable<DetailRoute> { backStackEntry ->
            val args: DetailRoute = backStackEntry.toRoute()
            DetailScreen(
                id = args.id,
                sts = this@SharedTransitionLayout,
                avs = this,
            )
        }
    }
}
```

Pass `sts` and `avs` exactly as you would inside a manual `AnimatedContent`. The `composable` lambda IS an `AnimatedVisibilityScope`. If you ship Compose Navigation 3 (stable expected early 2026), the surface is the same - the ergonomics get a bit nicer with type-safe routes already inferred.

---

## Gotchas

- **Mismatched keys = no animation.** Silent failure. Verify with Layout Inspector's animation panel; both sides must show the same `SharedContentState`.
- **Unmounted source.** Don't put a `sharedElement` inside a `LazyColumn` item that may be scrolled off when the transition starts. The framework needs the source slot to be measurable to compute origin bounds. Workaround: scroll to make the source visible before triggering navigation, or use `sharedBounds` on the entire visible row.
- **Performance.** Each shared element is a render pass through the overlay. Sharing 20+ elements at once tanks frame rate. Share the hero image and the title; let everything else fade.
- **Z-order during transition.** Shared elements render in the overlay above the rest of the layout. If you have UI that should sit above the morph (top app bar, fab), keep it OUTSIDE `SharedTransitionLayout` or accept the overlap.
- **Reduced motion.** Wrap shared transitions in a check (see `../SKILL.md` reduced-motion section) and replace with a `snap()` `boundsTransform` and an instant `tween(0)` enter/exit.

---

## Sources

- [Android SharedTransitionLayout docs](https://developer.android.com/develop/ui/compose/animation/shared-elements)
- [skydoves/Orbital](https://github.com/skydoves/Orbital) - shared element transitions library and recipes
- [androidx.navigation Compose animations](https://developer.android.com/jetpack/androidx/releases/navigation)
