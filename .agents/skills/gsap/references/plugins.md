# GSAP Plugins

## SplitText (Free since v3.12)

Splits text into `chars`, `words`, `lines` for granular animations.

### Usage

```js
import { SplitText } from "gsap/SplitText";
gsap.registerPlugin(SplitText);

const split = SplitText.create(".headline", {
  type: "chars, words, lines",
  mask: "lines",       // masks lines (clip overflow for reveal)
  linesClass: "line",
  charsClass: "char",
  wordsClass: "word",
});

// Animate chars
gsap.from(split.chars, {
  y: 50,
  opacity: 0,
  stagger: 0.03,
  duration: 0.6,
  ease: "power3.out",
});
```

### autoSplit + onSplit (v3.13+)

Automatic re-split on resize (when lines change).

```js
SplitText.create(".text", {
  type: "lines, words",
  mask: "lines",
  autoSplit: true, // re-split au resize
  onSplit(self) {
    return gsap.from(self.words, {
      y: "100%",
      opacity: 0,
      stagger: 0.04,
      duration: 0.7,
    });
    // Returning the tween allows autoSplit to kill/recreate it
  },
});
```

### Revert

Always revert after animation to clean up the DOM.

```js
// BAD — spans remain in the DOM indefinitely
const split = SplitText.create(".text", { type: "chars" });
gsap.from(split.chars, { opacity: 0 });

// GOOD — revert when the animation is finished
const split = SplitText.create(".text", { type: "chars" });
gsap.from(split.chars, {
  opacity: 0,
  stagger: 0.02,
  onComplete: () => split.revert(),
});
// OR use autoSplit + onSplit which handles the cycle automatically
```

## Flip

Animates layout changes (position, size) with a smooth transition. FLIP technique: First, Last, Invert, Play.

### Usage

```js
import { Flip } from "gsap/Flip";
gsap.registerPlugin(Flip);

// 1. Capture the current state
const state = Flip.getState(".items");

// 2. Modify the DOM / layout
container.appendChild(movedElement);
// or toggle a class, reorder, etc.

// 3. Animate from the old state to the new one
Flip.from(state, {
  duration: 0.8,
  ease: "power2.inOut",
  stagger: 0.05,
  absolute: true,      // uses position absolute during the animation
  onEnter: (elements) => gsap.fromTo(elements, { opacity: 0, scale: 0 }, { opacity: 1, scale: 1 }),
  onLeave: (elements) => gsap.to(elements, { opacity: 0, scale: 0 }),
});
```

### Flip.fit()

Matches the size/position of one element to another.

```js
// Makes .box match the position/size of .target
Flip.fit(".box", ".target", {
  scale: true,     // uses scale instead of width/height
  duration: 0.5,
});
```

### Flip pitfall

```js
// BAD — getState AFTER the DOM change = no reference
container.appendChild(element);
const state = Flip.getState(".items"); // TOO LATE

// GOOD — getState BEFORE the change
const state = Flip.getState(".items");
container.appendChild(element);
Flip.from(state, { duration: 0.6 });
```

## MorphSVG (Club)

Morphs one SVG path into another.

### Usage

```js
import { MorphSVGPlugin } from "gsap/MorphSVGPlugin";
gsap.registerPlugin(MorphSVGPlugin);

gsap.to("#circle", {
  morphSVG: "#star",     // target shape (selector or path data)
  duration: 1.5,
  ease: "power2.inOut",
});

// With path data string
gsap.to("#shape", {
  morphSVG: "M10,10 C20,20 40,20 50,10",
  duration: 1,
});
```

### findShapeIndex

Interactive tool to find the best starting point for the morph.

```js
// Dev only — opens an interactive tool
MorphSVGPlugin.findShapeIndex("#circle", "#star");
```

### Convert primitives to path

```js
// Converts rect, circle, ellipse, polygon, polyline, line to <path>
MorphSVGPlugin.convertToPath("circle, rect, ellipse");
```

### MorphSVG pitfall

```js
// BAD — morph between shapes with very different point counts = chaotic result
gsap.to("#simple-circle", { morphSVG: "#complex-illustration" });

// GOOD — use shapes with similar complexity, or shapeIndex to optimize
gsap.to("#simple-circle", {
  morphSVG: { shape: "#complex-shape", shapeIndex: 2 }, // test with findShapeIndex
});
```

## DrawSVG (Club)

Animates an SVG stroke (drawing effect).

### Usage

```js
import { DrawSVGPlugin } from "gsap/DrawSVGPlugin";
gsap.registerPlugin(DrawSVGPlugin);

// Draws the stroke from 0% to 100%
gsap.from(".path", { drawSVG: 0, duration: 2, ease: "power2.inOut" });

// Animate a portion of the stroke
gsap.fromTo(".path",
  { drawSVG: "0% 0%" },
  { drawSVG: "0% 100%", duration: 2 }
);

// Moving portion
gsap.to(".path", { drawSVG: "50% 60%", duration: 1 });

// Timeline for "snake" effect
const tl = gsap.timeline({ repeat: -1 });
tl.fromTo(".path",
  { drawSVG: "0% 0%" },
  { drawSVG: "0% 30%", duration: 1 }
).to(".path",
  { drawSVG: "100% 100%", duration: 1 }
);
```

