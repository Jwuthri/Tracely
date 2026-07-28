# Framer Motion — API Reference

> `motion` v11+ — `import { motion, AnimatePresence, ... } from "motion/react"`

## motion component — Props

### Animation

| Prop | Type | Description |
|------|------|-------------|
| `initial` | `Target \| VariantLabel \| false` | Initial state. `false` = no animation on mount (starts directly from `animate`) |
| `animate` | `Target \| VariantLabel` | Target state. Change = animates automatically |
| `exit` | `Target \| VariantLabel` | Exit animation (requires parent `AnimatePresence`) |
| `transition` | `Transition` | Transition config (duration, ease, type, delay...) |
| `variants` | `Variants` | Map of labels to targets. Propagate to motion children |

### Gesture props

| Prop | Type | Description |
|------|------|-------------|
| `whileHover` | `Target \| VariantLabel` | Animates during hover |
| `whileTap` | `Target \| VariantLabel` | Animates during press/tap |
| `whileFocus` | `Target \| VariantLabel` | Animates during focus |
| `whileDrag` | `Target \| VariantLabel` | Animates during drag |
| `whileInView` | `Target \| VariantLabel` | Animates when visible in the viewport |

### Drag

| Prop | Type | Description |
|------|------|-------------|
| `drag` | `boolean \| "x" \| "y"` | Enables drag. `true` = both axes |
| `dragConstraints` | `{ top, left, right, bottom } \| RefObject` | Drag limits. Ref = a parent element |
| `dragElastic` | `number \| { top, left, right, bottom }` | Elasticity outside constraints (0-1, default 0.35) |
| `dragMomentum` | `boolean` | Inertia after release (default true) |
| `dragSnapToOrigin` | `boolean` | Returns to initial position after release |
| `dragTransition` | `InertiaTransition` | Inertia transition config |
| `dragPropagation` | `boolean` | Propagates drag to draggable parents |
| `onDrag` | `(event, info: PanInfo) => void` | Callback during drag |
| `onDragStart` | `(event, info: PanInfo) => void` | Callback at drag start |
| `onDragEnd` | `(event, info: PanInfo) => void` | Callback at drag end |
| `onDirectionLock` | `(axis: "x" \| "y") => void` | Callback when direction is locked |

### Layout

| Prop | Type | Description |
|------|------|-------------|
| `layout` | `boolean \| "position" \| "size" \| "preserve-aspect"` | Automatically animates layout changes |
| `layoutId` | `string` | Shared layout — animates between components sharing the same layoutId |
| `layoutDependency` | `any` | Forces a layout recalculation when this value changes |
| `layoutScroll` | `boolean` | Compensates scroll offset in layout calculations |
| `onLayoutAnimationStart` | `() => void` | Callback at layout animation start |
| `onLayoutAnimationComplete` | `() => void` | Callback at layout animation end |

### Lifecycle callbacks

| Prop | Type | Description |
|------|------|-------------|
| `onAnimationStart` | `(definition) => void` | When an animation starts |
| `onAnimationComplete` | `(definition) => void` | When an animation ends |
| `onUpdate` | `(latest: ResolvedValues) => void` | On each frame during animation |
| `onViewportEnter` | `(entry) => void` | When the element enters the viewport |
| `onViewportLeave` | `(entry) => void` | When the element leaves the viewport |

### Style (MotionValue-compatible)

The `style` prop accepts `MotionValue` in addition to normal values:

```tsx
const x = useMotionValue(0);
<motion.div style={{ x, opacity: 0.5 }} />
```

**Independent transforms** supported in `style`: `x`, `y`, `z`, `rotateX`, `rotateY`, `rotateZ`, `scale`, `scaleX`, `scaleY`, `skewX`, `skewY`.

## AnimatePresence — Props

| Prop | Type | Description |
|------|------|-------------|
| `mode` | `"sync" \| "wait" \| "popLayout"` | Enter/exit behavior. Default `"sync"` |
| `initial` | `boolean` | `false` = disables initial animations of children on first render |
| `onExitComplete` | `() => void` | Callback when all exit animations are finished |
| `custom` | `any` | Value passed to dynamic `exit` variants |
| `presenceAffectsLayout` | `boolean` | Does the exiting element still affect layout (default true) |

### Mode details

- **`sync`** (default) — enter and exit simultaneously
- **`wait`** — waits for exit to finish before starting enter (page transitions)
- **`popLayout`** — removes the element from flow immediately via `position: absolute`, starts enter during exit

## Transition — Configuration

```tsx
// Spring (default for physical values)
transition={{ type: "spring", stiffness: 300, damping: 30, mass: 1 }}

// Tween (default for opacity, color)
transition={{ type: "tween", duration: 0.3, ease: "easeInOut" }}

// Inertia (for drag momentum)
transition={{ type: "inertia", velocity: 200, power: 0.8 }}

// Per-value
transition={{
  x: { type: "spring", stiffness: 300 },
  opacity: { duration: 0.2 },
}}

// Orchestration in variants
transition={{
  staggerChildren: 0.08,
  delayChildren: 0.2,
  staggerDirection: -1,       // reverse
  when: "beforeChildren",     // or "afterChildren"
}}
```

