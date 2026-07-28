# Liquid Glass Deep Dive (iOS 26)

> System-level glassmorphism with adaptive depth and morphing transitions. iOS 26+.
> Concise rules. Fallback patterns for older iOS at the bottom.

---

## What Liquid Glass Is

iOS 26 ships a system glassmorphism layer with adaptive depth, refraction, and morphing transitions across views. It is built on the same Metal stack as `.layerEffect` but optimized at the system level: the OS knows about device pixel density, surrounding content, and motion, and tunes blur radius, opacity, and refraction in real time. Pre-iOS 26 used `Material` (`.ultraThinMaterial` etc.), which is purely a backdrop blur. Liquid Glass adds light bending, edge highlights, and a coordinated namespace for morphing between glass surfaces.

---

## Basic API

| API | Purpose |
|---|---|
| `.glassEffect()` | Default glass (regular thickness) |
| `.glassEffect(.regular)` / `.thick` / `.thin` | Variants (clarity vs blur strength) |
| `.glassEffectID(_, in:)` | Pair a glass surface with a namespace for morphing |
| `GlassEffectContainer` | Group glass surfaces that should morph as one |
| `.glassBackgroundEffect(displayMode:)` | Older watchOS alias; iOS prefers `.glassEffect()` |

Variant guidance:
- `.thin`: subtle, content stays visible. Use for lightweight chrome.
- `.regular`: balanced, default. Use for cards, tab bars.
- `.thick`: heavy blur, stronger separation. Use for modals, focused surfaces.

---

## Recipe: Glass Card Morphing

Hero card that expands to a sheet. Both states share `glassEffectID`, the OS animates the morph.

```swift
struct ExpandingCard: View {
    @Namespace var glassNS
    @State var expanded = false

    var body: some View {
        ZStack {
            if !expanded {
                Image("hero")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 200, height: 280)
                    .glassEffect(.regular)
                    .glassEffectID("hero", in: glassNS)
                    .onTapGesture {
                        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
                            expanded = true
                        }
                    }
            } else {
                VStack {
                    Image("hero").resizable().scaledToFit()
                    Text("Details").font(.title)
                }
                .padding()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .glassEffect(.thick)
                .glassEffectID("hero", in: glassNS)
                .onTapGesture {
                    withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
                        expanded = false
                    }
                }
            }
        }
    }
}
```

The OS interpolates blur, refraction, and edge highlights between the two states.

---

## Recipe: Glass Tab Bar

Floating tab bar with `.glassEffect(.regular)` over scrolling content. The bar adapts its tint as content scrolls beneath.

```swift
struct GlassTabBar: View {
    @State var selected = 0
    let tabs = ["house", "magnifyingglass", "person"]

    var body: some View {
        ZStack(alignment: .bottom) {
            ScrollView {
                LazyVStack(spacing: 16) {
                    ForEach(0..<50) { i in
                        Card(index: i)
                    }
                }
                .padding()
            }

            HStack(spacing: 32) {
                ForEach(tabs.indices, id: \.self) { i in
                    Image(systemName: tabs[i])
                        .font(.title2)
                        .foregroundStyle(selected == i ? .primary : .secondary)
                        .frame(width: 44, height: 44)
                        .onTapGesture { selected = i }
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 12)
            .glassEffect(.regular)
            .clipShape(Capsule())
            .padding(.bottom, 16)
        }
    }
}
```

---

## Recipe: Glass Modal Stack

Stacked sheets with progressively heavier glass, signaling depth.

```swift
struct GlassModalStack: View {
    @State var first = false
    @State var second = false

    var body: some View {
        Button("Open") { first = true }
            .sheet(isPresented: $first) {
                VStack {
                    Text("Layer 1").font(.title)
                    Button("Deeper") { second = true }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .glassEffect(.thin)
                .sheet(isPresented: $second) {
                    Text("Layer 2")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .glassEffect(.thick) // heavier blur as we go deeper
                }
            }
    }
}
```

> Rule of thumb: each modal layer goes one tier thicker. `.thin` -> `.regular` -> `.thick`.

---

## iOS <26 Fallback Patterns

| iOS 26 API | Pre-iOS 26 fallback |
|---|---|
| `.glassEffect(.thin)` | `.background(.ultraThinMaterial)` |
| `.glassEffect(.regular)` | `.background(.regularMaterial)` |
| `.glassEffect(.thick)` | `.background(.thickMaterial)` |
| `.glassEffectID(_, in:)` | `matchedGeometryEffect(id:in:)` on a material-backed view |
| `GlassEffectContainer` | Manual `ZStack` + shared namespace |

```swift
@ViewBuilder
func adaptiveGlass<Content: View>(@ViewBuilder content: () -> Content) -> some View {
    if #available(iOS 26.0, *) {
        content().glassEffect(.regular)
    } else {
        content().background(.ultraThinMaterial)
    }
}
```

---

## What Doesn't Work Pre-iOS 26

- **True refraction** (light bending through glass). Material is flat backdrop blur.
- **Adaptive transparency** based on what's behind. Material is a fixed mix.
- **`glassEffectID` morphing**. Use `matchedGeometryEffect` on a material-backed view; the material itself doesn't animate between states, only the view's frame does.
- **Edge highlights** that respond to motion. Static border at best.

If those are non-negotiable for your design, gate the feature on iOS 26 and ship a simpler fallback.

---

## Gotchas

### Glass on glass nests poorly

Stacking glass on glass compounds blur and washes out content. Use `GlassEffectContainer` to group siblings into one rendered surface.

```swift
// BAD -- two passes, content disappears
Card().glassEffect(.regular)
    .padding()
    .background(.ultraThinMaterial)

// GOOD -- one container, one pass
GlassEffectContainer {
    HStack { Pill1(); Pill2() }
}
```

### Glass over solid backgrounds is invisible

Liquid Glass is designed to refract content beneath. Over a flat white or black solid, the effect is imperceptible. Use it over photographic, gradient, or animated backgrounds.

```swift
// BAD -- nothing to refract
ZStack {
    Color.white
    Card().glassEffect(.regular) // looks like a slightly grey card
}

// GOOD -- refractive content underneath
ZStack {
    Image("blurred-photo").resizable().scaledToFill()
    Card().glassEffect(.regular)
}
```

### Glass inside `LazyVStack` rows compounds cost

Each cell rendering its own glass means N GPU passes during scroll. Either lift the glass out of the cell or accept the cost only for visible cells (Lazy stacks help, but glass is still expensive per cell).

```swift
// BAD
LazyVStack {
    ForEach(items) { item in
        Card(item: item).glassEffect(.regular)
    }
}

// GOOD -- glass on the chrome only, cells use solid backgrounds
ZStack {
    LazyVStack {
        ForEach(items) { item in
            Card(item: item).background(.ultraThinMaterial.opacity(0.5))
        }
    }
    Header().glassEffect(.regular)
}
```

---

## Sources

- Apple HIG iOS 26 Materials (see Apple iOS 26 release notes)
- [Apple SwiftUI Materials documentation](https://developer.apple.com/documentation/swiftui/material)
- [dpearson2699/swift-ios-skills](https://github.com/dpearson2699/swift-ios-skills) (swiftui-liquid-glass module)
