---
name: swiftui-graphics
description: "Advanced SwiftUI visuals - Metal shaders (.colorEffect, .layerEffect, .distortionEffect), .visualEffect, Liquid Glass (iOS 26), Canvas, holographic and CRT effects."
---

# SwiftUI Graphics

> Advanced SwiftUI visuals: Metal shaders, visual effects, Liquid Glass, Canvas.
> Loaded for advanced thesis (shaders, holographic, liquid-glass, distortion).
> Foundation: `../swiftui-motion/SKILL.md` covers the basics.
> Concise rules here. Deep-dives in `references/`.

---

## Decision Tree: Which API?

| Need | API |
|---|---|
| Pixel-level color manipulation | `.colorEffect(ShaderLibrary....)` |
| Pixel position / distortion | `.distortionEffect(ShaderLibrary....)` |
| Full layer with overlay (mix shader + bg) | `.layerEffect(ShaderLibrary....)` |
| View modifier with geometry context | `.visualEffect { content, geometry in }` |
| Custom drawing (paths, gradients) | `Canvas { context, size in }` |
| iOS 26+ glassmorphism | `.glassEffect()` / `GlassEffectContainer` |
| Performance dump | `Canvas` with `.opaque(true)` then export |

> **Default order of escalation:** built-in modifiers -> `.visualEffect` -> `Canvas` -> Metal shader. Reach for shaders only when the effect is per-pixel and animated.

---

## Metal Shaders Intro

SwiftUI binds to Metal Shading Language (MSL) via three modifiers shipped in iOS 17: `.colorEffect`, `.distortionEffect`, `.layerEffect`. You author a `.metal` file in your app target, mark functions with the `[[ stitchable ]]` attribute, and SwiftUI auto-generates the Swift binding via `ShaderLibrary.<functionName>(...)`. One library per app target. Shaders run on the GPU at native resolution; arguments are passed as `.float`, `.float2`, `.color`, `.image` from Swift. iOS 17+ only; for older targets, fall back to gradients, blur, or `Canvas`.

The three slots differ by what data they receive:
- `.colorEffect`: gets `(position, color)`, returns transformed color. No neighbor sampling.
- `.distortionEffect`: gets `(position)`, returns a new sample position. Pixels move, colors do not change.
- `.layerEffect`: gets `(position, SwiftUI::Layer layer)`, returns final color. Can sample anywhere within `maxSampleOffset`. Most expensive.

---

## Recipe: Ripple `.layerEffect`

Touch ripple that displaces nearby pixels along a sine wave.

```swift
struct RippleView: View {
    @State var rippleOrigin: CGPoint = .zero
    @State var rippleTime: Float = 0

    var body: some View {
        Image("photo")
            .resizable()
            .scaledToFit()
            .layerEffect(
                ShaderLibrary.ripple(
                    .float2(Float(rippleOrigin.x), Float(rippleOrigin.y)),
                    .float(rippleTime),
                    .float(0.05) // amplitude
                ),
                maxSampleOffset: CGSize(width: 50, height: 50)
            )
            .onTapGesture { location in
                rippleOrigin = location
                rippleTime = 0
                withAnimation(.linear(duration: 1.2)) {
                    rippleTime = 1.2
                }
            }
    }
}
```

```metal
// Ripple.metal
#include <SwiftUI/SwiftUI_Metal.h>
using namespace metal;

[[ stitchable ]]
half4 ripple(float2 position, SwiftUI::Layer layer,
             float2 origin, float time, float amp) {
    float distance = length(position - origin);
    float wave = sin(distance * 0.05 - time * 8.0) * amp;
    float2 dir = normalize(position - origin);
    float falloff = 1.0 / max(distance, 1.0);
    float2 displaced = position + dir * wave * falloff * 50.0;
    return layer.sample(displaced);
}
```

**Why this works:**
- `[[ stitchable ]]` exposes the function to SwiftUI's runtime.
- The first two args (`position`, `SwiftUI::Layer layer`) are injected by SwiftUI for any `.layerEffect`. Your Swift-side args start at index 2.
- `maxSampleOffset` tells SwiftUI how far you may sample beyond the view bounds. Underestimate and you get clipping. Overestimate and you waste GPU.

---

## Recipe: Holographic `.colorEffect`

Oil-slick rainbow shimmer driven by time or scroll offset. Preserves luminance so dark regions stay dark.

