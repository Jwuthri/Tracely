# Easing Guide

Complete reference for easing functions across CSS, GSAP, and Framer Motion.

---

## CSS Easings

### Built-in Keywords

| Keyword | cubic-bezier | When to Use | Feel |
|---|---|---|---|
| `ease` | `(0.25, 0.1, 0.25, 1.0)` | General-purpose default | Smooth, slightly fast start |
| `ease-in` | `(0.42, 0, 1.0, 1.0)` | **Exits only.** Element leaving the screen | Slow start, fast end (accelerating away) |
| `ease-out` | `(0, 0, 0.58, 1.0)` | **Entries.** Element appearing on screen | Fast start, smooth landing |
| `ease-in-out` | `(0.42, 0, 0.58, 1.0)` | State changes (color, position shift) | Symmetric acceleration/deceleration |
| `linear` | `(0, 0, 1.0, 1.0)` | Scroll-synced, progress bars, spinners | Mechanical, constant speed |

### Common cubic-bezier Recipes

| Name | Value | Use Case |
|---|---|---|
| Snappy UI | `cubic-bezier(0.2, 0, 0, 1)` | Modals, drawers, fast UI |
| Material Design Standard | `cubic-bezier(0.4, 0, 0.2, 1)` | General Material transitions |
| Material Decelerate | `cubic-bezier(0, 0, 0.2, 1)` | Entries in Material Design |
| Material Accelerate | `cubic-bezier(0.4, 0, 1, 1)` | Exits in Material Design |
| Apple ease | `cubic-bezier(0.25, 0.1, 0.25, 1)` | iOS-style smooth transitions |
| Vercel/Geist | `cubic-bezier(0.16, 1, 0.3, 1)` | Snappy with soft landing |
| Overshoot | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Playful entries, slight bounce past target |
| Dramatic exit | `cubic-bezier(0.55, 0, 1, 0.45)` | Fast aggressive exit |

```css
/* Example: snappy modal entry */
.modal {
  transition: transform 0.25s cubic-bezier(0.2, 0, 0, 1),
              opacity 0.25s cubic-bezier(0.2, 0, 0, 1);
}
```

### CSS linear() Function

Creates custom easing curves with multiple stops. Useful for spring-like or bounce effects in pure CSS.

```css
/* Spring-like bounce */
.bounce-enter {
  transition: transform 0.5s linear(
    0, 0.004, 0.016, 0.035, 0.063, 0.098, 0.141, 0.191,
    0.25, 0.316, 0.391, 0.473, 0.562, 0.659, 0.763, 0.876,
    1, 1.097, 1.159, 1.185, 1.176, 1.142, 1.092, 1.035,
    0.984, 0.946, 0.925, 0.92, 0.929, 0.946, 0.969, 0.991,
    1.006, 1.015, 1.017, 1.013, 1.006, 1
  );
}
```

