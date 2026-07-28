---
name: compose-multiplatform
description: "Compose Multiplatform / KMP patterns - expect/actual composables, platform-specific code, density and font handling cross-target, iOS/Android/Desktop interop."
---

# Compose Multiplatform

> Compose Multiplatform (CMP) and Kotlin Multiplatform (KMP) patterns for cross-platform UI.
> Loaded for projects with `org.jetbrains.compose` plugin.
> Foundation: `../compose-motion/SKILL.md` for animation API; this file covers what's specific to writing one Compose codebase for Android + iOS + Desktop + Web.

---

## KMP vs CMP - quick clarification

**KMP** (Kotlin Multiplatform) is the language and build infrastructure: shared Kotlin code compiled to JVM, Native (iOS, macOS, Linux, Windows), and Wasm. **CMP** (Compose Multiplatform) is the UI framework on top of KMP, built by JetBrains as a port of Jetpack Compose. You write a single Compose codebase in `commonMain` that runs on Android, iOS, Desktop (JVM), and Web (Wasm). Platform-specific code lives in `androidMain`, `iosMain`, `desktopMain`, `wasmJsMain` and is wired in via `expect`/`actual` declarations.

---

## Project structure

```
composeApp/
├── src/
│   ├── commonMain/        ← shared Compose code (most of the app)
│   │   └── kotlin/
│   ├── androidMain/       ← Android-specific (uses Activity, Context)
│   ├── iosMain/           ← iOS-specific (uses UIKit/UIView interop)
│   ├── desktopMain/       ← JVM desktop (uses java.awt/swing if needed)
│   └── wasmJsMain/        ← Wasm web target
├── build.gradle.kts
iosApp/                    ← Xcode project consuming the generated framework
androidApp/                ← Android Application module (often merged into composeApp)
```

The `commonMain` folder should hold 80-95% of your code in a well-architected CMP project. If `iosMain` or `androidMain` start growing past a few hundred lines, you're probably leaking platform concerns into UI logic that could stay shared.

---

## `expect`/`actual` pattern

The KMP escape hatch when you genuinely need different implementations per target. Declare the contract once in `commonMain`, implement it once per target.

```kotlin
// commonMain
expect fun openShareSheet(text: String)

// androidMain
actual fun openShareSheet(text: String) {
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, text)
    }
    context.startActivity(Intent.createChooser(intent, null))
}

// iosMain
actual fun openShareSheet(text: String) {
    val activityVC = UIActivityViewController(
        activityItems = listOf(text),
        applicationActivities = null
    )
    UIApplication.sharedApplication.keyWindow
        ?.rootViewController
        ?.presentViewController(activityVC, true, null)
}
```

`expect`/`actual` works for top-level functions, classes, type aliases, and properties. The signature in `actual` must match exactly, including modifiers and default values.

---

## `expect`/`actual` for composables

Composables follow the same rules. Useful when a feature needs a platform-specific Compose API (Android `RuntimeShader`, iOS `UIKitView`, Desktop `SwingPanel`).

```kotlin
// commonMain
@Composable
expect fun PlatformBlur(modifier: Modifier = Modifier, content: @Composable () -> Unit)

// androidMain (uses RuntimeShader on Android 13+)
@Composable
actual fun PlatformBlur(modifier: Modifier, content: @Composable () -> Unit) {
    Box(modifier.graphicsLayer { renderEffect = blurEffect }) { content() }
}

// iosMain (uses UIVisualEffectView via UIKitView)
@Composable
actual fun PlatformBlur(modifier: Modifier, content: @Composable () -> Unit) {
    Box(modifier) {
        UIKitView(
            factory = { UIVisualEffectView(effect = UIBlurEffect.systemMaterial()) },
            modifier = Modifier.matchParentSize()
        )
        content()
    }
}
```

Rule: `expect` composables should be the exception, not the rule. Most "platform feel" differences can be tuned via tokens (colors, corner radii, spring stiffness) in `commonMain`, not via separate code paths.

---

## `LocalDensity` cross-platform

On Android, `LocalDensity.current.density` reflects the device DPI bucket (1.0, 1.5, 2.0, 3.0...). On iOS, density is computed from `UIScreen.scale` (typically 2.0 or 3.0 on Retina). On Desktop, density depends on the screen scaling factor (1.0 by default; 2.0 on Retina-class displays; user-configurable on Windows). On Wasm, density follows `window.devicePixelRatio`.

Don't hardcode `Dp` to pixel ratios; trust `Dp` and `LocalDensity` to handle conversion. If you need an exact pixel value (e.g., for a `Canvas` draw operation), do the conversion explicitly:

```kotlin
val density = LocalDensity.current
val pxValue = with(density) { 16.dp.toPx() }
```

Avoid reading `density` inside hot loops; cache the conversion.

---

## `LocalConfiguration` and platform-aware UI

