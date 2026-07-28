# Enter/Exit Recipes

Copy-paste recipes in CSS, Framer Motion, and GSAP.
Each recipe includes the BAD pattern (enter without exit) and the GOOD pattern (enter + exit).

---

## 1. Kowalski Style (Minimal)

Subtle, almost invisible. `opacity` + tiny `translateY(4px)`. Short spring or fast ease-out.
Best for: SaaS, productivity tools, frequent UI elements.

### CSS

```css
/* BAD -- entry without exit */
.card {
  animation: kowalski-in 0.2s ease-out forwards;
}
@keyframes kowalski-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* GOOD -- enter + exit */
.card {
  animation: kowalski-in 0.2s ease-out forwards;
}
.card.exiting {
  animation: kowalski-out 0.15s ease-in forwards;
}
@keyframes kowalski-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes kowalski-out {
  from { opacity: 1; transform: translateY(0); }
  to { opacity: 0; transform: translateY(2px); }
}
```

### Framer Motion

```tsx
/* BAD -- no exit */
<motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} />

/* GOOD */
<AnimatePresence>
  {show && (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 2 }}
      transition={{ type: "spring", stiffness: 400, damping: 30 }}
    />
  )}
</AnimatePresence>
```

### GSAP

```js
// BAD -- no exit
gsap.from('.card', { opacity: 0, y: 4, duration: 0.2, ease: "power2.out" });

// GOOD
function enterCard(el) {
  return gsap.from(el, { opacity: 0, y: 4, duration: 0.2, ease: "power2.out" });
}
function exitCard(el) {
  return gsap.to(el, { opacity: 0, y: 2, duration: 0.15, ease: "power1.in" });
}
```

---

## 2. Krehel Style (Material)

Rich, layered. `opacity` + `translateY(8px)` + `blur(4px)`. Spring ~0.45s.
Best for: portfolios, creative sites, landing pages.

### CSS

```css
/* BAD -- entry without exit */
.card {
  animation: krehel-in 0.45s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
@keyframes krehel-in {
  from { opacity: 0; transform: translateY(8px); filter: blur(4px); }
  to { opacity: 1; transform: translateY(0); filter: blur(0); }
}

/* GOOD -- enter + exit */
.card {
  animation: krehel-in 0.45s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
.card.exiting {
  animation: krehel-out 0.25s ease-in forwards;
}
@keyframes krehel-in {
  from { opacity: 0; transform: translateY(8px); filter: blur(4px); }
  to { opacity: 1; transform: translateY(0); filter: blur(0); }
}
@keyframes krehel-out {
  from { opacity: 1; transform: translateY(0); filter: blur(0); }
  to { opacity: 0; transform: translateY(4px); filter: blur(2px); }
}
```

### Framer Motion

```tsx
/* BAD -- no exit */
<motion.div
  initial={{ opacity: 0, y: 8, filter: "blur(4px)" }}
  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
/>

/* GOOD */
<AnimatePresence>
  {show && (
    <motion.div
      initial={{ opacity: 0, y: 8, filter: "blur(4px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: 4, filter: "blur(2px)" }}
      transition={{ type: "spring", stiffness: 200, damping: 20 }}
    />
  )}
</AnimatePresence>
```

### GSAP

```js
// BAD -- no exit
gsap.from('.card', {
  opacity: 0, y: 8, filter: "blur(4px)",
  duration: 0.45, ease: "power3.out"
});

// GOOD
function enterCard(el) {
  return gsap.from(el, {
    opacity: 0, y: 8, filter: "blur(4px)",
    duration: 0.45, ease: "power3.out"
  });
}
function exitCard(el) {
  return gsap.to(el, {
    opacity: 0, y: 4, filter: "blur(2px)",
    duration: 0.25, ease: "power2.in"
  });
}
```

---

## 3. Jhey Style (Playful)

Energetic, bouncy. `scale` + `rotate`, bounce/elastic easing.
Best for: kids apps, playful brands, gamified UI, creative portfolios.

### CSS

