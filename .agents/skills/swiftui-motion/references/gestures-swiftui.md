# SwiftUI Gestures deep-dive

Gesture composition, conflict resolution, velocity, and the patterns that ship on every modern iOS app.
SwiftUI gestures are declarative; conflicts are resolved by composition, not by `.cancel()` calls.

---

## Gesture types reference

### TapGesture

```swift
.gesture(
    TapGesture(count: 2).onEnded { print("double tap") }
)
// Single tap is the default (count: 1)
```

Discrete (fires once on completion). `count:` recognizes N taps within the system double-tap interval.

### LongPressGesture

```swift
.gesture(
    LongPressGesture(minimumDuration: 0.5)
        .onChanged { _ in /* press detected, not yet "long" */ }
        .onEnded { _ in /* threshold crossed */ }
)
```

`minimumDuration` is the threshold; `maximumDistance` (default 10pt) is how far the finger can drift before the gesture cancels.

### DragGesture

```swift
.gesture(
    DragGesture(minimumDistance: 0)
        .onChanged { value in offset = value.translation }
        .onEnded { value in
            withAnimation(.spring(.smooth)) { offset = .zero }
        }
)
```

`minimumDistance: 0` recognizes immediately on touch-down (use for drag-without-tap-fallback). `minimumDistance: 10` (default) means the user has to actually drag - taps still pass through to children. Pick deliberately:

| `minimumDistance` | Behavior |
|---|---|
| `0` | Recognizes on touch-down. Steals taps from children. Use for drag handles. |
| `10` (default) | Distinguishes drag from tap. Use for swipe-to-dismiss patterns. |
| `> 30` | Only "intentional" drags. Use for gesture overlays that must coexist with scrolling content. |

`coordinateSpace:` lets you read translations in `.local` (default), `.global`, or a named coordinate space - useful for cross-view drags.

### MagnifyGesture (iOS 17+, replaces MagnificationGesture)

```swift
@State private var scale: CGFloat = 1
@State private var lastScale: CGFloat = 1

Image("photo")
    .scaleEffect(scale)
    .gesture(
        MagnifyGesture()
            .onChanged { value in scale = lastScale * value.magnification }
            .onEnded { _ in lastScale = scale }
    )
```

`value.magnification` is the cumulative pinch ratio since gesture start. Multiply by the previous `lastScale` to compose successive pinches.

### RotateGesture (iOS 17+, replaces RotationGesture)

```swift
@State private var rotation: Angle = .zero
@State private var lastRotation: Angle = .zero

Image("photo")
    .rotationEffect(rotation)
    .gesture(
        RotateGesture()
            .onChanged { value in rotation = lastRotation + value.rotation }
            .onEnded { _ in lastRotation = rotation }
    )
```

Rare on phones (one-handed), more common on iPad and visionOS. Combine with `MagnifyGesture` via `.simultaneously(with:)` for a photo-editor-style canvas.

### SpatialTapGesture (iOS 17+)

```swift
.gesture(
    SpatialTapGesture()
        .onEnded { value in
            print("tapped at \(value.location)")
        }
)
```

Same as `TapGesture` but reports the local location. Useful for ripple effects, zoom-to-point on photo viewers, drawing apps.

---

## Composition operators

### `.simultaneously(with:)` - parallel recognition

```swift
let drag = DragGesture().onChanged { offset = $0.translation }
let magnify = MagnifyGesture().onChanged { scale = $0.magnification }

.gesture(drag.simultaneously(with: magnify))
```

Both gestures recognize together. Use for canvas / photo viewers that need pan + zoom at the same time.

### `.sequenced(before:)` - one must complete first

```swift
let press = LongPressGesture(minimumDuration: 0.3)
let drag = DragGesture()

.gesture(
    press.sequenced(before: drag)
        .onChanged { value in
            switch value {
            case .first: break  // long-press in progress
            case .second(_, let dragValue):
                if let d = dragValue { offset = d.translation }
            }
        }
)
```

Classic "press-and-hold-then-drag" pattern (iOS reorder, drag-to-pin on Maps). The drag won't recognize until the long-press completes.

### `.exclusively(before:)` - one OR the other

```swift
let tap = TapGesture()
let longPress = LongPressGesture()

.gesture(tap.exclusively(before: longPress))
```

If both could recognize, the first one wins. Rare in practice - usually you want simultaneous or sequenced.

---

## Conflict resolution patterns

### Vertical scroll vs horizontal swipe

```swift
DragGesture(minimumDistance: 10)
    .onChanged { value in
        // Claim the gesture only if the drag is dominantly horizontal
        let horizontal = abs(value.translation.width)
        let vertical = abs(value.translation.height)
        guard horizontal > vertical * 1.5 else { return }
        offset = value.translation.width
    }
```

By the time `onChanged` first fires, the user has moved 10pt+. Compare horizontal vs vertical magnitude before claiming - otherwise you fight the parent `ScrollView`.

