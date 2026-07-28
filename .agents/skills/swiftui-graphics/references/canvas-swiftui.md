# Canvas (SwiftUI Native Drawing)

> Vector drawing without leaving SwiftUI. Paths, gradients, text, blend modes.
> Concise patterns for `Canvas` + `TimelineView`. iOS 15+.

---

## `Canvas` API Basics

```swift
Canvas { context, size in
    // draw using context, bounded by size
}
```

The `context` is a `GraphicsContext`. The `size` is a `CGSize`.

**Key methods:**

| Method | Purpose |
|---|---|
| `context.fill(_ path: Path, with: GraphicsContext.Shading)` | Fill a path with color, gradient, image |
| `context.stroke(_ path: Path, with: ..., lineWidth:)` | Stroke a path |
| `context.draw(_ image: GraphicsContext.ResolvedImage, in: CGRect)` | Draw a resolved image |
| `context.draw(_ text: Text, at: CGPoint)` | Draw resolved text |
| `context.addFilter(_: GraphicsContext.Filter)` | Apply blur, shadow, color matrix |
| `context.transform = CGAffineTransform` | Cumulative transform |
| `context.clip(to: Path)` | Clip subsequent draws |
| `context.opacity = Double` | Set opacity for subsequent draws |
| `context.blendMode = GraphicsContext.BlendMode` | Set blend mode |

**Path construction:**
```swift
// Built-in shapes
Path(ellipseIn: rect)
Path(roundedRect: rect, cornerRadius: 12)
Path(CGRect(...))

// Manual construction
var path = Path()
path.move(to: CGPoint(x: 0, y: 0))
path.addLine(to: CGPoint(x: 100, y: 100))
path.addQuadCurve(to: end, control: ctrl)
path.addArc(center: c, radius: r, startAngle: .zero, endAngle: .pi, clockwise: false)
path.closeSubpath()
```

**Symbol drawing** (resolve a SwiftUI view inside Canvas):
```swift
Canvas { context, size in
    if let star = context.resolveSymbol(id: "star") {
        context.draw(star, at: CGPoint(x: 50, y: 50))
    }
} symbols: {
    Image(systemName: "star.fill").tag("star").foregroundStyle(.yellow)
}
```

---

## Animating with TimelineView

`Canvas` does not animate by itself. Wrap in `TimelineView(.animation)` so the closure re-runs at the screen refresh rate.

```swift
TimelineView(.animation) { timeline in
    Canvas { context, size in
        let t = timeline.date.timeIntervalSinceReferenceDate
        // draw using t as time
    }
}
```

**Schedules:**

| Schedule | Use |
|---|---|
| `.animation` | Frame rate (60-120 Hz), best for visual animation |
| `.animation(minimumInterval: 0.1)` | 10 fps cap, save power for slow effects |
| `.periodic(from:by:)` | Fixed interval (clocks, counters) |
| `.explicit([dates])` | Manual schedule |

---

## Recipes

### Sparkle Field

30 random sparkles fading in/out with stable per-sparkle phase.

```swift
struct Sparkle: Identifiable {
    let id = UUID()
    let position: CGPoint
    let size: Double
    let phase: Double
}

struct SparkleField: View {
    let sparkles: [Sparkle] = (0..<30).map { _ in
        Sparkle(
            position: CGPoint(x: .random(in: 0...300), y: .random(in: 0...600)),
            size: .random(in: 2...5),
            phase: .random(in: 0...(2 * .pi))
        )
    }

    var body: some View {
        TimelineView(.animation) { timeline in
            Canvas { context, size in
                let t = timeline.date.timeIntervalSinceReferenceDate
                for s in sparkles {
                    let alpha = (sin(t * 2 + s.phase) + 1) / 2 * 0.8 + 0.2
                    context.fill(
                        Path(ellipseIn: CGRect(
                            x: s.position.x, y: s.position.y,
                            width: s.size, height: s.size
                        )),
                        with: .color(.white.opacity(alpha))
                    )
                }
            }
        }
        .frame(width: 300, height: 600)
    }
}
```