```css
/* BAD -- entry without exit */
.card {
  animation: jhey-in 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}
@keyframes jhey-in {
  from { opacity: 0; transform: scale(0.8) rotate(-4deg); }
  to { opacity: 1; transform: scale(1) rotate(0deg); }
}

/* GOOD -- enter + exit */
.card {
  animation: jhey-in 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}
.card.exiting {
  animation: jhey-out 0.3s ease-in forwards;
}
@keyframes jhey-in {
  from { opacity: 0; transform: scale(0.8) rotate(-4deg); }
  to { opacity: 1; transform: scale(1) rotate(0deg); }
}
@keyframes jhey-out {
  from { opacity: 1; transform: scale(1) rotate(0deg); }
  to { opacity: 0; transform: scale(0.9) rotate(2deg); }
}
```

### Framer Motion

```tsx
/* BAD -- no exit */
<motion.div
  initial={{ opacity: 0, scale: 0.8, rotate: -4 }}
  animate={{ opacity: 1, scale: 1, rotate: 0 }}
/>

/* GOOD */
<AnimatePresence>
  {show && (
    <motion.div
      initial={{ opacity: 0, scale: 0.8, rotate: -4 }}
      animate={{ opacity: 1, scale: 1, rotate: 0 }}
      exit={{ opacity: 0, scale: 0.9, rotate: 2 }}
      transition={{ type: "spring", stiffness: 600, damping: 15 }}
    />
  )}
</AnimatePresence>
```

### GSAP

```js
// BAD -- no exit
gsap.from('.card', {
  opacity: 0, scale: 0.8, rotation: -4,
  duration: 0.6, ease: "back.out(1.7)"
});

// GOOD
function enterCard(el) {
  return gsap.from(el, {
    opacity: 0, scale: 0.8, rotation: -4,
    duration: 0.6, ease: "back.out(1.7)"
  });
}
function exitCard(el) {
  return gsap.to(el, {
    opacity: 0, scale: 0.9, rotation: 2,
    duration: 0.3, ease: "power2.in"
  });
}
```

---

## 4. Snappy Style

Fast, professional. `opacity` + `translateY(-8px)` (drops down), ease-out 150ms.
Best for: dashboards, data-heavy apps, developer tools.

### CSS

```css
/* BAD -- entry without exit */
.tooltip {
  animation: snappy-in 0.15s ease-out forwards;
}
@keyframes snappy-in {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* GOOD -- enter + exit */
.tooltip {
  animation: snappy-in 0.15s ease-out forwards;
}
.tooltip.exiting {
  animation: snappy-out 0.1s ease-in forwards;
}
@keyframes snappy-in {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes snappy-out {
  from { opacity: 1; transform: translateY(0); }
  to { opacity: 0; transform: translateY(-4px); }
}
```

### Framer Motion

```tsx
/* BAD -- no exit */
<motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} />

/* GOOD */
<AnimatePresence>
  {show && (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.15, ease: [0, 0, 0.58, 1] }}
    />
  )}
</AnimatePresence>
```

### GSAP

```js
// BAD -- no exit
gsap.from('.tooltip', { opacity: 0, y: -8, duration: 0.15, ease: "power2.out" });

// GOOD
function enterTooltip(el) {
  return gsap.from(el, { opacity: 0, y: -8, duration: 0.15, ease: "power2.out" });
}
function exitTooltip(el) {
  return gsap.to(el, { opacity: 0, y: -4, duration: 0.1, ease: "power1.in" });
}
```

---

## 5. Cinematic Style

Slow, dramatic. `clipPath` reveal, 600ms+. Content revealed through a mask/wipe.
Best for: hero sections, portfolios, editorial, storytelling.

### CSS