`LocalConfiguration.current` is **Android-only** and lives in `androidMain`. For CMP, prefer the cross-platform alternatives:

- `LocalWindowInfo.current.containerSize` - the window/screen size as `IntSize`, available in `commonMain`.
- `LocalDensity.current` - density, available in `commonMain`.
- `LocalLayoutDirection.current` - LTR / RTL.
- `BoxWithConstraints { ... }` - read `maxWidth` / `maxHeight` directly inside layout.

If you need real device characteristics (orientation, idiom, model), wrap the access in `expect`/`actual` and pass a typed object like `PlatformInfo` to the common layer.

---

## Fonts cross-platform via Compose Resources

`org.jetbrains.compose.resources` is the shared resources plugin. Drop fonts in `commonMain/composeResources/font/`, and the Gradle plugin generates a typed `Res` accessor.

```
composeApp/src/commonMain/composeResources/
├── font/
│   ├── Inter-Regular.ttf
│   └── Inter-Bold.ttf
├── drawable/
│   └── logo.svg
└── values/
    ├── strings.xml          ← default locale
    └── strings.fr.xml       ← French overrides
```

Usage in `commonMain`:

```kotlin
import myproject.composeapp.generated.resources.Inter_Regular
import myproject.composeapp.generated.resources.Inter_Bold
import myproject.composeapp.generated.resources.Res

val InterFamily = FontFamily(
    Font(Res.font.Inter_Regular, FontWeight.Normal),
    Font(Res.font.Inter_Bold, FontWeight.Bold),
)

Text("Hello", fontFamily = InterFamily)
```

Same pattern for `Res.drawable.logo` (image), `Res.string.app_name` (localized string via `stringResource(...)`), `Res.file.config` (raw bytes via `Res.readBytes(...)`).

---

## iOS interop with SwiftUI

CMP produces a `UIViewController` you can drop into a SwiftUI app. KMP generates a top-level Kotlin function (commonly named `MainViewController()` or `ComposeUIViewController { ... }`) that returns a `UIViewController`. Wrap it with `UIViewControllerRepresentable`.

```kotlin
// iosMain/kotlin/main.ios.kt
fun MainViewController(): UIViewController = ComposeUIViewController {
    AppContent()  // commonMain composable
}
```

```swift
// iOS app target
import SwiftUI
import ComposeApp  // KMP-generated framework

struct ComposeContent: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> UIViewController {
        Main_iosKt.MainViewController()
    }
    func updateUIViewController(_ uiViewController: UIViewController, context: Context) {}
}

struct ContentView: View {
    var body: some View { ComposeContent().ignoresSafeArea() }
}
```

The Kotlin function name gets mangled to `Main_iosKt.MainViewController()` because the file is `main.ios.kt`. Check the generated framework headers if the symbol name surprises you.

---

## Android entry point

No interop ceremony on Android. The Activity hosts the common composable directly via `setContent { ... }`.

```kotlin
// androidApp/src/main/kotlin/MainActivity.kt
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AppContent()  // commonMain composable
        }
    }
}
```

If you need to pass `Context` or `Activity` into `commonMain`, expose it via a DI graph or an `expect class PlatformContext` in `commonMain` with `actual class PlatformContext(val context: Context)` in `androidMain`.

---

## Embedding SwiftUI/UIKit inside a Compose iOS view (the reverse direction)

Use `UIKitView` for a `UIView` factory or `UIKitViewController` for a `UIViewController` factory.

```kotlin
// iosMain
UIKitView(
    factory = {
        UISwitch().apply {
            addTarget(target, action = NSSelectorFromString("onToggle:"), forControlEvents = UIControlEventValueChanged)
        }
    },
    modifier = Modifier.size(48.dp, 32.dp)
)
```

For SwiftUI views: wrap them in a `UIHostingController` exposed via a Swift `@objc` bridge function, then call from Kotlin via the generated headers (cinterop). See `references/cmp-interop.md` for the full pattern.

---

## Animation cross-platform

All animation APIs (`animate*AsState`, `AnimatedVisibility`, `updateTransition`, `SharedTransitionLayout`) work identically across targets in CMP 1.7+. Spring tuning written in `commonMain` produces the same physics on Android and iOS. Gestures (`Modifier.draggable`, `Modifier.pointerInput`) work cross-platform with the same API surface.

The animation primer lives in `../compose-motion/SKILL.md`. Cross-platform deltas to keep in mind:
- iOS first-frame is slower (Skia bootstrap); a 200ms enter animation feels tighter on Android, slightly delayed on iOS cold start.
- Wasm motion can stutter on first frame (JIT warmup); pre-warm critical paths or hide motion until interactive.

---

## What does NOT work (gotchas)

