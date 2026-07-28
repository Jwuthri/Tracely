# AGSL Recipes

Production-ready AGSL shaders for Compose. Each recipe ships AGSL source, Compose binding, parameter explanation, and perf notes. All shaders gate on `Build.VERSION.SDK_INT >= 33`.

> AGSL syntax reminders: `uniform` for inputs (read-only per pixel), `half4 main(float2 fragCoord)` returns the pixel color, `image.eval(coord)` samples the underlying view as a texture. Use `half` for color math (faster than `float` on mobile GPUs), `float` for geometry.

---

## 1. Touch Ripple

A pond-style wave that emanates from a tap point, attenuating with distance and decaying over time.

```glsl
// ripple.agsl
uniform float2 resolution;
uniform float2 origin;
uniform float time;       // seconds since tap
uniform float duration;   // total ripple lifetime in seconds
uniform shader image;

half4 main(float2 fragCoord) {
    float2 toOrigin = fragCoord - origin;
    float dist = length(toOrigin);
    float t = clamp(time / duration, 0.0, 1.0);
    // Decay amplitude as time progresses
    float amplitude = (1.0 - t) * 0.06;
    float wave = sin(dist * 0.05 - time * 8.0) * amplitude;
    // Falloff: stronger near origin, weaker far away
    float falloff = 1.0 / max(dist * 0.01, 1.0);
    float2 dir = toOrigin / max(dist, 0.0001);
    float2 displaced = fragCoord + dir * wave * falloff * 50.0;
    return image.eval(displaced);
}
```

```kotlin
val shader = remember { RuntimeShader(RIPPLE_AGSL) }
shader.setFloatUniform("origin", tapX, tapY)
shader.setFloatUniform("time", elapsedSec)
shader.setFloatUniform("duration", 1.5f)
```

**Parameters:**
- `origin` (px): tap location in view-local coordinates.
- `time` (s): seconds since tap began. Drive via `withFrameMillis` and a stored start timestamp.
- `duration` (s): how long the ripple animates before fading. 1.0-2.0 typical.

**Perf:** Single render pass. The `sin` and `length` calls are cheap. Safe up to 1080p at 60fps on mid-range GPUs (Pixel 6, S22).

---

## 2. Holographic Gradient

Animated rainbow shimmer modulated by the underlying view's luminance. Looks like an iridescent foil.

```glsl
// holographic.agsl
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
    half3 mixed = mix(color.rgb, rainbow * luma * 2.0, 0.5);
    return half4(mixed, color.a);
}
```

```kotlin
val shader = remember { RuntimeShader(HOLOGRAPHIC_AGSL) }
val time by produceState(0f) {
    while (true) withFrameMillis { value = it / 1000f }
}
shader.setFloatUniform("time", time)
```

**Parameters:**
- `time` (s): drives the rainbow drift. Wraps naturally via `sin`, no need to reset.

**Perf:** Cheapest of the seven. No texture sampling beyond the base. Works fine at 60fps even on entry-level devices.

---

## 3. Glow Halo

Brightens pixels above a luminance threshold, simulating a bloom-style glow without the cost of a separable blur.

```glsl
// glow.agsl
uniform float threshold;  // 0..1, luminance cutoff
uniform float strength;   // multiplier for the glow boost
uniform shader image;

half4 main(float2 fragCoord) {
    half4 color = image.eval(fragCoord);
    half luma = dot(color.rgb, half3(0.299, 0.587, 0.114));
    half excess = max(luma - threshold, 0.0);
    half3 boosted = color.rgb + color.rgb * excess * strength;
    return half4(boosted, color.a);
}
```

```kotlin
shader.setFloatUniform("threshold", 0.7f)
shader.setFloatUniform("strength", 2.5f)
```

**Parameters:**
- `threshold` (0..1): only pixels brighter than this glow. 0.7 = highlights only.
- `strength` (>= 0): how much to boost. 2.0-3.0 = subtle; 5.0+ = blown-out.

**Perf:** No multi-tap sampling, single pass. Fastest "glow" effect available without a true bloom pipeline.

---

## 4. Distortion / Heat Haze

Noise-driven displacement, like air shimmering above hot asphalt.

