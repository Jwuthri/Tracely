# CMP Interop - cross-platform native bridges

Cross-platform interop in Compose Multiplatform spans four directions: Compose hosting native (UIKit, SwiftUI, Android Views, Swing), native hosting Compose (Xcode app embedding `MainViewController`, Android `setContent`), and bidirectional state sharing through KMP types. This file collects the canonical recipes and call-out the build-side wiring that's easy to forget.

---

## iOS interop primitives

| API | Purpose |
|---|---|
| `UIKitView(factory: () -> UIView, modifier: Modifier)` | Drop a UIView into the Compose tree |
| `UIKitViewController(factory: () -> UIViewController, modifier: Modifier)` | Drop a UIViewController into the Compose tree |
| `ComposeUIViewController { content }` | Build a `UIViewController` from a Compose tree, exposed to Swift |
| `LocalUIViewController.current` | Access the host `UIViewController` from inside Compose (for presenting modals) |

To expose a Compose tree to SwiftUI, KMP generates a top-level Kotlin function (commonly `MainViewController()`) which returns a `UIViewController`. Wrap it with `UIViewControllerRepresentable` in Swift.

Lifecycle reminder: a `UIKitView` retains its UIView across recompositions only if the `factory` lambda's identity stays stable. Capturing changing variables in the factory triggers a full UIView rebuild. Use `update = { view -> ... }` to mutate properties of an existing UIView.

---

## Recipe: Compose calling SwiftUI

Goal: drop a SwiftUI `Map` view (rendered natively by MapKit) inside a Compose screen.

```kotlin
// commonMain
@Composable
expect fun NativeMapView(
    coordinates: Pair<Double, Double>,
    modifier: Modifier = Modifier
)

// iosMain
@Composable
actual fun NativeMapView(
    coordinates: Pair<Double, Double>,
    modifier: Modifier
) {
    UIKitViewController(
        factory = {
            // SwiftUIBridge is exposed via the Swift framework
            SwiftUIBridge.makeMapController(
                lat = coordinates.first,
                lon = coordinates.second
            )
        },
        modifier = modifier
    )
}

// androidMain - fallback to a Compose Map or a no-op
@Composable
actual fun NativeMapView(
    coordinates: Pair<Double, Double>,
    modifier: Modifier
) {
    // Use Google Maps Compose or a placeholder
    Box(modifier.background(Color.LightGray)) {
        Text("Map unavailable on this target")
    }
}
```

Swift side:

```swift
// SwiftUIBridge.swift (in iosApp Xcode target)
import SwiftUI
import MapKit

@objc public class SwiftUIBridge: NSObject {
    @objc public static func makeMapController(lat: Double, lon: Double) -> UIViewController {
        let region = MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: lat, longitude: lon),
            span: MKCoordinateSpan(latitudeDelta: 0.05, longitudeDelta: 0.05)
        )
        return UIHostingController(rootView: Map(coordinateRegion: .constant(region)))
    }
}
```

Build wiring (`build.gradle.kts` of the `composeApp` module):

```kotlin
kotlin {
    listOf(iosX64(), iosArm64(), iosSimulatorArm64()).forEach { target ->
        target.compilations.getByName("main") {
            cinterops {
                val swiftBridge by creating {
                    defFile(project.file("src/iosMain/swiftBridge.def"))
                }
            }
        }
    }
}
```

`swiftBridge.def`:

```
language = Objective-C
headers = SwiftUIBridge.h
package = bridge.swiftui
```

The Swift class needs `@objc` and a generated header (Xcode auto-generates `ProductName-Swift.h`). The Kotlin import becomes `import bridge.swiftui.SwiftUIBridge`.

---

## Recipe: SwiftUI hosting Compose

Goal: a SwiftUI app that uses a Compose screen as one tab among native SwiftUI tabs.

```kotlin
// iosMain/kotlin/main.ios.kt
fun MainViewController(): UIViewController = ComposeUIViewController {
    AppContent()
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

@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                NativeHomeView()
                    .tabItem { Label("Home", systemImage: "house") }

                ComposeContent()
                    .ignoresSafeArea()
                    .tabItem { Label("Studio", systemImage: "wand.and.stars") }

                SettingsView()
                    .tabItem { Label("Settings", systemImage: "gear") }
            }
        }
    }
}
```

Tip: `ignoresSafeArea()` is usually right because Compose handles its own safe-area insets via `WindowInsets.safeDrawing`. If you wrap inside SwiftUI containers that add their own padding, you'll get double insets.