### Ease presets

`"linear"`, `"easeIn"`, `"easeOut"`, `"easeInOut"`, `"circIn"`, `"circOut"`, `"circInOut"`, `"backIn"`, `"backOut"`, `"backInOut"`, `"anticipate"`

Cubic bezier: `ease: [0.25, 0.1, 0.25, 1.0]`

## Hooks

### useMotionValue

```tsx
const x = useMotionValue(0);
// Set without re-render
x.set(100);
// Read current value
x.get(); // 100
// Bind to style
<motion.div style={{ x }} />
```

Creates a reactive value that updates the DOM without React re-render. Foundation of all other hooks.

### useTransform

```tsx
// Map a value to another
const opacity = useTransform(x, [-200, 0, 200], [0, 1, 0]);

// Transform with a function
const rounded = useTransform(x, (latest) => Math.round(latest));

// Combine multiple values
const combined = useTransform([x, y], ([latestX, latestY]) => latestX + latestY);
```

Derives a `MotionValue` from one or more others. Recalculated on each source change.

### useSpring

```tsx
const springX = useSpring(motionValue, {
  stiffness: 300,   // default 100
  damping: 30,      // default 10
  mass: 1,          // default 1
  restSpeed: 0.01,
  restDelta: 0.01,
});

// With initial value (number)
const spring = useSpring(0);
spring.set(100); // animates to 100 with spring physics
```

Creates a spring that follows a `MotionValue` or a number. Ideal for smooth scroll indicators, cursor followers.

### useScroll

```tsx
// Page scroll
const { scrollX, scrollY, scrollXProgress, scrollYProgress } = useScroll();

// Target element scroll
const ref = useRef(null);
const { scrollYProgress } = useScroll({
  target: ref,
  offset: ["start end", "end start"],
  // offset format: [targetEdge containerEdge]
  // "start end" = when the top of target reaches the bottom of the container
});

// Specific container scroll
const { scrollYProgress } = useScroll({ container: scrollRef });
```

Returns 4 `MotionValue`: absolute position (scrollX/Y) and normalized 0-1 progress (scrollXProgress/YProgress).

**Offset keywords**: `"start"`, `"center"`, `"end"`, or a number/percentage (`0.5`, `"100px"`).

### useAnimate

```tsx
const [scope, animate] = useAnimate();

// Imperative animation
await animate(scope.current, { x: 100, opacity: 1 }, { duration: 0.5 });

// Selectors within the scope
await animate("li", { opacity: 1 }, { delay: stagger(0.1) });

// Sequence
await animate([
  [scope.current, { x: 100 }],
  ["li", { opacity: 1 }, { delay: stagger(0.1) }],
]);

<div ref={scope}>
  <li>...</li>
</div>
```

Imperative API for complex animations, sequences, and dynamic orchestrations. Alternative to variants when logic is too dynamic.

### useInView

```tsx
const ref = useRef(null);
const isInView = useInView(ref, {
  once: true,          // triggers only once
  amount: 0.5,         // 50% visible (default "some")
  margin: "-100px",    // rootMargin (like IntersectionObserver)
});

// Usage with animate
<motion.div
  ref={ref}
  initial={{ opacity: 0, y: 50 }}
  animate={isInView ? { opacity: 1, y: 0 } : {}}
/>
```

Wrapper around `IntersectionObserver`. Returns a reactive boolean.

### useReducedMotion

```tsx
const prefersReduced = useReducedMotion();

<motion.div
  animate={prefersReduced ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
  transition={prefersReduced ? { duration: 0 } : { type: "spring" }}
/>
```

Respects `prefers-reduced-motion`. **Always use it** for non-essential animations. Returns `true` if the user has enabled the system preference.

### useMotionValueEvent

```tsx
const x = useMotionValue(0);

useMotionValueEvent(x, "change", (latest) => {
  console.log("x changed to", latest);
});

useMotionValueEvent(x, "animationStart", () => { /* ... */ });
useMotionValueEvent(x, "animationComplete", () => { /* ... */ });
useMotionValueEvent(x, "animationCancel", () => { /* ... */ });
```

Subscribes to a MotionValue without re-render. Auto-cleanup on unmount. Prefer over `onChange` (deprecated).

## Utilities

### stagger

```tsx
import { stagger } from "motion/react";

animate("li", { opacity: 1 }, { delay: stagger(0.1) });
animate("li", { opacity: 1 }, { delay: stagger(0.1, { startDelay: 0.2 }) });
animate("li", { opacity: 1 }, { delay: stagger(0.1, { from: "center" }) });
// from: number | "first" | "center" | "last"
```

### animate (standalone)

```tsx
import { animate } from "motion/react";

// Animate a value
animate(0, 100, {
  duration: 1,
  onUpdate: (latest) => el.style.opacity = latest,
});

// Animate an element directly (outside React)
animate(element, { opacity: 1 }, { duration: 0.5 });
```

### scroll (standalone)

```tsx
import { scroll } from "motion";

// Callback based on scroll progress
scroll((progress) => {
  el.style.opacity = progress;
});

// Bind to an element's scroll
scroll(
  (progress) => { /* ... */ },
  { target: element, offset: ["start end", "end start"] }
);
```