```glsl
// haze.agsl
uniform float2 resolution;
uniform float time;
uniform float intensity;  // displacement amount in px
uniform shader image;

float hash(float2 p) {
    return fract(sin(dot(p, float2(127.1, 311.7))) * 43758.5453);
}

float noise(float2 p) {
    float2 i = floor(p);
    float2 f = fract(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    return mix(
        mix(hash(i), hash(i + float2(1.0, 0.0)), u.x),
        mix(hash(i + float2(0.0, 1.0)), hash(i + float2(1.0, 1.0)), u.x),
        u.y
    );
}

half4 main(float2 fragCoord) {
    float2 uv = fragCoord / resolution;
    float dx = noise(float2(uv.x * 8.0, uv.y * 8.0 + time * 0.6)) - 0.5;
    float dy = noise(float2(uv.x * 8.0 + 100.0, uv.y * 8.0 + time * 0.6)) - 0.5;
    float2 displaced = fragCoord + float2(dx, dy) * intensity;
    return image.eval(displaced);
}
```

```kotlin
shader.setFloatUniform("resolution", w, h)
shader.setFloatUniform("time", time)
shader.setFloatUniform("intensity", 8f)
```

**Parameters:**
- `intensity` (px): max displacement. 4-12 = subtle haze; 30+ = strong distortion.
- `time` (s): scrolls the noise field.

**Perf:** Two `noise` calls per pixel. Costs more than recipes 1-3 but stays at 60fps on Pixel 6 and above for 1080p panels. For lower-end devices, sample noise at half-res via a precomputed texture.

---

## 5. Glassmorphism / Liquid Glass

Frosted glass effect: combine an upstream `Modifier.blur()` with chromatic aberration plus a soft edge tint. The blur happens before the shader; the shader adds the chromatic and edge details.

```glsl
// glass.agsl
uniform float2 resolution;
uniform float aberration;  // 0..0.01, color split amount
uniform float edgeWidth;   // 0..0.1, width of the frosted border
uniform shader image;

half4 main(float2 fragCoord) {
    float2 uv = fragCoord / resolution;
    // Chromatic aberration: split RGB along radial axis
    float2 ca = (uv - 0.5) * aberration;
    half r = image.eval(fragCoord + ca * resolution).r;
    half g = image.eval(fragCoord).g;
    half b = image.eval(fragCoord - ca * resolution).b;
    half4 base = half4(r, g, b, 1.0);
    // Edge tint: subtle brightening near borders
    float edgeDist = max(abs(uv.x - 0.5), abs(uv.y - 0.5));
    float edge = smoothstep(0.5 - edgeWidth, 0.5, edgeDist);
    half3 tinted = base.rgb + half3(edge * 0.08);
    return half4(tinted, 0.9);
}
```

```kotlin
Box(
    modifier = Modifier
        .blur(20.dp, BlurredEdgeTreatment.Unbounded)  // upstream blur
        .graphicsLayer {
            shader.setFloatUniform("resolution", size.width, size.height)
            shader.setFloatUniform("aberration", 0.004f)
            shader.setFloatUniform("edgeWidth", 0.05f)
            renderEffect = RenderEffect
                .createRuntimeShaderEffect(shader, "image")
                .asComposeRenderEffect()
        }
)
```

**Parameters:**
- `aberration` (0..0.01): how strongly RGB channels separate. 0.002-0.006 looks natural.
- `edgeWidth` (0..0.1): width of the brighter border. 0.03-0.08 typical.

**Perf:** 3 `image.eval` calls (R, G, B at different offsets). Pair with a real `Modifier.blur()` rather than computing blur in AGSL - the platform blur is hardware-accelerated and far cheaper.

---

## 6. Holographic Foil (Tilt Shimmer)

Anisotropic shimmer that responds to device tilt. Drive via accelerometer or touch position.

```glsl
// foil.agsl
uniform float2 resolution;
uniform float2 tilt;      // -1..1 on each axis
uniform shader image;

half4 main(float2 fragCoord) {
    float2 uv = fragCoord / resolution;
    half4 color = image.eval(fragCoord);
    // Anisotropic stripe pattern aligned with tilt direction
    float n = dot(uv - 0.5, tilt) * 20.0;
    half3 rainbow = half3(
        sin(n) * 0.5 + 0.5,
        sin(n + 2.094) * 0.5 + 0.5,
        sin(n + 4.188) * 0.5 + 0.5
    );
    half luma = dot(color.rgb, half3(0.299, 0.587, 0.114));
    // Stronger shimmer at high luma; tilt magnitude controls intensity
    float intensity = length(tilt) * luma;
    half3 mixed = mix(color.rgb, rainbow, intensity * 0.6);
    return half4(mixed, color.a);
}
```

