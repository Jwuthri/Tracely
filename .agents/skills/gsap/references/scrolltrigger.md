# ScrollTrigger

## Setup

```js
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
gsap.registerPlugin(ScrollTrigger);
```

## Basic syntax

### On a tween

```js
gsap.to(".box", {
  x: 200,
  scrollTrigger: {
    trigger: ".box",    // trigger element
    start: "top center", // when the TOP of the trigger reaches the CENTER of the viewport
    end: "bottom center",
    toggleActions: "play none none none",
  },
});
```

### On a timeline

```js
const tl = gsap.timeline({
  scrollTrigger: {
    trigger: ".section",
    start: "top top",
    end: "+=1000",
    pin: true,
    scrub: 1,
  },
});
tl.to(".a", { x: 200 }).to(".b", { y: -100 }, "<");
```

### Standalone (without tween)

```js
ScrollTrigger.create({
  trigger: ".section",
  start: "top center",
  end: "bottom center",
  onEnter: () => console.log("enter"),
  onLeave: () => console.log("leave"),
  toggleClass: "active",
});
```

## Properties

### trigger

Element or selector that defines the trigger zone.

```js
trigger: ".my-section"   // CSS selector
trigger: elementRef       // DOM element
```

### start / end

Format : `"triggerPoint viewportPoint"`.

Possible values for each point: `top`, `center`, `bottom`, percentage (`80%`), pixels (`200px`), or function.

```js
start: "top center"        // top of trigger = center of viewport
start: "top 80%"           // top of trigger = 80% of viewport (from top)
start: "top top+=100"      // top of trigger = top of viewport + 100px
end: "bottom top"          // bottom of trigger = top of viewport
end: "+=500"               // 500px after start
end: () => "+=" + el.offsetHeight // dynamic
```

### scrub

Links animation progress to scroll.

```js
scrub: true    // instant (follows scroll exactly)
scrub: 0.5     // smooth with 0.5s catch-up
scrub: 1       // smooth with 1s catch-up (recommended)
scrub: 3       // very smooth, fluid effect
```

### pin

Pins the element for the duration of the ScrollTrigger.

```js
pin: true               // pins the trigger
pin: ".other-element"   // pins another element
pinSpacing: true         // default: adds padding to compensate
pinSpacing: false        // no padding (for overlay effects)
pinReparent: true        // reparents the pin (fixes z-index issues, use with caution)
```

### snap

Snaps progress to specific points after scrolling.

```js
snap: 0.25                // snaps every 25%
snap: [0, 0.25, 0.5, 1]  // snaps to specific points
snap: "labels"            // snaps to timeline labels

// Advanced config
snap: {
  snapTo: "labels",
  duration: { min: 0.2, max: 0.8 },
  delay: 0.1,
  ease: "power1.inOut",
  directional: true,     // snap in the scroll direction
}
```

### toggleActions

Defines behavior at 4 moments: `onEnter`, `onLeave`, `onEnterBack`, `onLeaveBack`.

Possible actions: `play`, `pause`, `resume`, `reset`, `restart`, `complete`, `reverse`, `none`.

```js
toggleActions: "play none none none"     // default
toggleActions: "play pause resume reverse" // classic
toggleActions: "restart none none reset"   // reset on each entry
```

### toggleClass

```js
toggleClass: "active"                           // toggle on the trigger
toggleClass: { targets: ".box", className: "active" } // toggle on other elements
```

### markers

Visual debug. **Remove in production.**

```js
markers: true
markers: { startColor: "green", endColor: "red", fontSize: "12px" }
```

## Callbacks

```js
ScrollTrigger.create({
  trigger: ".section",
  start: "top center",
  end: "bottom center",
  onEnter:     (self) => {},  // scroll down, enters the zone
  onLeave:     (self) => {},  // scroll down, exits the zone
  onEnterBack: (self) => {},  // scroll up, re-enters the zone
  onLeaveBack: (self) => {},  // scroll up, exits from the top
  onUpdate:    (self) => {    // every frame during scrub
    self.progress;    // 0-1
    self.direction;   // 1 (down) or -1 (up)
    self.isActive;    // in the zone?
    self.getVelocity(); // scroll velocity
  },
  onToggle:    (self) => {},  // when isActive changes
  onRefresh:   (self) => {},  // when positions are recalculated
  onScrubComplete: () => {},  // when scrub finishes catching up
});
```

