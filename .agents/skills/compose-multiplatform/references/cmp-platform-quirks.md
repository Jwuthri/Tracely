# CMP Platform Quirks

Catalog of platform-specific behaviors and surprising differences across Android / iOS / Desktop / Web targets in CMP. Updated for CMP 1.7 (April 2026 baseline).
The point is not to be exhaustive but to flag the cases where "write once, run everywhere" leaks - so you can plan for them rather than discover them in QA.

---

## Layout / sizing

### iOS safe area
`Modifier.windowInsetsPadding(WindowInsets.safeDrawing)` works on both iOS and Android in CMP 1.7+. Pre-1.7, you needed iOS-specific handling to read `UIScreen.mainScreen.bounds` and subtract notch/home indicator manually.

Always verify on a physical iPhone with a notch (iPhone 14 Pro and up have the Dynamic Island, which has the same insets as the notch but different visual treatment). The simulator's notched devices give correct values; older simulators without notches will silently report zero insets.

```kotlin
Box(
    Modifier
        .fillMaxSize()
        .windowInsetsPadding(WindowInsets.safeDrawing)
) {
    AppContent()
}
```

### Desktop window resizing
Compose composables receive `LocalWindowInfo.current.containerSize` updates as the user drags the window edge. Animations that read window size in `LaunchedEffect` or directly inside layout can stutter during resize because the resize emits ~60 events per second. Throttle reads with `derivedStateOf`:

```kotlin
val windowInfo = LocalWindowInfo.current
val widthDp by remember {
    derivedStateOf { windowInfo.containerSize.width.dp }
}
```

### Web (Wasm) viewport
The Compose canvas fills its host element by default. CSS `width: 100vw; height: 100vh` on the wrapper is the typical setup. Watch out for browser zoom: zooming the page changes `devicePixelRatio` and your `Dp` values stay constant in CSS pixels but render at different physical pixel sizes. Test at 100%, 125%, 150%.

---

## Inputs

### Soft keyboard (iOS)
`imePadding()` requires `IOSKeyboardEventListener` setup in CMP 1.7. Pre-1.7, you had to handle it manually via `UIKeyboardWillShowNotification`. The listener attaches when the Compose view controller mounts; if you're embedding inside SwiftUI and the SwiftUI parent already adjusts for the keyboard, you'll get double-adjustment. Disable one side.

### Hardware keyboard (Desktop)
`Modifier.onKeyEvent { event -> ... }` works for global key handling. Use `Modifier.onPreviewKeyEvent` to intercept before child composables. `Key.Tab`, `Key.Enter`, modifier keys (`event.isCtrlPressed`, `event.isMetaPressed`) are platform-aware.

### Native gestures conflict (iOS)
Edge swipe-back (`UIScreenEdgePanGestureRecognizer`) overrides custom horizontal pan in the leading 30dp on iOS. If your app uses a swipeable carousel or drawer that starts from the edge, users on iOS will trigger system back navigation instead. Mitigations:
- Move the swipe area inward 30dp+.
- Disable the system gesture by setting `interactivePopGestureRecognizer.isEnabled = false` on the navigation controller (only if you control the host controller).

### Wasm input
`Modifier.pointerInput` works for mouse and touch. Right-click via mouse fires as a secondary press; long-press on touch is detected via `detectTapGestures(onLongPress = ...)`. Wheel events come through `Modifier.scrollable`.

---

## Rendering

### Skia on Android vs Skiko on iOS/Desktop/Web
Both targets use Skia as the rendering engine, but Android uses the Skia bundled with the OS while iOS/Desktop/Web ship Skiko (Kotlin-wrapped Skia). Same engine family, slightly different driver, can produce subtly different anti-aliasing on diagonal lines or sub-pixel text. Visual diff testing across platforms catches it; pixel-exact comparisons will fail.

### Compose 1.7 SharedTransitionLayout
Works cross-platform but iOS performance is slightly slower than Android - benchmark hero animations on iPhone 12 baseline. If you target lower-end devices (iPhone 8, older Android budget phones), keep shared-element scopes shallow (avoid wrapping a screen with 100+ composables in a single `SharedTransitionLayout`).

### AGSL shaders (advanced)
Android only. AGSL (Android Graphics Shading Language) requires Android 13+ (`RuntimeShader`). iOS, Desktop, and Web do not have an equivalent. If you need shaders cross-platform:
- iOS: drop a Metal-backed `MTKView` via `UIKitView`.
- Desktop: use OpenGL/Vulkan via Skiko's lower-level APIs (advanced).
- Wasm: WebGL/WebGPU via JS interop.

For most projects, restrict shaders to Android-only feature flags rather than attempting cross-platform parity.

---

## Material 3 components

