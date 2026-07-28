# PhaseAnimator + KeyframeAnimator deep-dive

iOS 17+ shipped two complementary animation primitives: `PhaseAnimator` for ordered state choreography and `KeyframeAnimator` for time-based parallel tracks.
This file documents when to choose which, gotchas, and combined patterns.

---

## When to choose Phase vs Keyframe

| Need | Pick |
|---|---|
| 3+ ordered states with springy feel between each | `PhaseAnimator` |
| Same animation should re-fire on a value change | both, via `trigger:` |
| Multiple properties animating on independent timelines | `KeyframeAnimator` |
| Continuous time-based animation (durations matter precisely) | `KeyframeAnimator` |
| Loop forever on appear | `PhaseAnimator` (no `trigger:` + cycle phases) |
| One-shot effect on user action (heart pop, success check) | both work; Phase is shorter to write |
| Custom shape that animates a value | `Animatable` (not these) |

---

## PhaseAnimator deep-dive

### Anatomy

```swift
view.phaseAnimator(
    Phase.allCases,           // CaseIterable + Hashable
    trigger: someValue        // optional - re-runs from phase[0] on change
) { content, phase in
    content
        .modifier1(...)
        .modifier2(...)
} animation: { phase in
    // optional - per-phase animation override
    switch phase { ... }
}
```

Without `trigger:`, the animator walks through phases once on appear and stops on the last one. With `trigger:`, the animator re-runs from `phases[0]` every time the trigger value changes (it must be `Equatable`).

### Full example: success state with 4 phases

```swift
enum SuccessPhase: CaseIterable {
    case off, scaleIn, rotate, settle
}

struct SuccessBadge: View {
    @State private var trigger = 0

    var body: some View {
        Image(systemName: "checkmark.seal.fill")
            .font(.system(size: 80))
            .foregroundStyle(.green)
            .phaseAnimator(SuccessPhase.allCases, trigger: trigger) { view, phase in
                view
                    .scaleEffect(scale(for: phase))
                    .rotationEffect(rotation(for: phase))
                    .opacity(phase == .off ? 0 : 1)
            } animation: { phase in
                switch phase {
                case .off: .smooth(duration: 0.05)
                case .scaleIn: .spring(.bouncy, blendDuration: 0.3)
                case .rotate: .spring(response: 0.45, dampingFraction: 0.7)
                case .settle: .spring(.smooth)
                }
            }
            .onTapGesture { trigger += 1 }
    }

    private func scale(for phase: SuccessPhase) -> CGFloat {
        switch phase {
        case .off: 0
        case .scaleIn: 1.25
        case .rotate: 1.15
        case .settle: 1.0
        }
    }

    private func rotation(for phase: SuccessPhase) -> Angle {
        switch phase {
        case .off, .scaleIn: .zero
        case .rotate: .degrees(360)
        case .settle: .degrees(360)
        }
    }
}
```

### Per-phase animation override

The `animation: { phase in ... }` closure runs once per phase transition and returns the `Animation` to use *into* that phase. Returning `nil` from a switch case is invalid - return a default like `.smooth` instead.

### Gotchas

- Phase enum must be `CaseIterable + Hashable`. SwiftUI walks through `allCases` in declaration order.
- Transitions are sequential, never parallel. If two properties need to animate on different curves *at the same time*, use `KeyframeAnimator`.
- Without `trigger:`, the animator settles on the last phase and stops. To loop, repeat the same phase as last and rely on `trigger` toggling, or use `KeyframeAnimator(initialValue:repeating:content:)`.
- Tap-spam-resistance: increment a counter as `trigger` (`trigger += 1`) instead of toggling a `Bool`. Toggling can collapse rapid taps into a single phase change because SwiftUI dedupes equal values.
- The phase enum is type-erased to `Hashable` in the API; if you need values inside the phase use associated types or a separate value model.

---

## KeyframeAnimator deep-dive

### Anatomy

```swift
view.keyframeAnimator(
    initialValue: AnimationValues(),  // your custom value type, must be Equatable
    trigger: someValue                // optional - omit for one-shot on appear
) { content, values in
    content
        .scaleEffect(values.scale)
        .rotationEffect(values.rotation)
        .opacity(values.opacity)
} keyframes: { initial in
    KeyframeTrack(\.scale) {
        SpringKeyframe(1.3, duration: 0.15)
        SpringKeyframe(1.0, duration: 0.3, spring: .bouncy)
    }
    KeyframeTrack(\.rotation) {
        CubicKeyframe(.degrees(15), duration: 0.1)
        CubicKeyframe(.degrees(-15), duration: 0.2)
        CubicKeyframe(.degrees(0), duration: 0.15)
    }
}
```