### Animated Sine Wave

```swift
TimelineView(.animation) { timeline in
    Canvas { context, size in
        let t = timeline.date.timeIntervalSinceReferenceDate
        var path = Path()
        path.move(to: CGPoint(x: 0, y: size.height / 2))
        for x in stride(from: 0, through: size.width, by: 2) {
            let y = size.height / 2 + sin(x * 0.02 + t * 2) * 30
            path.addLine(to: CGPoint(x: x, y: y))
        }
        context.stroke(path, with: .color(.cyan), lineWidth: 2)
    }
}
```

### Particle Trail (cursor-following)

```swift
struct ParticleTrail: View {
    @State var trail: [CGPoint] = []

    var body: some View {
        Canvas { context, size in
            for (i, point) in trail.enumerated() {
                let alpha = Double(i) / Double(max(trail.count, 1))
                let radius = 2 + alpha * 8
                context.fill(
                    Path(ellipseIn: CGRect(
                        x: point.x - radius / 2, y: point.y - radius / 2,
                        width: radius, height: radius
                    )),
                    with: .color(.purple.opacity(alpha))
                )
            }
        }
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { value in
                    trail.append(value.location)
                    if trail.count > 30 { trail.removeFirst() }
                }
        )
    }
}
```

### Gradient Mesh (moving anchors)

Radial gradients at moving anchor points, blended with `.plusLighter`.

```swift
TimelineView(.animation) { timeline in
    Canvas { context, size in
        context.blendMode = .plusLighter
        let t = timeline.date.timeIntervalSinceReferenceDate
        let anchors = [
            CGPoint(x: size.width * 0.3 + sin(t) * 50, y: size.height * 0.3 + cos(t) * 50),
            CGPoint(x: size.width * 0.7 + cos(t * 0.7) * 50, y: size.height * 0.7 + sin(t * 0.7) * 50),
        ]
        let colors: [Color] = [.purple, .cyan]
        for (anchor, color) in zip(anchors, colors) {
            let gradient = Gradient(colors: [color.opacity(0.6), color.opacity(0)])
            context.fill(
                Path(CGRect(origin: .zero, size: size)),
                with: .radialGradient(
                    gradient,
                    center: anchor,
                    startRadius: 0,
                    endRadius: 200
                )
            )
        }
    }
}
```

---

## Performance

- **Canvas redraws on ancestor state changes.** Wrap with `EquatableView` or `.drawingGroup()` to control scope.
- **Heavy draws: precompute paths once** using `let path = Path { ... }` outside the closure or in `@State`.
- **Don't draw thousands of items.** For pixel-grain effects (smoke, fire, dense particles), `.layerEffect` with a Metal shader scales better.
- **`drawingGroup()`** turns Canvas into a single Metal-backed layer. Useful when nested in heavy hierarchies, but disables hit-testing on the contents.
- **Symbol resolve cost.** `context.resolveSymbol` is cheap once but called every frame. Cache outside if symbols never change.

---

## Canvas vs Metal Shader

| Need | Tool |
|---|---|
| Vector drawing (paths, shapes) | Canvas |
| Text rendering | Canvas (via `Text`) |
| Hundreds of distinct shapes with simple animation | Canvas |
| Pixel-level color manipulation | Metal shader (`.colorEffect`) |
| Pixel displacement, ripples, distortion | Metal shader (`.distortionEffect`/`.layerEffect`) |
| Thousands of particles, smoke, fluids | Metal shader or SpriteKit |
| Static / one-shot drawing | Canvas (no TimelineView) |

> **Rule:** if you can describe the effect in vectors, use Canvas. If it's per-pixel, use Metal.

---

## Sources

- [Apple Canvas documentation](https://developer.apple.com/documentation/swiftui/canvas)
- [Apple TimelineView documentation](https://developer.apple.com/documentation/swiftui/timelineview)
- [Apple GraphicsContext](https://developer.apple.com/documentation/swiftui/graphicscontext)