```kotlin
// Read accelerometer or expose via pointer drag
val tilt by sensorTiltState()  // returns Offset in -1..1
shader.setFloatUniform("tilt", tilt.x, tilt.y)
```

**Parameters:**
- `tilt` (-1..1, -1..1): tilt vector. From accelerometer, gyro, or pointer drag (normalize by view size).

**Perf:** Same cost as the holographic recipe. The cost of reading the sensor dwarfs the shader.

---

## 7. Noise Overlay / Film Grain

3D pseudo-noise (the third dimension is time) overlaid on the underlying view. Adds organic texture, hides banding, useful for night-mode UI.

```glsl
// grain.agsl
uniform float2 resolution;
uniform float time;
uniform float intensity;  // 0..0.3
uniform shader image;

float hash3(float3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}

half4 main(float2 fragCoord) {
    half4 color = image.eval(fragCoord);
    float grain = hash3(float3(fragCoord, time)) - 0.5;
    return half4(color.rgb + half3(grain * intensity), color.a);
}
```

```kotlin
shader.setFloatUniform("resolution", w, h)
shader.setFloatUniform("time", time)
shader.setFloatUniform("intensity", 0.08f)
```

**Parameters:**
- `intensity` (0..0.3): grain visibility. 0.04-0.1 = subtle film grain; 0.2+ = aggressive noise.
- `time` (s): cycles the grain. Even slow `time` (e.g. /4) avoids static-noise jitter.

**Perf:** Cheapest of all - 1 hash, 1 mix. Run on top of any other effect for free.

---

## Combining Shaders

Two strategies. Pick based on the constraint.

### Strategy A: Chain (separate render passes)

Use when each effect is logically independent and you want to toggle them at runtime.

```kotlin
Modifier
    .graphicsLayer { renderEffect = blurRenderEffect }
    .graphicsLayer { renderEffect = grainRenderEffect }
```

Cost: N render passes per frame. Each pass reads back the previous result as a texture. Adds up fast - keep to 2 passes max.

### Strategy B: Fold into one shader (single pass)

Use when the effects always ship together and perf matters. Inline all the math in one AGSL `main`.

```glsl
// glass + grain in one pass
uniform float2 resolution;
uniform float time;
uniform float aberration;
uniform float grainAmount;
uniform shader image;

float hash3(float3 p) { /* ... */ }

half4 main(float2 fragCoord) {
    float2 uv = fragCoord / resolution;
    // Glass aberration
    float2 ca = (uv - 0.5) * aberration;
    half r = image.eval(fragCoord + ca * resolution).r;
    half g = image.eval(fragCoord).g;
    half b = image.eval(fragCoord - ca * resolution).b;
    half3 base = half3(r, g, b);
    // Grain
    float grain = hash3(float3(fragCoord, time)) - 0.5;
    return half4(base + half3(grain * grainAmount), 0.9);
}
```

Cost: 1 render pass, one set of `image.eval` calls. Almost always faster than chaining.

> **Rule of thumb:** if 2 effects are always on together, fold them. If they're toggled independently, chain.

---

## Sources

- [drinkthestars/shady](https://github.com/drinkthestars/shady) - reference AGSL patterns rendered in Compose
- [Mortd3kay/liquid-glass-android](https://github.com/Mortd3kay/liquid-glass-android)
- [JumpingKeyCaps/DynamicVisualEffectsAGSL](https://github.com/JumpingKeyCaps/DynamicVisualEffectsAGSL)
- [Android AGSL docs](https://developer.android.com/develop/ui/views/graphics/agsl/using-agsl)
- [Shadertoy](https://www.shadertoy.com/) - GLSL reference (port to AGSL with minor syntactic changes: `vec*` -> `float*` / `half*`, `texture()` -> `image.eval()`, no `gl_FragCoord` - use the `fragCoord` parameter of `main`)
