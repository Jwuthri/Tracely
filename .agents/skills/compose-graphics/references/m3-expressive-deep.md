# Material 3 Expressive: Deep-Dive

M3 Expressive is the 2025 Material 3 evolution. Springs replace fixed-duration tweens for spatial properties; shape morphing replaces step transitions; choreography becomes the unit of motion design rather than the individual easing curve. Use it where attention should anchor: hero moments, key actions, brand-defining surfaces. Default the rest to Standard.

---

## MotionScheme Tokens

The theme exposes six animation specs through `MaterialTheme.motionScheme`. They split along two axes.

### Spatial vs Effects

| Domain | Token family | Implementation |
|---|---|---|
| **Spatial** - position, size, scale | `*SpatialSpec()` | Spring-based. Inertia, overshoot, settle. |
| **Effects** - opacity, color, elevation | `*EffectsSpec()` | Tween-based. Predictable, no overshoot. |

> Why split? A bouncing alpha looks broken (opacity overshoots into negative or above 1). A tweened position looks robotic (no inertia). The split codifies what works and what doesn't.

### Speed Variants

| Speed | Spatial | Effects |
|---|---|---|
| Fast | `fastSpatialSpec()` (~ 200ms) | `fastEffectsSpec()` (~ 150ms) |
| Default | `defaultSpatialSpec()` (~ 350ms) | `defaultEffectsSpec()` (~ 250ms) |
| Slow | `slowSpatialSpec()` (~ 600ms) | `slowEffectsSpec()` (~ 400ms) |

### When to Override

Rare. Reach for the tokens 95% of the time - they encode Material's calibrated spring stiffness, damping, and visibilityThreshold values. Only override when:

- The brand demands a unique signature spring (extra-bouncy hero, e.g. a game).
- You're animating a non-Material surface (custom canvas).
- A11y testing surfaces a specific issue (e.g. a token spring is too long for vestibular comfort).

In those cases, build a custom spring once and reuse it through a small abstraction. Don't sprinkle ad-hoc `spring(stiffness = ..., dampingRatio = ...)` calls across the app.

---

## Choreography Patterns

Choreography is sequencing multiple element animations into a single perceived motion. Three patterns cover most hero moments.

### Sequential Reveal

Cards or list items stagger in. The eye reads left-to-right, top-to-bottom. Stagger 50ms per item.

```kotlin
items.forEachIndexed { index, item ->
    val visible by produceState(false, index) {
        delay(index * 50L)
        value = true
    }
    AnimatedVisibility(
        visible = visible,
        enter = slideInVertically(
            animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec()
        ) + fadeIn(animationSpec = MaterialTheme.motionScheme.defaultEffectsSpec())
    ) {
        Card(item)
    }
}
```

### Hero-First

The focal element animates first. Supporting elements follow 100-150ms later. Establishes hierarchy.

```kotlin
val heroVisible by produceState(false) { value = true }
val supportingVisible by produceState(false) { delay(150); value = true }

Column {
    AnimatedVisibility(heroVisible, /* hero springs */) { HeroCard() }
    AnimatedVisibility(supportingVisible, /* supporting springs */) { Metadata() }
}
```

### Coordinated Exit

All elements exit on the same `slowEffectsSpec()`. No staggering on exit - it slows perceived dismissal and feels sluggish.

```kotlin
AnimatedVisibility(
    visible = sheetVisible,
    enter = /* staggered enter */,
    exit = fadeOut(animationSpec = MaterialTheme.motionScheme.slowEffectsSpec())
) { /* ... */ }
```

> **Enter is choreography. Exit is uniform.** Never stagger on exit unless you have a very specific narrative reason.

---

## Code Example: Hero Card with Full Choreography

Tap a card. Shape morphs (Circle to Cookie4Sided), color transitions (primary to primaryContainer), elevation springs up, content fades in 100ms after the morph starts.

```kotlin
@Composable
fun ExpressiveHeroCard(item: Item) {
    var expanded by remember { mutableStateOf(false) }
    val transition = updateTransition(expanded, label = "hero")

    val morphProgress by transition.animateFloat(
        transitionSpec = { MaterialTheme.motionScheme.slowSpatialSpec() },
        label = "morph"
    ) { if (it) 1f else 0f }

    val color by transition.animateColor(
        transitionSpec = { MaterialTheme.motionScheme.defaultEffectsSpec() },
        label = "color"
    ) {
        if (it) MaterialTheme.colorScheme.primaryContainer
        else MaterialTheme.colorScheme.primary
    }

    val elevation by transition.animateDp(
        transitionSpec = { MaterialTheme.motionScheme.defaultSpatialSpec() },
        label = "elevation"
    ) { if (it) 12.dp else 2.dp }

    val contentAlpha by transition.animateFloat(
        transitionSpec = {
            tween(
                durationMillis = 250,
                delayMillis = 100,
                easing = FastOutSlowInEasing
            )
        },
        label = "alpha"
    ) { if (it) 1f else 0f }

    val morph = remember { Morph(MaterialShapes.Circle, MaterialShapes.Cookie4Sided) }

    Box(
        modifier = Modifier
            .size(200.dp)
            .shadow(elevation, shape = RoundedCornerShape(16.dp))
            .clip(GenericShape { _, _ ->
                addPath(morph.toPath(morphProgress).asAndroidPath().asComposePath())
            })
            .background(color)
            .clickable { expanded = !expanded }
    ) {
        Box(modifier = Modifier.alpha(contentAlpha)) {
            Text(item.title, modifier = Modifier.padding(24.dp))
        }
    }
}
```