```css
/* BAD -- entry without exit */
.hero {
  animation: cinematic-in 0.8s cubic-bezier(0.4, 0, 0.2, 1) forwards;
}
@keyframes cinematic-in {
  from { clip-path: inset(0 100% 0 0); }
  to { clip-path: inset(0 0% 0 0); }
}

/* GOOD -- enter + exit */
.hero {
  animation: cinematic-in 0.8s cubic-bezier(0.4, 0, 0.2, 1) forwards;
}
.hero.exiting {
  animation: cinematic-out 0.5s ease-in forwards;
}
@keyframes cinematic-in {
  from { clip-path: inset(0 100% 0 0); }
  to { clip-path: inset(0 0% 0 0); }
}
@keyframes cinematic-out {
  from { clip-path: inset(0 0% 0 0); opacity: 1; }
  to { clip-path: inset(0 0% 0 100%); opacity: 0; }
}
```

### Framer Motion

```tsx
/* BAD -- no exit */
<motion.div
  initial={{ clipPath: "inset(0 100% 0 0)" }}
  animate={{ clipPath: "inset(0 0% 0 0)" }}
  transition={{ duration: 0.8, ease: [0.4, 0, 0.2, 1] }}
/>

/* GOOD */
<AnimatePresence>
  {show && (
    <motion.div
      initial={{ clipPath: "inset(0 100% 0 0)" }}
      animate={{ clipPath: "inset(0 0% 0 0)" }}
      exit={{ clipPath: "inset(0 0% 0 100%)", opacity: 0 }}
      transition={{ duration: 0.8, ease: [0.4, 0, 0.2, 1] }}
    />
  )}
</AnimatePresence>
```

### GSAP

```js
// BAD -- no exit
gsap.from('.hero', {
  clipPath: "inset(0 100% 0 0)",
  duration: 0.8, ease: "power2.inOut"
});

// GOOD
function enterHero(el) {
  return gsap.fromTo(el,
    { clipPath: "inset(0 100% 0 0)" },
    { clipPath: "inset(0 0% 0 0)", duration: 0.8, ease: "power2.inOut" }
  );
}
function exitHero(el) {
  return gsap.to(el, {
    clipPath: "inset(0 0% 0 100%)", opacity: 0,
    duration: 0.5, ease: "power2.in"
  });
}
```

---

## Stagger Patterns

Stagger transforms a group of identical animations into a choreography.

### CSS (with custom properties)

```css
.card { animation: fade-up 0.3s ease-out forwards; animation-delay: calc(var(--i) * 50ms); opacity: 0; }
/* Set --i via inline style or nth-child */
.card:nth-child(1) { --i: 0; }
.card:nth-child(2) { --i: 1; }
.card:nth-child(3) { --i: 2; }
```

### Framer Motion (variants)

```tsx
const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05, delayChildren: 0.1 } },
  exit: { transition: { staggerChildren: 0.03, staggerDirection: -1 } },
};
const item = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 4 },
};

<motion.ul variants={container} initial="hidden" animate="show" exit="exit">
  {items.map((item) => (
    <motion.li key={item.id} variants={item} />
  ))}
</motion.ul>
```

### GSAP

```js
// Linear stagger
gsap.from('.card', {
  opacity: 0, y: 20,
  duration: 0.4, ease: "power2.out",
  stagger: 0.06
});

// Center-out stagger (items animate from center outward)
gsap.from('.card', {
  opacity: 0, y: 20,
  duration: 0.4, ease: "power2.out",
  stagger: { each: 0.06, from: "center" }
});

// Grid stagger (2D distribution)
gsap.from('.grid-item', {
  opacity: 0, scale: 0.95,
  duration: 0.4, ease: "power2.out",
  stagger: { each: 0.04, from: "start", grid: [4, 4] }
});
```

---

## Summary: Which Recipe for Which Project?

| Project Type | Primary Recipe | Stagger | Timing |
|---|---|---|---|
| SaaS / Dashboard | Kowalski or Snappy | 40-60ms | 150-250ms |
| Portfolio / Agency | Krehel or Cinematic | 60-100ms | 300-600ms |
| E-commerce | Kowalski (products), Snappy (filters) | 50ms | 150-300ms |
| Landing page | Krehel (hero), Cinematic (sections) | 80-120ms | 400-800ms |
| Kids / Game UI | Jhey | 60-80ms | 300-600ms |
| Developer tools | Snappy | 30-50ms | 100-200ms |
