---
name: compose-graphics
description: "Advanced Compose visuals - Material 3 Expressive motion physics, AGSL shaders (Android 13+), Canvas/DrawScope generative, graphicsLayer effects."
---

# Compose Graphics

> Advanced Compose visuals: M3 Expressive motion physics, AGSL shaders (Android 13+), Canvas / DrawScope, graphicsLayer effects.
> Loaded for advanced thesis (shader, expressive, M3 Expressive, AGSL, Canvas, holographic).
> Foundation: `../compose-motion/SKILL.md` covers basics. Concise rules here. Deep-dive in `references/`.

---

## Decision Tree: Which API for Which Need

| Need | API |
|---|---|
| Spring physics with bounce / overshoot | `MotionScheme.expressive()` (M3 Expressive) |
| Pixel-level shader | `RuntimeShader` + `Modifier.graphicsLayer { renderEffect = ... }` (Android 13+) |
| Generative drawing (paths, particles, fractals) | `Canvas { drawScope -> ... }` |
| GPU effects (blur, shadows, color filters) | `Modifier.graphicsLayer { renderEffect = ... }` or `Modifier.blur(...)` |
| Adaptive system materials (Material You glassmorphism) | `Modifier.background(MaterialTheme.colorScheme.surfaceContainerHighest)` |
| Liquid glass on Android | AGSL shader recipe (no native API like iOS yet) |

---

## Domain 1: Material 3 Expressive

### What It Is

The 2025 Material 3 evolution introduces spring-based motion physics replacing fixed-duration tweens. New shape morphing API via `androidx.graphics.shapes`. New `MotionScheme` selectable on the theme. Aimed at hero moments, key interactions, brand-defining UI.

### MotionScheme

| Scheme | Personality | Use For |
|---|---|---|
| `MotionScheme.standard()` | Calmer, less overshoot | Default for chrome, lists, navigation |
| `MotionScheme.expressive()` | More overshoot, longer settle | Hero reveals, FABs, primary CTAs |

Apply on the theme:

```kotlin
MaterialTheme(motionScheme = MotionScheme.expressive()) {
    // children read tokens via MaterialTheme.motionScheme.*
}
```

Tokens exposed:

| Token | Domain | Speed |
|---|---|---|
| `fastSpatialSpec()` | Position / size | < 200ms |
| `defaultSpatialSpec()` | Position / size | ~ 350ms |
| `slowSpatialSpec()` | Position / size | ~ 600ms |
| `fastEffectsSpec()` | Opacity / color | < 150ms |
| `defaultEffectsSpec()` | Opacity / color | ~ 250ms |
| `slowEffectsSpec()` | Opacity / color | ~ 400ms |

> **Spatial vs Effects:** spatial = anything physical (height, offset, scale). Effects = visual properties without inertia (alpha, color, elevation). Springs feel natural for spatial; tweens feel right for effects. The tokens encode this for you.

### Hero Card Expand (Expressive Springs)

```kotlin
@Composable
fun ExpressiveHero() {
    var expanded by remember { mutableStateOf(false) }
    MaterialTheme(motionScheme = MotionScheme.expressive()) {
        val transition = updateTransition(targetState = expanded, label = "expand")
        val height by transition.animateDp(
            transitionSpec = { MaterialTheme.motionScheme.slowSpatialSpec() },
            label = "height"
        ) { if (it) 400.dp else 100.dp }
        val alpha by transition.animateFloat(
            transitionSpec = { MaterialTheme.motionScheme.defaultEffectsSpec() },
            label = "alpha"
        ) { if (it) 1f else 0f }

        Card(
            modifier = Modifier
                .fillMaxWidth()
                .height(height)
                .clickable { expanded = !expanded }
        ) {
            Box(modifier = Modifier.alpha(alpha)) {
                Text("Detail content", modifier = Modifier.padding(24.dp))
            }
        }
    }
}
```

### Spring Tuning Recipes

| Mood | Spec |
|---|---|
| Hero reveal | `spring(stiffness = Spring.StiffnessLow, dampingRatio = Spring.DampingRatioMediumBouncy)` |
| Snappy expressive | `spring(stiffness = Spring.StiffnessMediumLow, dampingRatio = 0.7f)` |
| Calm spatial | `MaterialTheme.motionScheme.defaultSpatialSpec()` (use the token) |
| Critical (no overshoot) | `spring(stiffness = Spring.StiffnessHigh, dampingRatio = 1f)` |

### Shape Morphing (M3 Expressive 1.3+)

`androidx.graphics.shapes` ships predefined morphable shapes (`MaterialShapes.Circle`, `Pentagon`, `Cookie4Sided`, `Sunny`, `Heart`, etc.) and a `Morph(start, end)` interpolator.