What ships in this 30-line composable: spatial spring on size and elevation, tweened color and content fade, content reveal delayed 100ms after the shape begins morphing. The hierarchy is preserved: shape leads, color and elevation join immediately, content waits its turn.

---

## Shape Morphing Patterns

`androidx.graphics.shapes` is the M3 Expressive shape engine. Two key APIs.

### Predefined Shapes

```kotlin
MaterialShapes.Circle
MaterialShapes.Square
MaterialShapes.Triangle
MaterialShapes.Pentagon
MaterialShapes.Cookie4Sided
MaterialShapes.Cookie6Sided
MaterialShapes.Cookie9Sided
MaterialShapes.Cookie12Sided
MaterialShapes.Heart
MaterialShapes.Sunny
MaterialShapes.Pill
```

These are tuned for smooth morphing. They share consistent vertex counts after subdivision, which means `Morph` can interpolate without artifacts.

### Morph

```kotlin
val morph = remember { Morph(MaterialShapes.Circle, MaterialShapes.Cookie4Sided) }
val path = morph.toPath(progress) // progress in 0..1
```

Combine with springs for organic feel:

```kotlin
val progress by animateFloatAsState(
    targetValue = if (active) 1f else 0f,
    animationSpec = MaterialTheme.motionScheme.slowSpatialSpec(),
    label = "morph"
)
```

> **Always use the spring tokens with morphing.** A linear morph feels mechanical; a spring morph feels alive.

### Custom Shapes

If `MaterialShapes` doesn't cover your need, use `RoundedPolygon` directly:

```kotlin
val custom = remember {
    RoundedPolygon(
        numVertices = 5,
        radius = 1f,
        rounding = CornerRounding(0.2f, smoothing = 0.5f)
    )
}
val morph = remember { Morph(MaterialShapes.Circle, custom) }
```

Vertex counts must align between the two shapes for smooth morphing. The library subdivides automatically when they don't match, but the result is choppier.

---

## Anti-Patterns Specific to Expressive

### 1. Expressive on Every Button

```kotlin
// BAD - every micro-interaction overshoots, UI feels chaotic
MaterialTheme(motionScheme = MotionScheme.expressive()) {
    Scaffold {
        Button(onClick = ...) { Text("Action") }
        IconButton(onClick = ...) { /* icon */ }
        // Every press now overshoots
    }
}

// GOOD - Standard for chrome, Expressive scoped to hero
MaterialTheme(motionScheme = MotionScheme.standard()) {
    Scaffold {
        // Hero region overrides locally
        MaterialTheme(motionScheme = MotionScheme.expressive()) {
            HeroCard()
        }
        // Buttons elsewhere stay calm
    }
}
```

### 2. Expressive on Sub-100ms Interactions

Overshoot is wasted on a 100ms toggle - the eye doesn't perceive it. Use Standard or a flat tween.

```kotlin
// BAD - bouncy 80ms toggle, the bounce is invisible
val color by animateColorAsState(
    targetValue = if (on) Color.Green else Color.Gray,
    animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()  // wrong domain too
)

// GOOD - effects spec for color, fast and flat
val color by animateColorAsState(
    targetValue = if (on) Color.Green else Color.Gray,
    animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()
)
```

### 3. Mixing Spatial Spec on Effects (and vice versa)

```kotlin
// BAD - bouncy alpha overshoots into invalid range, looks broken
val alpha by animateFloatAsState(
    targetValue = if (visible) 1f else 0f,
    animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec()
)

// GOOD - effects spec for alpha
val alpha by animateFloatAsState(
    targetValue = if (visible) 1f else 0f,
    animationSpec = MaterialTheme.motionScheme.defaultEffectsSpec()
)
```

### 4. Stagger on Exit

```kotlin
// BAD - staggered exit slows dismissal, feels sluggish
items.forEachIndexed { i, item ->
    AnimatedVisibility(
        visible = visible,
        exit = fadeOut(animationSpec = tween(delayMillis = i * 50))
    ) { Card(item) }
}

// GOOD - unified exit
items.forEach { item ->
    AnimatedVisibility(
        visible = visible,
        exit = fadeOut(animationSpec = MaterialTheme.motionScheme.slowEffectsSpec())
    ) { Card(item) }
}
```

---

## Sources

- [Material 3 Expressive blog](https://m3.material.io/blog/m3-expressive-motion-theming)
- [Material 3 Motion specs](https://m3.material.io/styles/motion/overview/specs)
- [androidx.graphics.shapes release notes](https://developer.android.com/jetpack/androidx/releases/graphics-shapes)
