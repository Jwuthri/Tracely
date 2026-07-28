---
name: gsap
description: "GSAP animation engine sub-skill - core, timeline, ScrollTrigger, plugins."
---

# GSAP — Animation Engine

## When to use GSAP

| Criteria              | CSS Transitions | Framer Motion | GSAP              |
| --------------------- | --------------- | ------------- | ----------------- |
| Hover / simple toggle | Yes             | Yes           | Overkill          |
| Sequenced timeline    | No              | Limited       | **Yes**           |
| Scroll-driven         | scroll-timeline | Limited       | **ScrollTrigger** |
| Complex stagger       | No              | Basic         | **Distribution**  |
| Mobile perf (60fps)   | Good            | Average       | **Excellent**     |
| Text splitting        | No              | No            | **SplitText**     |
| SVG morph / draw      | No              | No            | **MorphSVG**      |
| Bundle size concern   | 0kb             | ~30kb         | ~25kb + plugins   |

**Rule**: if the animation needs timeline, scroll-link, or distributed stagger, use GSAP. Otherwise CSS first.

## Setup

```js
// Always register plugins at the top level
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";

gsap.registerPlugin(ScrollTrigger, SplitText);
```

React: use `useGSAP()` from the `@gsap/react` package instead of `useEffect` + manual cleanup.

```jsx
import { useGSAP } from "@gsap/react";

useGSAP(() => {
  gsap.to(".box", { x: 200 });
}, { scope: containerRef }); // auto-cleanup, auto-revert
```

## Core Patterns

### defaults{} to avoid repetition

```js
const tl = gsap.timeline({
  defaults: { duration: 0.8, ease: "power2.out" },
});
tl.to(".a", { y: -20 })
  .to(".b", { y: -20 }, "<0.1")
  .to(".c", { y: -20 }, "<0.1");
```

### fromTo for full control

```js
gsap.fromTo(".card", { y: 40, opacity: 0 }, { y: 0, opacity: 1, stagger: 0.15 });
```

### Stagger with distribution

```js
gsap.to(".grid-item", {
  scale: 0,
  stagger: {
    each: 0.05,
    from: "center",   // "start" | "end" | "center" | "edges" | "random" | index
    grid: "auto",      // auto-detects the grid
    axis: "x",         // "x" | "y" | null (both)
  },
});
```

## ScrollTrigger Patterns

### Basic Pin + Scrub

```js
gsap.to(".panel", {
  x: "-300%",
  ease: "none",
  scrollTrigger: {
    trigger: ".container",
    pin: true,
    scrub: 1,
    end: () => "+=" + document.querySelector(".container").scrollWidth,
  },
});
```

### Batch for mass reveal

```js
ScrollTrigger.batch(".card", {
  onEnter: (elements) => gsap.to(elements, { opacity: 1, y: 0, stagger: 0.1 }),
  start: "top 85%",
});
```

### Horizontal scroll with containerAnimation

```js
const scrollTween = gsap.to(".panels", {
  x: () => -(document.querySelector(".panels").scrollWidth - window.innerWidth),
  ease: "none",
  scrollTrigger: { trigger: ".wrapper", pin: true, scrub: 1 },
});

// Animate elements INSIDE the horizontal scroll
gsap.to(".panel-content", {
  scale: 1.2,
  scrollTrigger: {
    trigger: ".panel-content",
    containerAnimation: scrollTween, // linked to horizontal scroll
    start: "left center",
    end: "right center",
    scrub: true,
  },
});
```

## DO NOT — Critical mistakes

### 1. Ease on containerAnimation

```js
// BAD — ease breaks the scroll mapping
scrollTrigger: { containerAnimation: scrollTween, scrub: 1, ease: "power2.out" }

// GOOD — always ease: "none" on the parent tween
const scrollTween = gsap.to(".panels", { x: ..., ease: "none", scrollTrigger: { scrub: 1 } });
```

### 2. ScrollTrigger on a child tween in a timeline

```js
// BAD — ScrollTrigger ignores child tweens of a timeline that has its own ScrollTrigger
const tl = gsap.timeline({ scrollTrigger: { trigger: ".section" } });
tl.to(".box", { x: 100, scrollTrigger: { trigger: ".box" } }); // IGNORE

// GOOD — one ScrollTrigger per timeline OR standalone tweens
gsap.to(".box", { x: 100, scrollTrigger: { trigger: ".box" } }); // tween standalone
```

### 3. setState in onUpdate

```js
// BAD — setState 60x/s = re-render hell
scrollTrigger: { onUpdate: (self) => setProgress(self.progress) }

// GOOD — mutate a ref or DOM element directly
const progressRef = useRef(0);
scrollTrigger: { onUpdate: (self) => { progressRef.current = self.progress; } }
// Or better: gsap.quickSetter to mutate the DOM without React
```

### 4. immediateRender on from() in a timeline

```js
// BAD — from() has immediateRender: true by default, breaks sequencing
tl.to(".box", { x: 100 });
tl.from(".box", { y: 50 }); // visually jumps to the start

// GOOD — disable immediateRender when from() follows another tween
tl.to(".box", { x: 100 });
tl.from(".box", { y: 50, immediateRender: false });
```

### 5. Animating non-transform properties

```js
// BAD — width/height/top/left trigger layout reflow
gsap.to(".box", { width: 200, height: 200 });

// GOOD — use transforms (GPU-accelerated, composited)
gsap.to(".box", { scaleX: 1.5, scaleY: 1.5 });
// If actual size needed: use Flip plugin for layout transition
```

## Refs

- `references/core.md` — Complete gsap.to/from/fromTo/set API, options
- `references/timeline.md` — Timeline, position parameter, nesting
- `references/scrolltrigger.md` — Full ScrollTrigger reference
- `references/plugins.md` — SplitText, Flip, MorphSVG, DrawSVG, MotionPath, Observer