> **Tool:** Use [linear-easing-generator.netlify.app](https://linear-easing-generator.netlify.app/) to convert spring configs to `linear()`.

---

## GSAP Easings

GSAP uses string-based easing: `"power2.out"`, `"back.inOut"`, `"elastic.out(1, 0.3)"`.

### Power Easings

| Ease | Intensity | Equivalent CSS | Best For |
|---|---|---|---|
| `power1` (a.k.a. `quad`) | Subtle | Close to `ease` | Subtle UI transitions |
| `power2` (a.k.a. `cubic`) | Medium | Close to `ease-out` | General purpose, entries |
| `power3` (a.k.a. `quart`) | Strong | More aggressive | Dramatic reveals |
| `power4` (a.k.a. `quint`) | Very strong | Very aggressive | Hero animations, impact |
| `none` / `linear` | Zero | `linear` | Scroll-driven |

**Suffix rules:** `.out` = entry, `.in` = exit, `.inOut` = state change.

```js
// Subtle card entry
gsap.from('.card', { opacity: 0, y: 20, duration: 0.4, ease: "power2.out" });

// Dramatic hero reveal
gsap.from('.hero', { opacity: 0, y: 60, duration: 0.8, ease: "power4.out" });
```

### Special Easings

| Ease | Config | Feel | Use Case |
|---|---|---|---|
| `back` | `back.out(1.7)` | Overshoots then settles | Playful entries, modals |
| `bounce` | `bounce.out` | Bounces at the end | Game UI, notifications, playful |
| `elastic` | `elastic.out(1, 0.3)` | Spring-like wobble | Attention-grabbing, fun UI |
| `slow` | `slow(0.7, 0.7, false)` | Slow middle section | Cinematic reveals |
| `steps` | `steps(12)` | Frame-by-frame | Sprite animations, retro |
| `rough` | `rough({ strength: 1, points: 20, ... })` | Shaky/glitchy | Horror, distortion effects |
| `circ` | `circ.out` | Circular motion curve | Natural motion arcs |
| `expo` | `expo.out` | Very fast then very slow | Snappy professional UI |

```js
// Playful notification bounce
gsap.from('.notification', {
  y: -100,
  duration: 0.6,
  ease: "back.out(1.7)"
});

// Elastic attention-grab
gsap.from('.badge', {
  scale: 0,
  duration: 0.8,
  ease: "elastic.out(1, 0.3)"
});

// Cinematic title reveal
gsap.from('.title', {
  opacity: 0,
  y: 40,
  duration: 1.2,
  ease: "expo.out"
});
```

### Custom Ease

```js
// Register a reusable custom ease
gsap.registerEase("mySnap", function(progress) {
  return Math.round(progress * 10) / 10; // Snap to 10 steps
});

gsap.to('.el', { x: 200, ease: "mySnap" });
```

---

## Spring Configs

Springs produce natural, physics-based motion. No fixed duration -- the spring resolves when it reaches equilibrium.

### Framer Motion Springs

Three parameters: `stiffness`, `damping`, `mass`.

| Preset | Stiffness | Damping | Mass | Feel | Use Case |
|---|---|---|---|---|---|
| Snappy UI | 400 | 30 | 1 | Fast, no overshoot | Buttons, toggles, menus |
| Default | 100 | 10 | 1 | Noticeable bounce | General entries |
| Gentle | 120 | 14 | 1 | Soft landing | Cards, modals |
| Bouncy | 600 | 15 | 1 | Strong overshoot | Playful, attention-grab |
| Slow | 50 | 10 | 1 | Sluggish, heavy | Large elements, page transitions |
| Heavy | 200 | 20 | 2 | Weighty, deliberate | Drag-and-drop, physics-sim |

```tsx
// Snappy button
<motion.button
  whileTap={{ scale: 0.97 }}
  transition={{ type: "spring", stiffness: 400, damping: 30 }}
/>

// Bouncy modal entry
<motion.div
  initial={{ opacity: 0, scale: 0.95, y: 10 }}
  animate={{ opacity: 1, scale: 1, y: 0 }}
  transition={{ type: "spring", stiffness: 300, damping: 20 }}
/>

// Gentle card
<motion.div
  initial={{ opacity: 0, y: 20 }}
  animate={{ opacity: 1, y: 0 }}
  transition={{ type: "spring", stiffness: 120, damping: 14 }}
/>
```

**Duration-based spring shorthand:**

```tsx
// Framer Motion also accepts duration + bounce (0 = no bounce, 1 = max bounce)
<motion.div
  transition={{ type: "spring", duration: 0.4, bounce: 0.2 }}
/>
```

### GSAP Spring-like Behavior

GSAP does not have a true spring system, but you can approximate springs:

**Option 1: `elastic` ease**
```js
gsap.from('.el', {
  scale: 0.95,
  opacity: 0,
  duration: 0.8,
  ease: "elastic.out(1, 0.4)" // amplitude, period
});
```

**Option 2: `back` ease (subtle overshoot)**
```js
gsap.from('.el', {
  y: 20,
  opacity: 0,
  duration: 0.5,
  ease: "back.out(1.4)" // overshoot amount
});
```

**Option 3: InertiaPlugin (true physics)**
```js
// Requires InertiaPlugin (Club GSAP)
gsap.to('.el', {
  inertia: {
    x: 500,      // velocity
    resistance: 200
  }
});
```

---

## Decision Matrix: Which Easing When?

| Scenario | CSS | GSAP | Framer Motion |
|---|---|---|---|
| Hover/focus state | `ease-out` or `cubic-bezier(0.2,0,0,1)` | `power2.out` | `type: "tween", ease: "easeOut"` |
| Modal entry | `cubic-bezier(0.16, 1, 0.3, 1)` | `power3.out` or `back.out(1.4)` | `type: "spring", stiffness: 300, damping: 25` |
| Modal exit | `ease-in` or `cubic-bezier(0.4, 0, 1, 1)` | `power2.in` | `type: "tween", ease: "easeIn", duration: 0.15` |
| List stagger | `ease-out` | `power2.out` with `stagger: 0.05` | Spring + `staggerChildren: 0.05` |
| Scroll-driven | `linear` | `none` | N/A (use `useScroll`) |
| Page transition | `cubic-bezier(0.4, 0, 0.2, 1)` | `power2.inOut` | `type: "tween", ease: "easeInOut"` |
| Bounce / playful | `linear(...)` bounce curve | `bounce.out` or `elastic.out` | `type: "spring", stiffness: 600, damping: 15` |
| Drag release | N/A | `power3.out` | `type: "spring", stiffness: 400, damping: 30` |