```metal
// Holographic.metal
#include <SwiftUI/SwiftUI_Metal.h>
using namespace metal;

[[ stitchable ]]
half4 holographic(float2 position, half4 color, float time) {
    float n = position.x * 0.01 + position.y * 0.005 + time * 0.3;
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
    let startTime = Date()

    var body: some View {
        TimelineView(.animation) { timeline in
            let elapsed = Float(timeline.date.timeIntervalSince(startTime))
            Image("card")
                .resizable()
                .scaledToFit()
                .colorEffect(
                    ShaderLibrary.holographic(.float(elapsed))
                )
        }
    }
}
```

> The 2.094 and 4.188 offsets are 2pi/3 and 4pi/3 -- they spread the three sine waves to RGB phases. Keep them.

---

## Recipe: CRT Scanlines

Vintage CRT effect: scanlines, flicker, subtle chromatic aberration.

```metal
// CRT.metal
#include <SwiftUI/SwiftUI_Metal.h>
using namespace metal;

[[ stitchable ]]
half4 crt(float2 position, half4 color, float time) {
    float scanline = sin(position.y * 1.5) * 0.04;
    float flicker = sin(time * 60.0) * 0.02;
    half3 result = color.rgb * (1.0 - scanline - flicker);
    // chromatic aberration on R/B channels
    return half4(result.r * 1.05, result.g, result.b * 1.05, color.a);
}
```

```swift
.colorEffect(ShaderLibrary.crt(.float(elapsed)))
```

> For real chromatic aberration (shifted R/B sample positions), promote to `.layerEffect`. The version above only tints, which reads as CRT at small scale.

---

## `.visualEffect` (iOS 17+)

Modifier that exposes the view's `GeometryProxy` so you can react to its frame in any coordinate space without `GeometryReader` boilerplate.

```swift
ScrollView {
    LazyVStack(spacing: 16) {
        ForEach(items) { item in
            CardView(item: item)
                .visualEffect { content, proxy in
                    let y = proxy.frame(in: .scrollView).minY
                    let scale = scale(for: y)
                    let opacity = opacity(for: y)
                    return content
                        .scaleEffect(scale)
                        .opacity(opacity)
                }
        }
    }
}

func scale(for y: CGFloat) -> CGFloat {
    let progress = max(0, min(1, y / 600))
    return 0.85 + progress * 0.15
}
```

**Use cases:**
- Parallax cards (move slower than scroll)
- Scroll-driven scale (cards grow as they enter view)
- Sticky reveal (clamp position via `.offset(y: max(0, -y))`)

> `.visualEffect` is purely visual: the geometry it returns is read-only and the modifier cannot trigger state updates. Don't try to write to `@State` from inside.

---

## Liquid Glass (iOS 26)

System glassmorphism with adaptive depth and morphing transitions. Built into the OS, optimized at the system level.

```swift
@Namespace var glassNS

struct HeroCard: View {
    var body: some View {
        if #available(iOS 26.0, *) {
            Image("hero")
                .resizable()
                .scaledToFit()
                .glassEffect(.regular)
                .glassEffectID("hero", in: glassNS)
        } else {
            Image("hero")
                .resizable()
                .scaledToFit()
                .background(.ultraThinMaterial)
        }
    }
}
```

For grouped surfaces that should morph as one (e.g., a tab bar that splits into separate pills on hover), wrap them in a container:

```swift
GlassEffectContainer(spacing: 12) {
    ForEach(tabs) { tab in
        TabIcon(tab: tab)
            .glassEffect(.regular)
            .glassEffectID(tab.id, in: glassNS)
    }
}
```

> Pre-iOS 26: use `.background(.ultraThinMaterial)` for static glass. For morphing transitions, fall back to `matchedGeometryEffect` on a material-backed view (see `swiftui-motion`).

Deep-dive: `references/liquid-glass-deep.md`.

---

## Canvas (SwiftUI Native Drawing)

Vector drawing API. Paths, gradients, text, blend modes -- without leaving SwiftUI.

```swift
struct SparkleField: View {
    var body: some View {
        Canvas { context, size in
            for _ in 0..<20 {
                let x = Double.random(in: 0...size.width)
                let y = Double.random(in: 0...size.height)
                let radius = Double.random(in: 1...4)
                context.fill(
                    Path(ellipseIn: CGRect(x: x, y: y, width: radius, height: radius)),
                    with: .color(.white.opacity(.random(in: 0.3...1.0)))
                )
            }
        }
    }
}
```

To animate, wrap in `TimelineView(.animation)` so the closure re-runs at frame rate:

