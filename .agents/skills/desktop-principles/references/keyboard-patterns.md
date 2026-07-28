# Keyboard Patterns Deep Dive

Deep dive on keyboard shortcuts across desktop platforms. Covers canonical bindings, cross-platform detection, chords, conflicts, and discoverability.

---

## Canonical shortcuts by domain

Stick to the conventions users already know. Reinventing `⌘+S` makes your app feel hostile within seconds.

### App lifecycle

| Action | macOS | Windows / Linux |
|---|---|---|
| New | `⌘+N` | `Ctrl+N` |
| Open | `⌘+O` | `Ctrl+O` |
| Save | `⌘+S` | `Ctrl+S` |
| Save As | `⌘+Shift+S` | `Ctrl+Shift+S` |
| Close window | `⌘+W` | `Ctrl+W` or `Alt+F4` |
| Quit app | `⌘+Q` | `Alt+F4` (no global Quit on Windows) |

### Editing

| Action | macOS | Windows / Linux |
|---|---|---|
| Undo | `⌘+Z` | `Ctrl+Z` |
| Redo | `⌘+Shift+Z` | `Ctrl+Y` (or `Ctrl+Shift+Z`) |
| Cut / Copy / Paste | `⌘+X` / `⌘+C` / `⌘+V` | `Ctrl+X` / `Ctrl+C` / `Ctrl+V` |
| Select All | `⌘+A` | `Ctrl+A` |
| Find | `⌘+F` | `Ctrl+F` |
| Replace | `⌘+Option+F` | `Ctrl+H` |

### Navigation

| Action | macOS | Windows / Linux |
|---|---|---|
| Switch tab forward | `⌘+Option+→` | `Ctrl+Tab` |
| New tab | `⌘+T` | `Ctrl+T` |
| Go back | `⌘+[` | `Alt+Left` |
| History | `⌘+Y` | `Ctrl+H` |

### App-specific (creative apps)

| Action | macOS | Windows / Linux |
|---|---|---|
| Command palette | `⌘+K` (or `⌘+Shift+P`) | `Ctrl+K` (or `Ctrl+Shift+P`) |
| Settings / Preferences | `⌘+,` | `Ctrl+,` |
| Toggle sidebar | `⌘+B` | `Ctrl+B` |
| Focus mode | `⌘+.` or `⌘+Shift+F` | `Ctrl+.` or `Ctrl+Shift+F` |

---

## Cross-platform detection

On the web, the modifier is `metaKey` on macOS and `ctrlKey` everywhere else. Detect once, then route every shortcut through a single helper.

```js
// navigator.platform is deprecated but still pragmatic; fall back to userAgent.
const isMac = navigator.platform
  ? navigator.platform.toUpperCase().indexOf('MAC') >= 0
  : /Mac|iPhone|iPad/.test(navigator.userAgent);

window.addEventListener('keydown', (event) => {
  const modKey = isMac ? event.metaKey : event.ctrlKey;
  if (modKey && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    openCommandPalette();
  }
});
```

SwiftUI handles the platform layer for you: `.keyboardShortcut("k", modifiers: [.command])` resolves to `⌘+K` on macOS and to the same physical key combo when an iPad has a hardware keyboard attached. No platform branching needed.

```swift
Button("Command Palette", action: openPalette)
  .keyboardShortcut("k", modifiers: [.command])
```

Compose Desktop exposes `KeyShortcut(Key.K, meta = true, ctrl = false)` for menu items. For raw key handling, branch on `event.isMetaPressed` (macOS) vs `event.isCtrlPressed` (Windows / Linux) by reading `hostOs` from `System.getProperty("os.name")` once at startup.

---

## Chord shortcuts (multi-step)

VS Code popularized chords like `⌘+K, ⌘+S` (open keyboard shortcuts editor). The pattern: a leader combo arms a buffer, the next combo within ~300ms triggers the action, otherwise the buffer resets.

**SwiftUI** does not natively support chord shortcuts. Use `NSEvent.addLocalMonitorForEvents(matching: .keyDown)` on macOS to intercept the leader, then track state in a small coordinator object. Reset the buffer on a `Task.sleep(for: .milliseconds(300))` timeout.

**Web** - maintain a small state machine with a 300ms timeout:

```js
let chordPending = false;
let chordTimer = null;

window.addEventListener('keydown', (event) => {
  const modKey = isMac ? event.metaKey : event.ctrlKey;
  if (modKey && event.key === 'k' && !chordPending) {
    event.preventDefault();
    chordPending = true;
    chordTimer = setTimeout(() => { chordPending = false; }, 300);
    return;
  }
  if (chordPending && modKey && event.key === 's') {
    event.preventDefault();
    clearTimeout(chordTimer);
    chordPending = false;
    openShortcutsEditor();
  }
});
```

**Compose Desktop** - hold a `var pendingLeader: Key?` in your top-level `onKeyEvent` handler, schedule a coroutine to clear it after 300ms, and check it on the next keydown.

---

## Conflicts to avoid

- Don't override OS shortcuts: `⌘+Q`, `⌘+Tab`, `⌘+Space` on macOS, `Alt+Tab`, `Ctrl+Alt+Del`, `Win+L` on Windows. The OS will swallow them anyway, and the user will think your app is broken.
- Don't override browser shortcuts on web (`⌘+L` address bar, `⌘+T` new tab, `⌘+W` close tab) without strong justification. If you must, scope the override to a specific element in focus, never globally.
- Avoid one-letter shortcuts without a modifier (`s` for save, `n` for new). They kill text input the moment a focusable field gains focus, and they clash with browser quick-find (`/` in Firefox).

---

## Discoverability

A shortcut nobody finds is a shortcut nobody uses. Three patterns, layered:

- **In the menu, next to the command.** Native menu APIs (NSMenu, Win32 menus, SwiftUI `MenuBar`, Compose `MenuBar`) render the shortcut on the right side automatically when you bind one. Never hide a primary action from the menu just because it has a shortcut.
- **In a tooltip on hover, after a 1s delay.** Format: `Action name (⌘N)`. The delay matters: instant tooltips feel noisy and trigger on every cursor sweep.
- **A `⌘+?` or `⌘+/` overlay listing every shortcut.** GitHub, Linear, Slack, Figma all use this. Group by domain (App, Editing, Navigation, View) and make the list searchable. Bonus: highlight the user's most-used shortcuts as a learning nudge.

---

## Sources

- macOS keyboard shortcuts (Apple): https://support.apple.com/en-us/HT201236
- Windows keyboard shortcuts (Microsoft): https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec
