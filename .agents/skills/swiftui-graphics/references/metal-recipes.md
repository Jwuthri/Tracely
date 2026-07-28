# Metal Shader Recipes

> Working Metal Shading Language (MSL) shaders for SwiftUI's `.colorEffect`, `.distortionEffect`, `.layerEffect`. iOS 17+.
> Each recipe: description, .metal code, Swift binding, parameters, performance note.

All `.metal` files start with:
```metal
#include <SwiftUI/SwiftUI_Metal.h>
using namespace metal;
```
(Omitted from each recipe below for brevity. Add it once per file.)

---

## 1. Ripple Touch

Touch ripple displacing pixels along a sine wave with time decay. The ripple fades as `time` grows.

```metal
[[ stitchable ]]
half4 ripple(float2 position, SwiftUI::Layer layer,
             float2 origin, float time, float amp) {
    float distance = length(position - origin);
    // wavefront expands with time, decays with distance
    float wavefront = distance - time * 200.0;
    float wave = sin(wavefront * 0.05) * amp;
    // decay: ripple weakens past the wavefront and over time
    float decay = exp(-time * 1.5) * exp(-abs(wavefront) * 0.005);
    wave *= decay;
    float2 dir = normalize(position - origin);
    float2 displaced = position + dir * wave * clamp(50.0 / max(distance, 1.0), 0.0, 50.0);
    return layer.sample(displaced);
}
```

```swift
struct RippleView: View {
    @State var origin: CGPoint = .zero
    @State var time: Float = 0

    var body: some View {
        Image("photo")
            .resizable()
            .scaledToFit()
            .layerEffect(
                ShaderLibrary.ripple(
                    .float2(Float(origin.x), Float(origin.y)),
                    .float(time),
                    .float(0.05)
                ),
                maxSampleOffset: CGSize(width: 50, height: 50)
            )
            .onTapGesture { location in
                origin = location
                time = 0
                withAnimation(.linear(duration: 1.5)) { time = 1.5 }
            }
    }
}
```

**Params:**
- `origin` (float2): touch point in view space.
- `time` (float): seconds since tap, drives wavefront expansion.
- `amp` (float): ripple amplitude. 0.05 is subtle; 0.2 cartoonish.

**Perf:** `.layerEffect` is the most expensive of the three. `clamp` on the displacement protects against runaway sampling. Keep `maxSampleOffset` tight.

---

## 2. Holographic Gradient

Rainbow shimmer over luminance, scrollable via a parameter. Useful for foil cards and trading-card effects.

```metal
[[ stitchable ]]
half4 holographic(float2 position, half4 color, float scroll) {
    float n = position.x * 0.01 + position.y * 0.005 + scroll * 0.3;
    half3 rainbow = half3(
        sin(n * 2.0) * 0.5 + 0.5,
        sin(n * 2.0 + 2.094) * 0.5 + 0.5,
        sin(n * 2.0 + 4.188) * 0.5 + 0.5
    );
    half luminance = dot(color.rgb, half3(0.299, 0.587, 0.114));
    return half4(mix(color.rgb, rainbow * luminance * 2.0, 0.5), color.a);
}
```

```swift
struct HolographicCard: View {
    @State var scroll: Float = 0

    var body: some View {
        Image("card")
            .resizable()
            .scaledToFit()
            .colorEffect(ShaderLibrary.holographic(.float(scroll)))
            .gesture(
                DragGesture()
                    .onChanged { scroll = Float($0.translation.width / 200) }
            )
    }
}
```

**Params:**
- `scroll` (float): drives the rainbow phase. Bind to scroll offset, time, or drag delta.

**Perf:** cheap. `.colorEffect` runs purely per-pixel with no neighbor access. Safe to apply on full-screen views.

---

## 3. CRT Scanlines + Chromatic Aberration

True chromatic aberration via offset RGB samples. Promote to `.layerEffect`.

```metal
[[ stitchable ]]
half4 crt(float2 position, SwiftUI::Layer layer, float time) {
    float scanline = sin(position.y * 1.5) * 0.04;
    float flicker = sin(time * 60.0) * 0.02;

    // sample R and B with horizontal offset for chromatic aberration
    float aberration = 1.5;
    half r = layer.sample(position + float2(aberration, 0)).r;
    half g = layer.sample(position).g;
    half b = layer.sample(position - float2(aberration, 0)).b;
    half a = layer.sample(position).a;

    half3 rgb = half3(r, g, b) * (1.0 - scanline - flicker);
    return half4(rgb, a);
}
```

