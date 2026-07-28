# Springs Cheat Sheet

Spring tuning cheat sheet. `response` (time to settle) vs `dampingFraction` (overshoot intensity, `0...1`).
Use presets when in doubt; tune only when needed. Keep 3-5 named springs in your design system, no more.

---

## Visual map

```
                    dampingFraction
              0.5          0.7          0.85         1.0
            +------------+------------+------------+------------+
   r   0.2  | TWITCHY    | NERVOUS    | SNAPPY     | CRISP      |
   e        +------------+------------+------------+------------+
   s   0.4  | BOUNCY     | PLAYFUL    | SMOOTH     | CALM       |
   p        +------------+------------+------------+------------+
   o   0.6  | WONKY      | EXPRESSIVE | FLOATY     | SLUGGISH   |
   n        +------------+------------+------------+------------+
   s   0.8  | UNUSABLE   | DRAMATIC   | LAZY       | DEAD       |
   e        +------------+------------+------------+------------+
```

Reading rules:
- Drop response (move up the table) for UI work that needs to feel snappy.
- Drop dampingFraction (move left) for moments that should feel alive (success states, celebrations).
- Stay in the `0.2...0.5` x `0.7...1.0` rectangle for 95% of UI; venture out only for hero moments.

---

## Preset reference (iOS 17+)

| Preset | response | dampingFraction | Equivalent in iOS 17+ duration/bounce API |
|---|---|---|---|
| `.snappy` | 0.3 | 0.85 | `.spring(duration: 0.3, bounce: 0.15)` |
| `.bouncy` | 0.5 | 0.7 | `.spring(duration: 0.5, bounce: 0.3)` |
| `.smooth` | 0.5 | 1.0 | `.spring(duration: 0.5, bounce: 0)` |
| `.interactiveSpring()` | 0.15 | 0.86 | gesture-follow, very stiff |

The two API shapes are equivalent. Pick one and stay consistent across the codebase. The new `(duration:bounce:)` API is more designer-friendly (`bounce` reads as "how much overshoot"); the legacy `(response:dampingFraction:)` API matches WWDC23 documentation more closely.

---

## Recipes by use case

### Tap feedback
```swift
.spring(response: 0.2, dampingFraction: 0.85)
// or .snappy
```
40-200ms snap. The user just tapped, they want acknowledgment now.

### Sheet present
```swift
.spring(response: 0.45, dampingFraction: 0.85)
```
Slight overshoot communicates "object arrives". Matches Apple's default sheet-present curve.

### Sheet dismiss
```swift
.spring(response: 0.4, dampingFraction: 1.0)
// or .smooth
```
No overshoot on exit - exits should be subtler than entrances (motion-principles rule).

### Drag follow (gesture in flight)
```swift
.interactiveSpring(response: 0.15, dampingFraction: 0.86)
```
Stiff and quick; the spring catches up to the finger but doesn't lag. Used in `.onChanged` of a `DragGesture`.

### Hero / page transition
```swift
.spring(response: 0.5, dampingFraction: 0.85)
```
Slightly slower than UI; the user is watching a spatial narrative unfold.

### Bouncy reveal (use sparingly)
```swift
.spring(response: 0.4, dampingFraction: 0.65)
// or .bouncy
```
For success states, achievement unlocks, "delightful" reveals. Cap usage to 1-2 places per app or it becomes noise.

### Loading shimmer / breathing pulse
```swift
.linear(duration: 1.5).repeatForever(autoreverses: true)
```
Springs are the wrong tool for looping at constant speed. Use `.linear` or `.easeInOut` here.

---

## Custom Animation API (iOS 17+)

The `(duration:bounce:)` constructor:

```swift
.spring(duration: 0.4, bounce: 0.3)
```

- `duration: TimeInterval` - perceived total time of the spring (similar to response).
- `bounce: Double` in `0...1` - 0 is critically damped (no overshoot), 1 is full bounce. Designers map this directly: 0.3 = subtle bounce, 0.5 = expressive, 0.8 = celebratory.

Internally equivalent to `(response:dampingFraction:)` but the mental model is more natural for designers handing off specs.

---

## Gotchas

- **`dampingFraction: 0`** = perpetual oscillation. NEVER ship this. The spring will never settle and the view will animate indefinitely.
- **`response > 0.6`** feels sluggish on UI elements. Reserve for hero moments (full-screen page transitions, onboarding reveals) or scroll-driven choreography.
- **Mixing many different springs across the app** = inconsistent feel. Pick 3-5 named springs (e.g., `.tap`, `.sheet`, `.drag`, `.hero`, `.celebrate`) and reuse. Express them as static extensions on `Animation`:
  ```swift
  extension Animation {
      static let appTap = Animation.spring(response: 0.2, dampingFraction: 0.85)
      static let appSheet = Animation.spring(response: 0.45, dampingFraction: 0.85)
      static let appHero = Animation.spring(response: 0.5, dampingFraction: 0.85)
  }
  ```
- **Spring + non-spring on the same property** stacks confusingly. The outer `withAnimation` wins, but child implicit `.animation(_, value:)` modifiers still trigger; if both fire on the same value the result is unpredictable. Pick one.
- **`.interactiveSpring` outside of gestures** feels twitchy. Use it only when the value is being driven continuously by the user.

---

## Sources

- [GetStream/swiftui-spring-animations](https://github.com/GetStream/swiftui-spring-animations)
- [WWDC23 Animate with springs](https://developer.apple.com/videos/play/wwdc2023/10158/)
- [Apple Animation reference](https://developer.apple.com/documentation/swiftui/animation)