```swift
TimelineView(.animation) { timeline in
    Canvas { context, size in
        let t = timeline.date.timeIntervalSinceReferenceDate
        // draw using t as time
    }
}
```

> `TimelineView(.animation)` redraws at the screen refresh rate. Use `.animation(minimumInterval: 0.1)` for slower animations to save power.

Deep-dive: `references/canvas-swiftui.md`.

---

## Performance Considerations

| Effect | Cost | Notes |
|---|---|---|
| `.colorEffect` | low | Runs per pixel, simple math, no neighbor access |
| `.distortionEffect` | medium | Sampling cost, branch-free is critical |
| `.layerEffect` | high | Full layer access, can sample anywhere |
| `Canvas` with TimelineView | varies | Depends on draw count and complexity |
| `.glassEffect` | medium-high | GPU heavy, fine on modern devices |

**Rules:**
1. Avoid stacking >1 `.layerEffect` on the same view -- each is a full render pass.
2. Precompute static parts (gradients, paths) outside the animated subtree.
3. Profile with Instruments **GPU Frame Capture** and **Metal System Trace** before optimizing blindly.

---

## Anti-Patterns

### 1. Stacked `.colorEffect` modifiers

Each modifier is a separate render pass.

```swift
// BAD -- 5 GPU passes
Image(...)
    .colorEffect(ShaderLibrary.tint(...))
    .colorEffect(ShaderLibrary.scanlines(...))
    .colorEffect(ShaderLibrary.grain(...))
    .colorEffect(ShaderLibrary.vignette(...))
    .colorEffect(ShaderLibrary.chromatic(...))

// GOOD -- one shader does all the ops in one pass
Image(...)
    .colorEffect(ShaderLibrary.crtCombo(.float(time)))
```

### 2. Canvas redrawn on every state change

Canvas re-runs when any ancestor state changes. Without `TimelineView` or `EquatableView`, you redraw on input you never intended.

```swift
// BAD -- redraws on parent re-render
struct Parent: View {
    @State var unrelated = 0
    var body: some View {
        VStack {
            Button("tick") { unrelated += 1 }
            Canvas { context, size in expensiveDraw(context, size) }
        }
    }
}

// GOOD -- isolate via EquatableView or TimelineView
TimelineView(.animation) { _ in
    Canvas { context, size in expensiveDraw(context, size) }
}
```

### 3. Hardcoded color values inside shader

Forces a recompile to change color. Pass them through.

```metal
// BAD
half3 tint = half3(1.0, 0.4, 0.2);

// GOOD -- accept color from Swift
[[ stitchable ]]
half4 tinted(float2 pos, half4 color, half4 tint) {
    return half4(color.rgb * tint.rgb, color.a);
}
```

```swift
.colorEffect(ShaderLibrary.tinted(.color(themeAccent)))
```

### 4. `.glassEffect` everywhere

Liquid Glass is expensive and visually noisy when overused. Reserve for hero / chrome surfaces.

```swift
// BAD -- 30 glass cards in a list
LazyVStack {
    ForEach(items) { item in
        Card(item: item).glassEffect(.regular) // GPU melt
    }
}

// GOOD -- glass on the floating tab bar, opaque cards underneath
ZStack(alignment: .bottom) {
    ScrollView { LazyVStack { ForEach(items) { Card(item: $0) } } }
    TabBar().glassEffect(.regular)
}
```

---

## Quick Reference

| Need | Load |
|---|---|
| Metal recipes deep dive | `references/metal-recipes.md` |
| Liquid Glass patterns + iOS 26 specifics | `references/liquid-glass-deep.md` |
| Canvas drawing patterns | `references/canvas-swiftui.md` |
| Base animations | `../swiftui-motion/SKILL.md` |
| Foundation | `../motion-principles/SKILL.md` |
| Mobile UX (iOS) | `../mobile-principles/SKILL.md` |
| Desktop UX (macOS) | `../desktop-principles/SKILL.md` |

---

## Sources

- [twostraws/Inferno](https://github.com/twostraws/Inferno) - reference Metal shaders for SwiftUI
- [Treata11/iShader](https://github.com/Treata11/iShader)
- [jamesrochabrun/ShaderKit](https://github.com/jamesrochabrun/ShaderKit)
- [raphaelsalaja/metallurgy](https://github.com/raphaelsalaja/metallurgy)
- [eleev/swiftui-new-metal-shaders](https://github.com/eleev/swiftui-new-metal-shaders)
- [Apple Metal Shading Language Spec](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf)
- [Apple Shader documentation](https://developer.apple.com/documentation/swiftui/shader)