There's also `keyframeAnimator(initialValue:repeating:content:keyframes:)` (no trigger, repeats forever) for ambient looping animations.

### The 4 keyframe types

| Type | Curve | Use |
|---|---|---|
| `LinearKeyframe(value, duration:)` | constant velocity | precise mechanical motion |
| `SpringKeyframe(value, duration:, spring:)` | settles with spring | natural arrival, overshoot |
| `CubicKeyframe(value, duration:)` | cubic bezier (ease) | classic ease-in/out feel |
| `MoveKeyframe(value)` | jump cut, no interpolation | reset to a baseline mid-sequence |

`SpringKeyframe`'s `spring:` parameter takes the same `Spring` you'd pass to `.spring(...)`. If omitted, uses a default smooth spring.

### Full example: custom loader with parallel tracks

```swift
struct LoaderValues {
    var rotation: Angle = .zero
    var scale: CGFloat = 1
    var opacity: Double = 1
}

struct PulseLoader: View {
    var body: some View {
        Image(systemName: "arrow.triangle.2.circlepath")
            .font(.system(size: 40))
            .keyframeAnimator(initialValue: LoaderValues(), repeating: true) { content, values in
                content
                    .rotationEffect(values.rotation)
                    .scaleEffect(values.scale)
                    .opacity(values.opacity)
            } keyframes: { _ in
                KeyframeTrack(\.rotation) {
                    LinearKeyframe(.degrees(360), duration: 1.5)
                }
                KeyframeTrack(\.scale) {
                    CubicKeyframe(1.1, duration: 0.75)
                    CubicKeyframe(1.0, duration: 0.75)
                }
                KeyframeTrack(\.opacity) {
                    CubicKeyframe(0.6, duration: 0.75)
                    CubicKeyframe(1.0, duration: 0.75)
                }
            }
    }
}
```

The total duration of each track determines its loop length. SwiftUI runs all tracks in parallel; if their total durations differ, each loops independently within the outer repeat. For a clean repeat, make all track durations equal.

### Trigger semantics

`trigger:` re-runs the entire keyframe sequence from `initialValue`. Increment a counter on the trigger side rather than toggling a `Bool` to avoid coalescing rapid events. The animation completes asynchronously - don't read end-state values immediately after setting the trigger.

---

## Combining Phase + Keyframe

You can wrap a `KeyframeAnimator` inside a phase to fire complex parallel tracks at a specific point in a state sequence:

```swift
enum LikePhase: CaseIterable { case idle, hit, settle }

struct LikeButton: View {
    @State private var phase: LikePhase = .idle
    @State private var keyTrigger = 0

    var body: some View {
        Image(systemName: "heart.fill")
            .foregroundStyle(.pink)
            .phaseAnimator([LikePhase.idle, .hit, .settle], trigger: keyTrigger) { view, ph in
                view
                    .scaleEffect(ph == .hit ? 1.4 : ph == .settle ? 1.0 : 1.0)
            } animation: { ph in
                switch ph {
                case .idle: .smooth(duration: 0.05)
                case .hit: .spring(.bouncy, blendDuration: 0.2)
                case .settle: .spring(.smooth)
                }
            }
            .onTapGesture { keyTrigger += 1 }
    }
}
```

For more exotic compositions (e.g., a keyframe animation playing on every settle into a phase), nest the `KeyframeAnimator` modifier inside the `content` closure of `phaseAnimator`.

---

## iOS 17+ Custom Animation protocol (brief)

The `CustomAnimation` protocol lets you build new animation types with full control over the velocity curve. Useful when none of the built-in springs / eases match a brand-specific motion identity. Implementation is non-trivial (you provide `animate(value:time:context:)` returning the interpolated value at time `t`). For 99% of work, the built-in springs + keyframes are enough. Reference: [Apple CustomAnimation](https://developer.apple.com/documentation/swiftui/customanimation).

---

## Sources

- [Apple PhaseAnimator](https://developer.apple.com/documentation/swiftui/phaseanimator)
- [Apple KeyframeAnimator](https://developer.apple.com/documentation/swiftui/keyframeanimator)
- [WWDC23 Wind your way through advanced animations](https://developer.apple.com/videos/play/wwdc2023/10157/)
- [Apple CustomAnimation protocol](https://developer.apple.com/documentation/swiftui/customanimation)