## containerAnimation

Allows creating ScrollTriggers for elements inside a horizontal scroll.

```js
// 1. Create the horizontal scroll
const panels = gsap.utils.toArray(".panel");
const scrollTween = gsap.to(panels, {
  xPercent: -100 * (panels.length - 1),
  ease: "none", // REQUIRED: ease none on the parent tween
  scrollTrigger: {
    trigger: ".panels-container",
    pin: true,
    scrub: 1,
    end: () => "+=" + document.querySelector(".panels-container").scrollWidth,
  },
});

// 2. Animate individual elements within the horizontal scroll
panels.forEach((panel) => {
  gsap.from(panel.querySelector(".content"), {
    opacity: 0,
    y: 50,
    scrollTrigger: {
      trigger: panel,
      containerAnimation: scrollTween, // LINKED to horizontal scroll
      start: "left center",            // horizontal axes!
      end: "center center",
      scrub: true,
    },
  });
});
```

**containerAnimation pitfalls**:
- The parent tween MUST have `ease: "none"`
- start/end use horizontal axes (`left`, `right`, `center`)
- Do NOT put `pin` on child ScrollTriggers
- Do NOT use `snap` on children

## ScrollTrigger.batch()

Animates elements in batches when they enter the viewport. Ideal for grids.

```js
ScrollTrigger.batch(".card", {
  onEnter: (elements, triggers) => {
    gsap.to(elements, {
      opacity: 1,
      y: 0,
      stagger: 0.1,
      overwrite: true,
    });
  },
  onLeave: (elements) => {
    gsap.set(elements, { opacity: 0, y: 30 });
  },
  onEnterBack: (elements) => {
    gsap.to(elements, { opacity: 1, y: 0, stagger: 0.1 });
  },
  start: "top 85%",
  // interval: 0.1, // batching time (default: 0.1s)
});

// Initial setup
gsap.set(".card", { opacity: 0, y: 30 });
```

## matchMedia

Responsive animations with automatic cleanup.

```js
ScrollTrigger.matchMedia({
  // Desktop
  "(min-width: 960px)": function () {
    gsap.to(".box", {
      x: 500,
      scrollTrigger: { trigger: ".section", scrub: true },
    });
    // Everything created here is automatically killed when the media no longer matches
  },

  // Mobile
  "(max-width: 959px)": function () {
    gsap.to(".box", {
      y: 200,
      scrollTrigger: { trigger: ".section", scrub: true },
    });
  },

  // All sizes
  all: function () {
    gsap.to(".always", { opacity: 1 });
  },
});
```

## Refresh

ScrollTrigger recalculates positions on resize. Sometimes you need to force it manually:

```js
// After loading images, dynamic content changes, etc.
ScrollTrigger.refresh();

// Wait for fonts/images to load
ScrollTrigger.refresh(true); // safe mode: waits for the next tick

// Recalculate a single ScrollTrigger
myTrigger.refresh();

// Sort order: controls refresh order
ScrollTrigger.sort(); // sorts by start position (recommended after dynamic additions)
```

## Useful static methods

```js
ScrollTrigger.getAll()                // all active ScrollTriggers
ScrollTrigger.getById("myId")         // by id
ScrollTrigger.killAll()               // destroys all
ScrollTrigger.saveStyles(".box")      // saves styles before matchMedia
ScrollTrigger.scrollerProxy(el, {})   // custom scroller (Locomotive, Lenis)
ScrollTrigger.normalizeScroll(true)   // normalizes touch scroll (anti-overscroll)
ScrollTrigger.config({ limitCallbacks: true }) // optimize perf
```

## Smooth scroll integration (Lenis)

```js
import Lenis from "lenis";

const lenis = new Lenis();
lenis.on("scroll", ScrollTrigger.update);
gsap.ticker.add((time) => lenis.raf(time * 1000));
gsap.ticker.lagSmoothing(0);
```

## Cleanup (React)

```jsx
useGSAP(() => {
  ScrollTrigger.create({
    trigger: sectionRef.current,
    start: "top center",
    onEnter: () => { /* ... */ },
  });
  // useGSAP automatically kills all ScrollTriggers created within the scope
}, { scope: containerRef });
```