| Component | Android | iOS | Desktop | Web |
|---|---|---|---|---|
| `Switch` | Material toggle | iOS-style auto-rendering | Material toggle | Material toggle |
| `Slider` | Material thumb | Material thumb (no native iOS slider) | Material thumb | Material thumb |
| `DatePicker` | Material grid | Material grid (no native UIDatePicker) | Material grid | Material grid |
| `BottomAppBar` | Material | Foreign-feeling on iOS | OK on macOS-style apps | OK |
| `NavigationBar` | Material | Foreign on iOS - consider native `TabView` | Adapts to desktop | Adapts |
| `TopAppBar` | Material | Acceptable but not a UINavigationBar | Title bar territory | Acceptable |

If you need native iOS pickers, tab bars, or nav bars: drop them in via `UIKitView` / `UIKitViewController`. The reverse (native Android Material on iOS) is rarely a goal.

---

## Lifecycle

| Platform | Lifecycle source | Compose access |
|---|---|---|
| Android | `Activity` lifecycle | `LocalLifecycleOwner.current` |
| iOS | Scene phase via `UIApplication` notifications | `LocalLifecycleOwner.current` (CMP 1.7+) |
| Desktop | Window close vs app close differ | `LocalLifecycleOwner.current` (CMP 1.7+) |
| Web | `visibilitychange` events on the document | `LocalLifecycleOwner.current` (limited) |

In CMP 1.7+, `LifecycleEventEffect` works cross-platform:

```kotlin
LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
    analytics.track("screen_resumed")
}
```

Desktop nuance: closing the last window can either quit the app or keep it running (macOS dock convention). Handle both: `Window(onCloseRequest = ::exitApplication)` to force quit, or hook `onCloseRequest` to hide-only.

---

## Resources

Use `org.jetbrains.compose.resources` plugin for fonts, images, strings, files. Generated `Res.font.X`, `Res.drawable.X`, `Res.string.X`, `Res.file.X` accessors live in a generated package keyed off your module name (e.g., `myproject.composeapp.generated.resources.Res`).

Localization: `commonMain/composeResources/values/strings.xml` is the default; add `values-fr/strings.xml` for French, `values-ja/strings.xml` for Japanese. Access via `stringResource(Res.string.app_name)`. Plural forms via `pluralStringResource(Res.plurals.items, count)`.

Drawable formats: SVG, PNG, JPEG. Vector drawables (Android XML format) are supported but SVG is preferred for cross-platform.

---

## Build / packaging

| Target | Command | Output |
|---|---|---|
| Android APK | `./gradlew :composeApp:assembleRelease` | `composeApp/build/outputs/apk/release/*.apk` |
| Android AAB | `./gradlew :composeApp:bundleRelease` | `composeApp/build/outputs/bundle/release/*.aab` |
| iOS framework | `./gradlew :composeApp:linkReleaseFrameworkIosArm64` | `composeApp/build/bin/iosArm64/releaseFramework/ComposeApp.framework` |
| iOS via SPM | Generated repo with `Package.swift` consumed by Xcode | Swift Package |
| Desktop installer | `./gradlew :composeApp:packageDistributionForCurrentOS` | `.dmg` (macOS), `.msi` (Windows), `.deb` (Linux) |
| Wasm dev | `./gradlew :composeApp:wasmJsBrowserDevelopmentRun` | Local dev server |
| Wasm prod | `./gradlew :composeApp:wasmJsBrowserDistribution` | `composeApp/build/dist/wasmJs/productionExecutable/` |

iOS framework is consumed in Xcode either by directly linking the `.framework` (legacy) or via Swift Package Manager from a generated repo (recommended for CI). The SPM approach lets you version the binary like any other dependency.

---

## Common errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `ImportError: Symbol not found` on iOS at runtime | A `commonMain` API used a JVM-only thing (e.g., `java.util.UUID`, `java.io.File`) | Use `kotlinx.uuid`, `kotlinx-io`, or `expect`/`actual` |
| Stack overflow in iOS Compose | Often a `LaunchedEffect` recursion or a state read in a tight loop | Profile with Xcode Instruments; isolate the offending composable |
| Slow Wasm | Unoptimized initial bundle | Tree-shake heavy deps, lazy-load secondary screens, profile `.wasm` size |
| Android build OK, iOS link fails with `Undefined symbol` | Cinterop misconfigured or Swift bridge header missing from build phase | Re-run `./gradlew :composeApp:cinteropProcess` and verify `.def` paths |
| Compose composable looks correct on Android but blank on iOS | Often a missing `Modifier.fillMaxSize()` at the root, or a `Box` with no constraints | Add explicit size; iOS doesn't infer size from parent the same way Android does in some edge cases |
| Fonts work on Android but not iOS | Font file copied to wrong resources folder, or font name typo | Drop fonts in `commonMain/composeResources/font/`; verify the generated `Res.font.X` accessor matches the file name |

---

## Sources

- [JetBrains CMP release notes](https://github.com/JetBrains/compose-multiplatform/blob/master/CHANGELOG.md)
- [Meet-Miyani/compose-skill](https://github.com/Meet-Miyani/compose-skill) (platform quirks section)
- [JetBrains CMP iOS interop](https://www.jetbrains.com/help/kotlin-multiplatform-dev/compose-uikit-integration.html)
- [Skiko (Skia for Kotlin)](https://github.com/JetBrains/skiko)