```kotlin
val morph = remember { Morph(MaterialShapes.Circle, MaterialShapes.Cookie4Sided) }
val progress by animateFloatAsState(
    targetValue = if (active) 1f else 0f,
    animationSpec = MaterialTheme.motionScheme.slowSpatialSpec(),
    label = "morph"
)
Box(
    modifier = Modifier
        .size(96.dp)
        .clip(GenericShape { size, _ ->
            addPath(
                morph.toPath(progress).asAndroidPath().asComposePath()
            )
        })
        .background(MaterialTheme.colorScheme.primary)
)
```

### When to Use Expressive vs Standard

- **Expressive:** hero moments, key interactions, FABs, primary CTAs. 1-3% of UI.
- **Standard:** default for the rest of the app. Mixing too much Expressive feels chaotic - every element fighting for attention.

---

## Domain 2: AGSL Shaders (Android 13+)

### What It Is

AGSL is Android's shader language. Similar to GLSL with simplifications (`half4` instead of `vec4`, restricted feature set, sandbox-safe). `RuntimeShader` compiles your AGSL source. Bind to a Compose modifier via `Modifier.graphicsLayer { renderEffect = ... }`.

### Setup

```kotlin
@Composable
fun ShaderEffect(content: @Composable () -> Unit) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
        // Android 12 and below: skip the shader, render content as-is.
        content()
        return
    }
    val shader = remember { RuntimeShader(AGSL_SOURCE) }
    val time by produceState(0f) {
        while (true) {
            withFrameMillis { ms ->
                value = ms / 1000f
            }
        }
    }
    Box(
        modifier = Modifier
            .onSizeChanged {
                shader.setFloatUniform("resolution", it.width.toFloat(), it.height.toFloat())
            }
            .graphicsLayer {
                shader.setFloatUniform("time", time)
                renderEffect = RenderEffect
                    .createRuntimeShaderEffect(shader, "image")
                    .asComposeRenderEffect()
            }
    ) { content() }
}
```

> **Always gate on `Build.VERSION.SDK_INT >= 33`.** Pre-Android 13 fallback: render the content unmodified, or use `Modifier.blur()` / a static gradient overlay.

### Recipe: Touch Ripple

AGSL source:

```glsl
// ripple.agsl
uniform float2 resolution;
uniform float2 origin;
uniform float time;
uniform shader image;

half4 main(float2 fragCoord) {
    float2 toOrigin = fragCoord - origin;
    float dist = length(toOrigin);
    float wave = sin(dist * 0.05 - time * 8.0) * 0.05;
    float falloff = 1.0 / max(dist * 0.01, 1.0);
    float2 dir = toOrigin / max(dist, 0.0001);
    float2 displaced = fragCoord + dir * wave * falloff * 50.0;
    return image.eval(displaced);
}
```

Compose binding (state-driven `time`, animated via `LaunchedEffect`):

```kotlin
@Composable
fun RippleSurface(content: @Composable BoxScope.() -> Unit) {
    if (Build.VERSION.SDK_INT < 33) { Box { content() }; return }
    val shader = remember { RuntimeShader(RIPPLE_AGSL) }
    var origin by remember { mutableStateOf(Offset.Zero) }
    var startMs by remember { mutableStateOf<Long?>(null) }
    val time by produceState(0f, startMs) {
        if (startMs == null) { value = 0f; return@produceState }
        val begin = startMs!!
        while (true) {
            withFrameMillis { now ->
                value = (now - begin) / 1000f
            }
        }
    }
    Box(
        modifier = Modifier
            .onSizeChanged {
                shader.setFloatUniform("resolution", it.width.toFloat(), it.height.toFloat())
            }
            .pointerInput(Unit) {
                detectTapGestures { tap ->
                    origin = tap
                    startMs = System.currentTimeMillis()
                }
            }
            .graphicsLayer {
                shader.setFloatUniform("origin", origin.x, origin.y)
                shader.setFloatUniform("time", time)
                renderEffect = RenderEffect
                    .createRuntimeShaderEffect(shader, "image")
                    .asComposeRenderEffect()
            },
        content = content
    )
}
```

### Recipe: Holographic Gradient

```glsl
uniform float time;
uniform shader image;

half4 main(float2 fragCoord) {
    half4 color = image.eval(fragCoord);
    float n = fragCoord.x * 0.01 + fragCoord.y * 0.005 + time * 0.3;
    half3 rainbow = half3(
        sin(n * 2.0) * 0.5 + 0.5,
        sin(n * 2.0 + 2.094) * 0.5 + 0.5,
        sin(n * 2.0 + 4.188) * 0.5 + 0.5
    );
    half luma = dot(color.rgb, half3(0.299, 0.587, 0.114));
    return half4(mix(color.rgb, rainbow * luma * 2.0, 0.5), color.a);
}
```