```swift
struct CRTView<Content: View>: View {
    let content: Content
    let startTime = Date()
    init(@ViewBuilder content: () -> Content) { self.content = content() }

    var body: some View {
        TimelineView(.animation) { timeline in
            let t = Float(timeline.date.timeIntervalSince(startTime))
            content.layerEffect(
                ShaderLibrary.crt(.float(t)),
                maxSampleOffset: CGSize(width: 2, height: 0)
            )
        }
    }
}
```

**Params:**
- `time` (float): seconds elapsed, drives flicker.

**Perf:** four `layer.sample` calls per pixel. Keep aberration small (`maxSampleOffset` of 2px is enough). At full screen on iPhone 12 and below, expect dropped frames if combined with other effects.

---

## 4. Glow Halo

Brightens pixels above a luminance threshold. Cheaper than bloom, ships in one pass.

```metal
[[ stitchable ]]
half4 glow(float2 position, half4 color, float threshold, float strength) {
    half luminance = dot(color.rgb, half3(0.299, 0.587, 0.114));
    half mask = smoothstep(threshold, threshold + 0.1, luminance);
    half3 boosted = color.rgb + color.rgb * mask * strength;
    return half4(boosted, color.a);
}
```

```swift
Text("HELLO")
    .font(.system(size: 80, weight: .black))
    .foregroundStyle(.white)
    .colorEffect(
        ShaderLibrary.glow(.float(0.7), .float(2.0))
    )
```

**Params:**
- `threshold` (float): luminance above which pixels glow. 0.7 = highlights only.
- `strength` (float): multiplier. 2.0 doubles bright pixels.