- **Drawer state on iOS**: native `ModalNavigationDrawer` swipe-to-open from the leading edge conflicts with iOS's back-swipe gesture. Use a button trigger or move the swipe area inward 30dp+.
- **`LayoutDirection.Rtl` quirks**: Android handles RTL natively, iOS Compose had bugs in 1.6 (text alignment, padding inversions). Improved in 1.7+ but verify with real Arabic/Hebrew strings.
- **Soft keyboard handling**: `imePadding()` works on Android out of the box. On iOS Compose 1.6+, it requires `IOSKeyboardEventListener` setup or a `WindowInsets` observer wired through the platform layer.
- **`Color.parseHex(...)`** does not exist in Compose. Use `Color(0xFFRRGGBB)` or write a tiny extension.
- **System fonts on iOS via Compose**: do not fallback to `FontFamily.SansSerif` and expect SF Pro. Compose on iOS ships its own font fallback chain. Either bundle SF Pro via Compose Resources (license-permitting) or use `UIKitView` to drop a native `UILabel` for system-font text.
- **Animations on Web (Wasm)**: heavier startup, occasional first-frame stutter; profile with browser devtools and lazy-load heavy animation graphs.
- **`java.util.UUID`, `java.io.File`** and other JVM-only APIs are forbidden in `commonMain` if you ship to iOS or Wasm. Use `kotlinx.uuid`, `kotlinx-io`, or the `okio` multiplatform port.

---

## CMP version notes (April 2026 baseline)

- Compose Multiplatform 1.7 stable: `SharedTransitionLayout` cross-platform, improved iOS keyboard handling, lifecycle observability via `LocalLifecycleOwner` on iOS.
- Kotlin 2.0+ required (K2 compiler).
- Some Material 3 components have platform-specific look (e.g., `Switch` on iOS auto-renders with iOS-style proportions; `DatePicker` stays Material across all targets).
- `compose-multiplatform-resources` plugin is the standard for assets; the older `moko-resources` is no longer recommended for new projects.

---

## Performance considerations

- **iOS first-frame** is slower than Android (Skia bootstrapping ~150-300ms cold). Keep your splash visible until the first composition emits, or pre-warm with a transparent root composable.
- **Wasm bundle size**: aim for <2MB compressed. Tree-shake heavy deps, lazy-load secondary screens via `kotlinx.coroutines` deferred composition, and inspect the `.wasm` output in `wasmJsBrowserDistribution`.
- **Desktop**: cold start is fast on JVM; AOT compilation via Kotlin/Native is overkill for desktop unless you need a single-file binary.
- **Android**: same baseline as Jetpack Compose - profile with the Compose compiler stability metrics and `Layout Inspector` recomposition counts.

---

## Anti-Patterns

| BAD | GOOD | Why |
|---|---|---|
| Reflection trick or `System.getProperty("os.name")` to detect platform inside `commonMain` | `expect`/`actual` with a typed `Platform` object | Reflection breaks on Wasm/Native; `expect`/`actual` is the contract the compiler enforces |
| Assuming Android `Context` is reachable in `commonMain` | Inject a typed dependency via `expect class PlatformContext` or a DI scope | `Context` does not exist on iOS/Desktop/Wasm; the code will not compile for those targets |
| Hardcoding Material colors that look great on Android but jarring on iOS | Define a `commonMain` design system, then optionally adjust 2-3 tokens via `actual` | Cross-platform consistency is good, but iOS users notice when a Material blue feels alien on iPhone |
| `LaunchedEffect(Unit) { while(true) { delay(16); ... } }` in `commonMain` | `rememberInfiniteTransition()` or scope to lifecycle events | Tight coroutine loops drain battery on iOS; infinite transitions pause when offscreen |

---

## Quick Reference: Loading Sub-skills

| Need | Load |
|---|---|
| iOS / Android interop deep-dive | `references/cmp-interop.md` |
| Per-platform behavior catalog | `references/cmp-platform-quirks.md` |
| Animation API | `../compose-motion/SKILL.md` |
| Advanced graphics (M3 Expressive, AGSL on Android only) | `../compose-graphics/SKILL.md` |
| iOS-side native interop with SwiftUI | `../swiftui-motion/SKILL.md` (when target is iOS and SwiftUI native blend wanted) |
| Mobile UX context | `../mobile-principles/SKILL.md` |
| Desktop UX context | `../desktop-principles/SKILL.md` |
| Foundation | `../motion-principles/SKILL.md` |

---

## Sources

- [Meet-Miyani/compose-skill](https://github.com/Meet-Miyani/compose-skill) (KMP/CMP comprehensive)
- [JetBrains Compose Multiplatform](https://www.jetbrains.com/lp/compose-multiplatform/)
- [Compose Multiplatform docs](https://www.jetbrains.com/help/kotlin-multiplatform-dev/compose-multiplatform.html)
- [skydoves/Orbital](https://github.com/skydoves/Orbital) (KMP-aware shared transitions)