### DrawSVG pitfall

```js
// BAD — the element has no stroke defined in CSS/SVG
gsap.from(".path", { drawSVG: 0 }); // nothing happens

// GOOD — always define a visible stroke
// CSS: .path { stroke: #fff; stroke-width: 2; fill: none; }
gsap.from(".path", { drawSVG: 0, duration: 2 });
```

## MotionPath (Free)

Animates an element along an SVG path.

### Usage

```js
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
gsap.registerPlugin(MotionPathPlugin);

gsap.to(".rocket", {
  motionPath: {
    path: "#flight-path",    // SVG path to follow
    align: "#flight-path",   // aligns the element on the path
    alignOrigin: [0.5, 0.5], // center of the element
    autoRotate: true,         // rotates in the direction of movement
    autoRotate: 90,           // rotation offset in degrees
    start: 0,                 // start position (0-1)
    end: 1,                   // end position (0-1)
  },
  duration: 3,
  ease: "power1.inOut",
});
```

### Path with coordinates

```js
gsap.to(".ball", {
  motionPath: {
    path: [
      { x: 100, y: 0 },
      { x: 200, y: -100 },
      { x: 300, y: 0 },
    ],
    curviness: 1.5,   // 0 = linear, 2 = very curved
    autoRotate: true,
  },
  duration: 2,
});
```

### MotionPath pitfall

```js
// BAD — autoRotate without alignOrigin = the element rotates around its corner
gsap.to(".el", {
  motionPath: { path: "#path", autoRotate: true },
});

// GOOD — always define align + alignOrigin with autoRotate
gsap.to(".el", {
  motionPath: {
    path: "#path",
    align: "#path",
    alignOrigin: [0.5, 0.5],
    autoRotate: true,
  },
});
```

## Observer (Free)

Detects user gestures (scroll, touch, pointer) without ScrollTrigger. Ideal for custom interactions (swipe, drag-to-reveal).

### Usage

```js
import { Observer } from "gsap/Observer";
gsap.registerPlugin(Observer);

Observer.create({
  type: "wheel, touch, pointer",  // event types to listen to
  target: window,                  // target element
  onUp: () => goToSection(-1),     // scroll/swipe up
  onDown: () => goToSection(1),    // scroll/swipe down
  tolerance: 50,                   // minimum pixels before triggering
  preventDefault: true,            // prevents native scroll
  wheelSpeed: -1,                  // inverts wheel direction
  onPress: (self) => {},           // pointer down
  onRelease: (self) => {},         // pointer up
  onDrag: (self) => {},            // during drag
  onChange: (self) => {
    self.deltaX;    // X displacement
    self.deltaY;    // Y displacement
    self.velocityX; // X velocity
    self.velocityY; // Y velocity
  },
});
```

### Full-page section transitions

```js
let currentIndex = 0;
const sections = gsap.utils.toArray(".section");
let animating = false;

function goToSection(direction) {
  if (animating) return;
  const nextIndex = gsap.utils.clamp(0, sections.length - 1, currentIndex + direction);
  if (nextIndex === currentIndex) return;

  animating = true;
  gsap.to(sections[currentIndex], { yPercent: -100 * direction, duration: 0.8 });
  gsap.fromTo(sections[nextIndex],
    { yPercent: 100 * direction },
    { yPercent: 0, duration: 0.8, onComplete: () => (animating = false) }
  );
  currentIndex = nextIndex;
}

Observer.create({
  type: "wheel, touch",
  onUp: () => goToSection(-1),
  onDown: () => goToSection(1),
  tolerance: 80,
  preventDefault: true,
});
```

### Observer pitfall

```js
// BAD — no debounce/lock = animations stacking up
Observer.create({
  onDown: () => gsap.to(".box", { y: "+=100" }), // each scroll adds 100px

// GOOD — lock during animation
let animating = false;
Observer.create({
  onDown: () => {
    if (animating) return;
    animating = true;
    gsap.to(".box", { y: "+=100", onComplete: () => (animating = false) });
  },
});
```

## Recap : Free vs Club

| Plugin         | Licence | Usage principal                    |
| -------------- | ------- | ---------------------------------- |
| ScrollTrigger  | Free    | Scroll-driven animations           |
| Observer       | Free    | Gesture detection                  |
| MotionPath     | Free    | Path following                     |
| Flip           | Free    | Layout transitions                 |
| SplitText      | Free    | Text splitting (free since v3.12)  |
| MorphSVG       | Club    | SVG shape morphing                 |
| DrawSVG        | Club    | SVG stroke animation               |
| CustomEase     | Free    | Custom easing curves               |
| ScrollSmoother | Club    | Smooth scrolling wrapper           |