**Perf:** very cheap. Pair with a Gaussian blur underneath for a true bloom look (use SwiftUI's `.blur(radius:)` on a duplicate layer).

---

## 5. Distortion / Heat Haze

Wavering distortion driven by pseudo-noise. Use case: heat above a fire, water reflections.

```metal
// hash-based pseudo-noise, fast and shader-friendly
float hash(float2 p) {
    return fract(sin(dot(p, float2(127.1, 311.7))) * 43758.5453);
}

float noise(float2 p) {
    float2 i = floor(p);
    float2 f = fract(p);
    float a = hash(i);
    float b = hash(i + float2(1.0, 0.0));
    float c = hash(i + float2(0.0, 1.0));
    float d = hash(i + float2(1.0, 1.0));
    float2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

[[ stitchable ]]
float2 heatHaze(float2 position, float time, float strength) {
    float n = noise(position * 0.02 + float2(0, time * 2.0));
    float2 offset = float2(
        (n - 0.5) * strength,
        (noise(position * 0.02 + float2(time, 0)) - 0.5) * strength
    );
    return position + offset;
}
```

```swift
TimelineView(.animation) { timeline in
    let t = Float(timeline.date.timeIntervalSinceReferenceDate)
    Image("flame")
        .resizable()
        .scaledToFit()
        .distortionEffect(
            ShaderLibrary.heatHaze(.float(t), .float(8.0)),
            maxSampleOffset: CGSize(width: 8, height: 8)
        )
}
```

**Params:**
- `time` (float): seconds elapsed, scrolls the noise field.
- `strength` (float): max pixel displacement. 8 px = visible but plausible.

**Perf:** `.distortionEffect` is per-pixel sampling -- medium cost. The noise function is the hot path; if too slow on older devices, sample a noise texture instead.

---

## 6. Particle Emitter (Canvas + TimelineView)

50 additive particles drifting upward. Pure SwiftUI, no Metal.

```swift
struct Particle: Identifiable {
    let id = UUID()
    var position: CGPoint
    var velocity: CGVector
    var life: Double
    var size: Double
}

struct ParticleEmitter: View {
    @State var particles: [Particle] = (0..<50).map { _ in
        Particle(
            position: CGPoint(x: .random(in: 0...300), y: 600),
            velocity: CGVector(dx: .random(in: -20...20), dy: .random(in: -100 ... -50)),
            life: .random(in: 0...3),
            size: .random(in: 2...6)
        )
    }

    var body: some View {
        TimelineView(.animation) { timeline in
            Canvas { context, size in
                context.blendMode = .plusLighter
                let t = timeline.date.timeIntervalSinceReferenceDate
                for p in particles {
                    let life = (p.life + t).truncatingRemainder(dividingBy: 3)
                    let progress = life / 3
                    let y = p.position.y + p.velocity.dy * life
                    let x = p.position.x + p.velocity.dx * life
                    let alpha = (1.0 - progress) * 0.8
                    context.fill(
                        Path(ellipseIn: CGRect(x: x, y: y, width: p.size, height: p.size)),
                        with: .color(.orange.opacity(alpha))
                    )
                }
            }
        }
        .frame(width: 300, height: 600)
    }
}
```

**Params:** all configured in particle struct (position, velocity, life, size).

**Perf:** Canvas with 50 fills at 60fps is fine on iPhone 11+. For 500+ particles or per-pixel glow, switch to a Metal `.colorEffect` on a CALayer-backed view or use SpriteKit/Metal directly.

---

## 7. Noise Overlay (Film Grain)

3D pseudo-noise approximation for animated film grain.

```metal
float hash3(float3 p) {
    return fract(sin(dot(p, float3(127.1, 311.7, 74.7))) * 43758.5453);
}

[[ stitchable ]]
half4 grain(float2 position, half4 color, float time, float strength) {
    float n = hash3(float3(position * 0.5, time * 10.0));
    half g = half(n - 0.5) * half(strength);
    return half4(color.rgb + g, color.a);
}
```

```swift
TimelineView(.animation) { timeline in
    let t = Float(timeline.date.timeIntervalSinceReferenceDate)
    Image("photo")
        .resizable()
        .scaledToFit()
        .colorEffect(ShaderLibrary.grain(.float(t), .float(0.15)))
}
```

**Params:**
- `time` (float): drives grain animation. Pass elapsed seconds.
- `strength` (float): grain amplitude. 0.05 subtle, 0.2 strong, 0.4 destructive.

**Perf:** very cheap. The hash is one `sin` and a `fract`. Safe on full-screen views at 60fps.

---

## Combining Recipes

Two strategies, in order of preference:

### A. Single shader with multiple ops (best perf)

Combine into one `[[ stitchable ]]` function. One render pass.

```metal
[[ stitchable ]]
half4 holoGrain(float2 position, half4 color, float time, float scroll) {
    // holographic
    float n = position.x * 0.01 + position.y * 0.005 + scroll * 0.3;
    half3 rainbow = half3(
        sin(n * 2.0) * 0.5 + 0.5,
        sin(n * 2.0 + 2.094) * 0.5 + 0.5,
        sin(n * 2.0 + 4.188) * 0.5 + 0.5
    );
    half lum = dot(color.rgb, half3(0.299, 0.587, 0.114));
    half3 holo = mix(color.rgb, rainbow * lum * 2.0, 0.5);

    // grain
    float g = fract(sin(dot(float3(position * 0.5, time * 10.0), float3(127.1, 311.7, 74.7))) * 43758.5453);
    half3 final = holo + half(g - 0.5) * 0.1;

    return half4(final, color.a);
}
```

### B. Stacked modifiers (use only when ops are conditional)

Each modifier is one render pass. Acceptable for 2 ops. Don't go past 3.

```swift
Image("card")
    .colorEffect(ShaderLibrary.holographic(.float(scroll)))
    .colorEffect(ShaderLibrary.grain(.float(time), .float(0.1)))
```

> When in doubt: prototype with stacked modifiers, then collapse into one shader for ship.

---

## Sources

- [twostraws/Inferno](https://github.com/twostraws/Inferno) - reference Metal shaders for SwiftUI
- [Treata11/iShader](https://github.com/Treata11/iShader)
- [jamesrochabrun/ShaderKit](https://github.com/jamesrochabrun/ShaderKit)
- [raphaelsalaja/metallurgy](https://github.com/raphaelsalaja/metallurgy)
- [eleev/swiftui-new-metal-shaders](https://github.com/eleev/swiftui-new-metal-shaders)
- [Apple Metal Shading Language Spec](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf)
- [Apple Shader documentation](https://developer.apple.com/documentation/swiftui/shader)