Multiplies the underlying view's luminance by a phase-shifted RGB sine wave - shimmer over text or icons. `time` animates the wave drift.

### Recipe: Liquid Glass / Glassmorphism

Android lacks a native iOS-26-style `glassEffect`. Compose this with blur + chromatic aberration + soft edge tint:

```glsl
uniform float2 resolution;
uniform shader image;

half4 main(float2 fragCoord) {
    float2 uv = fragCoord / resolution;
    // Chromatic aberration: sample R, G, B at slightly different offsets
    float2 ca = (uv - 0.5) * 0.004;
    half r = image.eval(fragCoord + ca * resolution).r;
    half g = image.eval(fragCoord).g;
    half b = image.eval(fragCoord - ca * resolution).b;
    half4 base = half4(r, g, b, 1.0);
    // Soft edge tint: brighten near borders for that frosted look
    float edge = smoothstep(0.45, 0.5, max(abs(uv.x - 0.5), abs(uv.y - 0.5)));
    half3 tinted = base.rgb + half3(edge * 0.08);
    return half4(tinted, 0.85);
}
```

Pair with `Modifier.blur(20.dp, BlurredEdgeTreatment.Unbounded)` upstream for the actual blur (cheaper than computing it in AGSL).

### Performance Notes

- Each `RuntimeShader` is a render pass. Compounds at 60fps - benchmark via Macrobenchmark.
- `image.eval(coord)` samples the underlying view as a texture. Heavy if the view is complex (long lists, nested layouts). Cache static parts in a parent that doesn't recompose.
- On Android 12 and below: graceful fallback (static image, no shader). Never hard-crash.
- Prefer 1 well-crafted shader over chaining 4 shaders in series.

---

## Domain 3: Canvas / DrawScope

### Canvas API

```kotlin
Canvas(modifier = Modifier.size(200.dp)) {
    // 'this' is DrawScope - size, drawCircle, drawPath, drawRect...
    drawCircle(Color.Blue, radius = size.minDimension / 2)
    drawPath(myPath, color = Color.White, style = Stroke(width = 4.dp.toPx()))
}
```

| DrawScope method | Use |
|---|---|
| `drawCircle` | Filled or stroked circles |
| `drawRect` | Rectangles, optionally with gradient brush |
| `drawPath` | Arbitrary path with `Stroke` or `Fill` |
| `drawArc` | Slice of an oval - useful for progress arcs |
| `drawLine` | Straight segment between two `Offset` |
| `drawText` | Text via `TextMeasurer` (preferred) or `drawIntoCanvas { it.nativeCanvas.drawText(...) }` |
| `drawIntoCanvas { }` | Escape hatch - access raw `android.graphics.Canvas` |

### Recipe: Animated Sine Wave

```kotlin
@Composable
fun AnimatedWave() {
    val infinite = rememberInfiniteTransition(label = "wave")
    val phase by infinite.animateFloat(
        initialValue = 0f,
        targetValue = 2 * PI.toFloat(),
        animationSpec = infiniteRepeatable(
            animation = tween(3000, easing = LinearEasing)
        ),
        label = "phase"
    )
    Canvas(modifier = Modifier.fillMaxWidth().height(80.dp)) {
        val path = Path()
        var x = 0
        while (x <= size.width.toInt()) {
            val y = size.height / 2 + sin(x * 0.05f + phase) * 20f
            if (x == 0) path.moveTo(x.toFloat(), y) else path.lineTo(x.toFloat(), y)
            x += 2
        }
        drawPath(path, color = Color.Blue, style = Stroke(width = 2.dp.toPx()))
    }
}
```

### Recipe: Particle System (50 Particles)

```kotlin
data class Particle(var x: Float, var y: Float, var vx: Float, var vy: Float, var life: Float)

@Composable
fun ParticleField() {
    val particles = remember {
        mutableStateListOf<Particle>().apply {
            repeat(50) {
                add(Particle(
                    x = Random.nextFloat() * 1000f,
                    y = Random.nextFloat() * 1000f,
                    vx = (Random.nextFloat() - 0.5f) * 4f,
                    vy = (Random.nextFloat() - 0.5f) * 4f,
                    life = 1f
                ))
            }
        }
    }
    LaunchedEffect(Unit) {
        while (true) {
            withFrameMillis { /* tick */ }
            particles.forEachIndexed { i, p ->
                p.x += p.vx
                p.y += p.vy
                p.life -= 0.01f
                if (p.life <= 0f) {
                    p.x = Random.nextFloat() * 1000f
                    p.y = Random.nextFloat() * 1000f
                    p.life = 1f
                }
            }
        }
    }
    Canvas(modifier = Modifier.fillMaxSize()) {
        particles.forEach { p ->
            drawCircle(
                color = Color.White.copy(alpha = p.life),
                radius = 2.dp.toPx(),
                center = Offset(p.x, p.y)
            )
        }
    }
}
```

