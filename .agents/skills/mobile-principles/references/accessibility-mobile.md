# Mobile Accessibility (deep-dive)

Mobile accessibility patterns. Screen readers, dynamic type, contrast, motor accommodations.
Cross-platform reference for SwiftUI, Compose, and the mobile web. Backs up the parent SKILL.md's reduced-motion section with the Android 14+ nuance.

---

## Screen readers

### VoiceOver (iOS / macOS)

VoiceOver reads `accessibilityLabel`, then `accessibilityValue`, then `accessibilityHint`. Traits (`accessibilityAddTraits`) tell it the element's role.

```swift
struct VolumeSlider: View {
  @Binding var value: Double // 0...1

  var body: some View {
    CustomTrack(value: value)
      .accessibilityElement()
      .accessibilityLabel("Volume")
      .accessibilityValue("\(Int(value * 100)) percent")
      .accessibilityHint("Swipe up or down to adjust")
      .accessibilityAddTraits(.isAdjustable)
      .accessibilityAdjustableAction { direction in
        switch direction {
        case .increment: value = min(1, value + 0.1)
        case .decrement: value = max(0, value - 0.1)
        @unknown default: break
        }
      }
  }
}
```

### TalkBack (Android Compose)

Compose builds a semantics tree from modifiers. `clearAndSetSemantics` replaces children's semantics (use it when a custom composable should be announced as one element). `traversalIndex` controls reading order.

```kotlin
Box(
  modifier = Modifier
    .size(48.dp)
    .clickable(onClick = onToggle)
    .clearAndSetSemantics {
      contentDescription = if (liked) "Liked, double tap to unlike" else "Not liked, double tap to like"
      role = Role.Button
      stateDescription = if (liked) "On" else "Off"
    },
) {
  Icon(if (liked) Icons.Filled.Favorite else Icons.Outlined.FavoriteBorder, contentDescription = null)
}
```

### Web (mobile)

ARIA on mobile is the same API as desktop, just delivered to VoiceOver/TalkBack instead of NVDA/JAWS. No major divergence.

```html
<div role="slider" aria-label="Volume"
  aria-valuemin="0" aria-valuemax="100" aria-valuenow="60"
  aria-describedby="vol-help" tabindex="0"></div>
<p id="vol-help" class="visually-hidden">Swipe up or down to adjust</p>
```

---

## Dynamic type / font scaling

**SwiftUI** - system styles scale. Custom fonts opt in via `UIFontMetrics` or `dynamicTypeSize`.

```swift
Text("Hello").font(.body) // scales

Text("Custom").font(.custom("Inter-Regular", size: 17, relativeTo: .body))
  .dynamicTypeSize(.xSmall ... .accessibility3)
```

**Compose** - use Material typography; read `LocalDensity.current.fontScale` for extreme sizes.

```kotlin
val fontScale = LocalDensity.current.fontScale
Text(
  text = "Headline",
  style = MaterialTheme.typography.headlineSmall,
  maxLines = if (fontScale > 1.3f) 3 else 2,
)
```

**Web** - relative units, cap with `clamp()`.

```css
:root { font-size: 100%; }
h1 { font-size: clamp(1.5rem, 4vw + 1rem, 2.5rem); }
p  { font-size: 1rem; line-height: 1.5; }
```

---

## Contrast (WCAG 2.2 AA)

| Element | Ratio |
|---|---|
| Normal text (<18pt or <14pt bold) | 4.5:1 |
| Large text (>=18pt or >=14pt bold) | 3:1 |
| Non-text UI components, icons, focus rings | 3:1 |

Tools: Stark plugin (Figma), Xcode Accessibility Inspector (Audit tab), Android Accessibility Scanner. Never rely on color alone (WCAG 1.4.1): pair it with an icon, label, or pattern.

---

## Motor accommodations

**iOS** - detect alternative input methods:

```swift
if UIAccessibility.isAssistiveTouchRunning {
  // increase tap targets, slow auto-dismiss, avoid time-limited gestures
}
// also: isSwitchControlRunning, isVoiceOverRunning
```

**Android - reduce motion (the nuance).** Two different signals. The parent SKILL.md uses `Settings.Global.ANIMATOR_DURATION_SCALE` for cross-version safety, but that is the developer-options toggle, not the user-facing accessibility setting. Since Android 14 (API 34), the proper signal is `AccessibilityManager.areTransitionsEnabled()`, wired to Settings -> Accessibility -> Remove animations.

```kotlin
@Composable
fun rememberReduceMotion(): Boolean {
  val context = LocalContext.current
  return remember {
    val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as AccessibilityManager
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
      !am.areTransitionsEnabled() // API 34+: user-facing toggle
    } else {
      Settings.Global.getFloat( // fallback: developer-options
        context.contentResolver,
        Settings.Global.ANIMATOR_DURATION_SCALE,
        1f,
      ) == 0f
    }
  }
}
```

Switch Access works if you respect standard focusable semantics (`Modifier.focusable()`, proper traversal order). Avoid time-limited gestures; provide a button alternative.

**Web:**

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    transition-duration: 0.001ms !important;
  }
}
```

Large click targets (44px min, WCAG 2.5.5), no hover-only affordances, no drag-only interactions without a button fallback.

---

## Testing checklist

- [ ] VoiceOver and TalkBack pass: every interactive element announced with a clear label and role.
- [ ] Dynamic Type at 200% (iOS xxxLarge / Android fontScale 2.0): no truncation, no overlap.
- [ ] Contrast pass: 4.5:1 normal text, 3:1 large text and non-text components.
- [ ] All interactive elements have labels (no unlabeled icon button).
- [ ] No information conveyed by color alone.
- [ ] All gestures have a non-gesture alternative (button, menu, keyboard equivalent).

---

## Sources

- Apple Accessibility: https://developer.apple.com/accessibility/
- Android Accessibility: https://developer.android.com/guide/topics/ui/accessibility
- WCAG 2.2: https://www.w3.org/TR/WCAG22/