---

## Android interop primitives

| API | Purpose |
|---|---|
| `AndroidView(factory: (Context) -> View, modifier: Modifier)` | Drop a legacy Android View into Compose |
| `AndroidViewBinding<T>(...)` | Drop a ViewBinding-generated layout into Compose |
| `setContent { ... }` in Activity | Compose root inside a legacy Activity |
| `ComposeView` (legacy XML) | Embed a Compose subtree inside an XML layout |

Going the other direction (Compose embedded in a Fragment-based legacy app):

```kotlin
class LegacyFragment : Fragment() {
    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View = ComposeView(requireContext()).apply {
        setViewCompositionStrategy(ViewCompositionStrategy.DisposeOnViewTreeLifecycleDestroyed)
        setContent {
            AppContent()  // commonMain composable
        }
    }
}
```

The `ViewCompositionStrategy` matters: `DisposeOnViewTreeLifecycleDestroyed` is the safe default for Fragments and prevents memory leaks tied to the Activity outliving the View.

---

## Desktop interop

Compose Desktop runs on the JVM and has full access to Java/Swing/AWT/JavaFX.

```kotlin
// desktopMain
@Composable
fun MapDesktop() {
    SwingPanel(
        factory = {
            JFXPanel().apply {
                Platform.runLater {
                    scene = Scene(WebView().apply { engine.load("https://maps.example") })
                }
            }
        },
        modifier = Modifier.fillMaxSize()
    )
}
```

`SwingPanel` is the desktop equivalent of `UIKitView` / `AndroidView`. JavaFX integration via `JFXPanel` is the canonical bridge for things like `WebView` or hardware video playback.

---

## Web (Wasm) interop

```kotlin
// wasmJsMain
external fun alert(message: String)

@JsName("renderChart")
external fun renderChart(canvasId: String, data: JsArray<JsNumber>)

@Composable
fun WebOnlyChart(data: List<Double>) {
    DisposableEffect(data) {
        renderChart("chart-canvas", data.toJsArray())
        onDispose { /* tear down JS chart */ }
    }
}
```

DOM injection via `kotlinx.browser.document.body?.appendChild(...)` is rare; usually unnecessary because Compose Wasm renders to a single `<canvas>`. If you need HTML next to the canvas (SEO, video element, native form), structure your `index.html` with adjacent containers and use Compose for the canvas portion only.

---

## Communication patterns (state shared between Compose and native)

The cleanest pattern is a shared ViewModel layer in `commonMain` exposing `MutableStateFlow` / `SharedFlow` / `Channel`. Both Compose and SwiftUI / native UIKit can observe a `Flow`.

```kotlin
// commonMain
class CounterViewModel {
    private val _count = MutableStateFlow(0)
    val count: StateFlow<Int> = _count.asStateFlow()

    fun increment() { _count.value += 1 }
}
```

Compose side:

```kotlin
@Composable
fun CounterScreen(vm: CounterViewModel) {
    val count by vm.count.collectAsState()
    Button(onClick = vm::increment) { Text("Count: $count") }
}
```

Swift side (using KMP's generated bindings via `Skie` or hand-rolled `Flow` -> `AsyncSequence`):

```swift
struct CounterView: View {
    @State private var count: Int32 = 0
    let vm = CounterViewModel()

    var body: some View {
        Button("Count: \(count)") { vm.increment() }
            .task {
                for await value in vm.count {
                    count = value as? Int32 ?? 0
                }
            }
    }
}
```

The `Skie` Gradle plugin (Touchlab) generates idiomatic Swift wrappers for KMP types - `StateFlow<Int>` becomes `AsyncSequence<Int>`, sealed classes become Swift enums, suspend functions become `async` functions. Without Skie you get raw `KotlinInt` and `Kotlinx_coroutines_coreFlow` types that need manual bridging.

For one-shot events (snackbar trigger, navigation event), use `SharedFlow` (replay = 0) or a `Channel` with `Channel.RENDEZVOUS`.

---

## Sources

- [JetBrains CMP iOS interop](https://www.jetbrains.com/help/kotlin-multiplatform-dev/compose-uikit-integration.html)
- [Meet-Miyani/compose-skill](https://github.com/Meet-Miyani/compose-skill)
- [Touchlab Skie](https://skie.touchlab.co/) (Swift bindings for KMP)
- [Kotlinx coroutines Flow](https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines.flow/)