### Recipe: Generative Pattern (Flow Field)

Quick mention: noise-driven particle motion. See `references/canvas-generative.md` for the full deep-dive (Perlin noise, particle pools, advection loop).

### Performance Notes

- Canvas redraws on every state change of any state it reads. Wrap volatile state in `derivedStateOf` to gate redraws.
- `LaunchedEffect(Unit) { while(true) { withFrameMillis { ... } } }` is fine for 60fps. Avoid `delay(16)` - it drifts.
- Heavy generative work: precompute paths once in `remember`, only animate transforms via `translate { drawPath(...) }`.
- 200 simple draws per frame = OK on most devices. 2000+ starts to lag.

---

## Anti-Patterns

### 1. Expressive Everywhere

```kotlin
// BAD - every interaction overshoots, UI feels like a bouncy castle
MaterialTheme(motionScheme = MotionScheme.expressive()) {
    AppRoot()
}

// GOOD - Standard for chrome, scope Expressive to hero moments
MaterialTheme(motionScheme = MotionScheme.standard()) {
    NavigationScaffold {
        // Hero detail screen overrides locally
        MaterialTheme(motionScheme = MotionScheme.expressive()) {
            HeroDetail()
        }
    }
}
```

### 2. RuntimeShader Without API Gate

```kotlin
// BAD - crashes on Android 12 and below
val shader = remember { RuntimeShader(AGSL_SOURCE) }

// GOOD - gate on SDK level, provide fallback
if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
    ShaderEffect { content() }
} else {
    Box(modifier = Modifier.background(fallbackGradient)) { content() }
}
```

### 3. Canvas Reading State Directly Each Frame

```kotlin
// BAD - any state change in the parent triggers a recompose of the Canvas
Canvas(modifier = Modifier.fillMaxSize()) {
    drawCircle(color = if (viewModel.isActive) Color.Red else Color.Blue, radius = 50f)
}

// GOOD - hoist the reads, derive a stable value
val color by remember { derivedStateOf { if (viewModel.isActive) Color.Red else Color.Blue } }
Canvas(modifier = Modifier.fillMaxSize()) {
    drawCircle(color = color, radius = 50f)
}
```

### 4. Chaining 4 AGSL Shaders in Series

```kotlin
// BAD - 4 render passes per frame, GPU melts on mid-range devices
.graphicsLayer { renderEffect = blurEffect }
.graphicsLayer { renderEffect = chromaticEffect }
.graphicsLayer { renderEffect = noiseEffect }
.graphicsLayer { renderEffect = vignetteEffect }

// GOOD - one shader doing all the math in a single pass
.graphicsLayer { renderEffect = combinedGlassEffect }
```

### 5. Allocating in DrawScope

```kotlin
// BAD - new Path every frame, GC stutter
Canvas(modifier = Modifier.fillMaxSize()) {
    val path = Path()
    points.forEach { path.lineTo(it.x, it.y) }
    drawPath(path, color = Color.Black)
}

// GOOD - reuse a remembered Path, rewind each frame
val path = remember { Path() }
Canvas(modifier = Modifier.fillMaxSize()) {
    path.rewind()
    points.forEach { path.lineTo(it.x, it.y) }
    drawPath(path, color = Color.Black)
}
```

---

## Quick Reference: Loading Sub-resources

| Need | Load |
|---|---|
| AGSL recipes (7 working shaders with binding code) | `references/agsl-recipes.md` |
| M3 Expressive choreography deep-dive | `references/m3-expressive-deep.md` |
| Generative drawing patterns (flow fields, L-systems, particles) | `references/canvas-generative.md` |
| Base animations (animateAsState, AnimatedVisibility, Transition) | `../compose-motion/SKILL.md` |
| CMP patterns (shared UI iOS / Android / Desktop) | `../compose-multiplatform/SKILL.md` |

---

## Sources

- [drinkthestars/shady](https://github.com/drinkthestars/shady) - AGSL shaders rendered in Compose
- [Mortd3kay/liquid-glass-android](https://github.com/Mortd3kay/liquid-glass-android)
- [JumpingKeyCaps/DynamicVisualEffectsAGSL](https://github.com/JumpingKeyCaps/DynamicVisualEffectsAGSL)
- [Material 3 Expressive blog](https://m3.material.io/blog/m3-expressive-motion-theming)
- [Material Design 3 Motion specs](https://m3.material.io/styles/motion/overview/specs)
- [Android AGSL docs](https://developer.android.com/develop/ui/views/graphics/agsl/using-agsl)
- [androidx.graphics.shapes](https://developer.android.com/jetpack/androidx/releases/graphics-shapes) - shape morphing
