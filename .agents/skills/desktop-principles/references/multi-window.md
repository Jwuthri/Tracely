# Multi-Window Deep Dive

Deep dive on multi-window architectures across desktop platforms. Covers when to split UI into multiple windows, how to wire them in SwiftUI and Compose Desktop, how to share state, and the lifecycle pitfalls each platform hides.

---

## When to use multiple windows

Multi-window is not free: each window doubles your state surface, your testing matrix, and your "where did I put that panel" surface area. Reach for it only when one of these scenarios actually fits.

### Document-based apps

Each open document is its own window with its own undo stack, dirty state, and title. Pages, Numbers, Xcode, Figma desktop. The mental model is "one window = one thing I'm editing", and tabs would conflate documents that should stay independent. Closing one window must not lose the others, and `⌘+W` should close just that document.

### Long-running secondary task

Export progress, terminal output, render preview, log tail. The user wants to keep watching it while continuing to work in the main window. Forcing this into a sheet or a panel kills the parallelism. Bonus: a secondary window can survive on a second monitor while the main window stays focused on the canvas.

### Companion / inspector windows

Floating palettes, a properties panel, a color picker, a debugger. Secondary tools the power user wants visible without stealing canvas space. They live above the main window, often on a second monitor, and they are summoned by a shortcut or a menu item rather than appearing on launch.

If none of those fit, prefer a tab, a sidebar, or a modal sheet. Adding a window because "it could be useful" is how you end up with seven floating panels nobody can find again.

---

## SwiftUI multi-window

SwiftUI exposes windows as `Scene`s. `WindowGroup` is for primary content (one per document or one per app), `Window` is for singletons like inspectors. Open them imperatively with `@Environment(\.openWindow)`.

```swift
@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
        Window("Inspector", id: "inspector") { InspectorView() }
            .windowResizability(.contentSize)
    }
}

// Then in any view:
@Environment(\.openWindow) var openWindow
Button("Open Inspector") { openWindow(id: "inspector") }
```

`.windowResizability(.contentSize)` sizes the window to fit its content and locks resizing to the intrinsic size. Use it for inspectors and palettes. Use `.automatic` (the default) for editable canvases. Pair the `id` with `openWindow(id:value:)` if you need to pass a payload (a document ID, a selected entity), and SwiftUI will reuse an existing window if one already matches that id + value pair.

---

## Compose Desktop multi-window

Compose Desktop models windows as composables inside the `application` block. Each `Window` call adds one to the OS, and removing it from the composition closes it. State for "is this window open" lives in a `remember` or a `MutableState` higher up.

```kotlin
fun main() = application {
    var inspectorOpen by remember { mutableStateOf(false) }
    Window(onCloseRequest = ::exitApplication, title = "Main") {
        Button(onClick = { inspectorOpen = true }) { Text("Open Inspector") }
    }
    if (inspectorOpen) {
        Window(onCloseRequest = { inspectorOpen = false }, title = "Inspector") {
            InspectorContent()
        }
    }
}
```

The `application` block stays alive as long as at least one window is composed. `::exitApplication` on the main window ensures closing it shuts the whole app down, while the inspector just flips its boolean and disappears. Use `rememberWindowState(size = ..., position = ...)` to persist size and position between launches, otherwise every reopen starts at the default top-left corner.

---

## State sharing patterns

Two windows looking at the same data must never disagree. Pick one of these patterns and stick with it across the whole app.

- **Singleton model.** A top-level `object` (Kotlin) or a `static let shared` (Swift) holding observable state. Simplest to wire, fine for small apps and prototypes. Falls apart the moment you need scoped lifetimes or unit tests with isolated state.
- **DI container.** Koin or Hilt for Compose, an `ObservableObject` exposed via `.environmentObject(...)` for SwiftUI. The container owns lifetimes, you inject the model into each window's root composable / view. This scales to multi-document apps where each window needs its own scoped instance.
- **Shared `@Observable` class injected via `.environment(...)`.** SwiftUI iOS 17+ / macOS 14+ approach. Mark the model `@Observable`, attach it once at the `App` level with `.environment(model)`, read it in any window with `@Environment(MyModel.self) var model`. Cleaner than `@EnvironmentObject` and avoids the published-property boilerplate.

Whichever you pick, write down the rule "secondary windows never own primary state". Inspectors observe and edit the model held by the document window, they do not hold the canonical copy. That way closing an inspector never loses work.

---

## Window lifecycle gotchas

Each platform fires lifecycle events at moments that are easy to get wrong, and the wrong hook means autosave fires twice or never at all.

- **SwiftUI**: use `Scene.onChange(of: scenePhase)` to react to active / inactive / background transitions. `.onAppear` fires once when the view shows up but does not fire again when the user clicks back into a window from another app. For "save on focus loss", you want `scenePhase`, not `onDisappear`.
- **Compose Desktop**: `LifecycleEventObserver` is an Android lifecycle API and does **not** apply to Compose Desktop. Use the `WindowState` returned by `rememberWindowState()` to observe size and position, and a `LaunchedEffect(windowState.isMinimized)` (or `.placement`) for transitions. There is no `onResume` / `onPause` equivalent: model focus and visibility yourself.
- **Web**: there is no real multi-window unless you call `window.open(...)`, and that is usually a popup blocker fight. Most "secondary windows" on web should actually be a side panel, a modal, or a separate tab the user opens deliberately. If you truly need a popout (a presenter view, a dedicated player), gate it behind a user gesture and handle the `null` return from `window.open` gracefully.

Across all three platforms: persist window size, position, and "was open at last quit" state to disk. Restoring exactly the layout the user left is the single biggest quality signal a multi-window app gives.

One more cross-platform trap: a window saved at coordinates `(3000, 1200)` on a second monitor will reopen offscreen if the user unplugs that monitor. Always clamp restored positions to the current screen list before applying them.

- SwiftUI: enumerate `NSScreen.screens` and clamp manually before passing to `.defaultPosition(...)`.
- Compose Desktop: `Toolkit.getDefaultToolkit().screenSize` plus `GraphicsEnvironment.getLocalGraphicsEnvironment().screenDevices` for the multi-monitor case.
- Web: there is no public API to get all monitors, but `window.screen.availWidth / availHeight` at least lets you keep popouts on the active screen.

---

## Sources

- Apple multi-window (`Scene`): https://developer.apple.com/documentation/swiftui/scene
- JetBrains Compose Desktop window management: https://www.jetbrains.com/help/kotlin-multiplatform-dev/compose-desktop-window-management.html