### Tap vs drag

```swift
// Drag with minimumDistance: 0 swallows taps - children never receive them.
DragGesture(minimumDistance: 0)

// Use minimumDistance: 5+ to let taps pass through.
DragGesture(minimumDistance: 5)
```

Default is 10. Lower it only if you need touch-down feedback (e.g., "press anywhere to dismiss" style overlays).

### Native nav back-swipe vs custom horizontal pan (iOS)

The system back-gesture lives on the leading edge (left in LTR). Custom horizontal pans there will fight it. Detect and skip:

```swift
DragGesture(minimumDistance: 10)
    .onChanged { value in
        // Ignore drags that started near the leading edge - leave them to the system
        guard value.startLocation.x > 30 else { return }
        offset = value.translation.width
    }
```

Same logic for the trailing edge if you support right-handed swipe-back, or for the bottom edge (home indicator).

---

## GestureMask + simultaneousGesture

`.simultaneousGesture(_:including:)` adds a gesture without claiming the input - both your gesture and the existing one recognize:

```swift
.simultaneousGesture(
    LongPressGesture().onEnded { _ in showContextMenu() },
    including: .gesture
)
```

`GestureMask` controls which gestures are eligible to fire on this view:

| Mask | Recognizes |
|---|---|
| `.gesture` | Only the gesture you just attached |
| `.subviews` | Only gestures attached to descendant views |
| `.all` | Both (default) |
| `.none` | Disable all gestures on this subtree |

Use `.subviews` when you want a parent overlay to coexist with child taps; use `.gesture` to suppress children entirely.

---

## Velocity / momentum

`DragGesture.Value` exposes prediction APIs that account for the user's flick velocity:

| Property | Meaning |
|---|---|
| `translation` | Current cumulative translation since gesture start |
| `predictedEndTranslation` | Where translation would land if released now (includes momentum) |
| `predictedEndLocation` | Same in absolute coordinates |
| `velocity` (iOS 17+) | `CGSize` of points per second on x/y |

Fling pattern using prediction:

```swift
DragGesture()
    .onEnded { value in
        let predictedX = value.predictedEndTranslation.width
        let dismissThreshold: CGFloat = 100
        if predictedX > dismissThreshold {
            withAnimation(.spring(.smooth)) { offset.width = 1000 }
            // trigger dismiss
        } else {
            withAnimation(.interactiveSpring()) { offset = .zero }
        }
    }
```

Direct velocity (iOS 17+):

```swift
.onEnded { value in
    let vx = value.velocity.width  // pt/s
    if abs(vx) > 800 { /* fast flick */ }
}
```

---

## Common patterns

### Swipe-to-dismiss (modal sheet)

```swift
@State private var dragOffset: CGFloat = 0

VStack { /* sheet content */ }
    .offset(y: dragOffset)
    .gesture(
        DragGesture(minimumDistance: 10)
            .onChanged { value in
                dragOffset = max(0, value.translation.height)  // only downward
            }
            .onEnded { value in
                let predicted = value.predictedEndTranslation.height
                if predicted > 150 {
                    withAnimation(.spring(.smooth)) { dragOffset = 800 }
                    onDismiss()
                } else {
                    withAnimation(.spring(.snappy)) { dragOffset = 0 }
                }
            }
    )
```

### Pull-to-refresh

```swift
List { /* rows */ }
    .refreshable {
        await viewModel.reload()
    }
```

iOS 15+. Built-in, accessible, respects scroll-views. Don't reinvent with `DragGesture`.

### Pinch-to-zoom an image

```swift
@State private var scale: CGFloat = 1
@State private var lastScale: CGFloat = 1

Image("photo")
    .scaleEffect(scale)
    .gesture(
        MagnifyGesture()
            .onChanged { value in
                scale = max(1, min(4, lastScale * value.magnification))
            }
            .onEnded { _ in lastScale = scale }
    )
```

Always clamp scale to a reasonable range (typically 1...4 for photos, 0.5...10 for maps).

### Double-tap-to-zoom

```swift
.gesture(
    TapGesture(count: 2).onEnded {
        withAnimation(.spring(.smooth)) {
            scale = scale > 1 ? 1 : 2
            lastScale = scale
        }
    }
)
```

Use alongside `MagnifyGesture` via `.simultaneously(with:)` so users can both pinch and double-tap.

---

## Sources

- [Apple Composing SwiftUI gestures](https://developer.apple.com/documentation/swiftui/composing-swiftui-gestures)
- [Apple Gesture protocol](https://developer.apple.com/documentation/swiftui/gesture)
- [Apple DragGesture.Value](https://developer.apple.com/documentation/swiftui/draggesture/value)
- [WWDC23 Beyond scroll views](https://developer.apple.com/videos/play/wwdc2023/10159/)
