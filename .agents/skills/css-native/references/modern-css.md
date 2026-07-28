# Modern CSS — Browser Support, Fallbacks & Progressive Enhancement

> Last verified: March 2026

---

## Browser Support Tables

### Scroll-Driven Animations (`animation-timeline`)

| Browser | Version | Status |
|---|---|---|
| Chrome | 115+ | Supported |
| Edge | 115+ | Supported |
| Firefox | 128+ | Supported (shipped July 2024) |
| Safari | 18.4+ | Supported (shipped early 2025) |

**Global coverage**: ~90%+ (as of March 2026)

### View Transitions API

| Feature | Chrome | Edge | Firefox | Safari |
|---|---|---|---|---|
| Same-document (`startViewTransition`) | 111+ | 111+ | 133+ | 18+ |
| Cross-document (`@view-transition`) | 126+ | 126+ | Not yet | 18.2+ |
| `view-transition-class` | 125+ | 125+ | Not yet | 18.2+ |

**Note**: Cross-document view transitions are an Interop 2026 focus area — Firefox support expected to land in 2026.

### @starting-style

| Browser | Version | Status |
|---|---|---|
| Chrome | 117+ | Supported |
| Edge | 117+ | Supported |
| Firefox | 129+ | Supported |
| Safari | 17.5+ | Supported |

**Global coverage**: ~93%+ — Baseline Newly Available (2024)

### CSS Anchor Positioning

| Browser | Version | Status |
|---|---|---|
| Chrome | 125+ | Supported |
| Edge | 125+ | Supported |
| Firefox | Nightly | In development (Interop 2026) |
| Safari | 26+ | Supported (shipped 2026) |

**Note**: Anchor positioning is an Interop 2026 focus area. Firefox expected to ship stable support in 2026.

### Container Queries

| Feature | Chrome | Edge | Firefox | Safari |
|---|---|---|---|---|
| Size queries (`@container`) | 105+ | 105+ | 110+ | 16+ |
| Container-relative units (`cqw`, `cqh`) | 105+ | 105+ | 110+ | 16+ |
| Style queries (`@container style()`) | 111+ | 111+ | Not yet | 18+ |

**Global coverage (size queries)**: ~95%+

---

## Fallback Patterns

### Scroll-Driven Animations

```css
/* Base: no scroll animation, element is always visible */
.reveal {
  opacity: 1;
  transform: translateY(0);
}

/* Progressive enhancement for supporting browsers */
@supports (animation-timeline: scroll()) {
  .reveal {
    animation: reveal-up linear both;
    animation-timeline: view();
    animation-range: entry 10% entry 90%;
  }

  @keyframes reveal-up {
    from {
      opacity: 0;
      transform: translateY(2rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
}
```

**Strategy**: Content is always visible by default. Scroll animation is purely decorative enhancement. Never hide content behind a scroll-driven animation without fallback.

### View Transitions (Same-Document)

```js
function navigate(updateFn) {
  // Fallback: just update the DOM instantly
  if (!document.startViewTransition) {
    updateFn();
    return;
  }

  document.startViewTransition(() => updateFn());
}
```

```css
/* Only apply transition styles if supported */
@supports (view-transition-name: none) {
  .hero { view-transition-name: hero; }

  ::view-transition-old(hero) {
    animation: fade-scale-out 250ms ease-out both;
  }
  ::view-transition-new(hero) {
    animation: fade-scale-in 300ms ease-in both;
  }
}
```

### View Transitions (Cross-Document)

```css
/* This rule is safely ignored by browsers that don't support it */
@view-transition {
  navigation: auto;
}

/* Guard transition-specific styles */
@supports (view-transition-name: none) {
  .page-header { view-transition-name: header; }
  .main-content { view-transition-name: content; }

  ::view-transition-group(header) {
    animation-duration: 300ms;
  }
  ::view-transition-group(content) {
    animation-duration: 250ms;
  }
}
```

**Strategy**: Pages load normally in unsupported browsers. The `@view-transition` rule is unknown and ignored — no breakage.

### @starting-style

```css
/* Broad support — but guard with @supports for very old browsers */
.popover {
  opacity: 1;
  transform: scale(1);
  transition: opacity 200ms ease, transform 200ms ease;
}

/* @starting-style is baseline — this works in all modern browsers */
.popover {
  @starting-style {
    opacity: 0;
    transform: scale(0.95);
  }
}

/* For the display transition, check discrete support */
@supports (transition-behavior: allow-discrete) {
  .popover {
    transition: opacity 200ms ease, transform 200ms ease,
                display 200ms allow-discrete, overlay 200ms allow-discrete;
  }

  .popover:not(:popover-open) {
    opacity: 0;
    transform: scale(0.95);
    display: none;
  }
}
```

**Strategy**: `@starting-style` itself is well-supported. The main concern is `transition-behavior: allow-discrete` for `display`/`overlay` transitions. Guard that part specifically.

### Anchor Positioning

```css
/* Feature detection for anchor positioning */
@supports (anchor-name: --a) {
  .trigger { anchor-name: --trigger; }

  .tooltip {
    position: fixed;
    position-anchor: --trigger;
    inset-area: top center;
    margin-bottom: 0.5rem;

    position-try-fallbacks: --bottom;
  }

  @position-try --bottom {
    inset-area: bottom center;
    margin-top: 0.5rem;
  }
}

/* Fallback for unsupported browsers: manual absolute positioning */
@supports not (anchor-name: --a) {
  .tooltip-wrapper {
    position: relative;
  }

  .tooltip {
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    margin-bottom: 0.5rem;
  }
}
```

**Strategy**: Use `@supports (anchor-name: --a)` to detect. Provide a classic `position: absolute` fallback. For JS-heavy apps, Floating UI remains a solid fallback.

### Container Queries

```css
/* Container queries are baseline — safe for production */
.card-wrapper {
  container-type: inline-size;
  container-name: card;
}

/* Size queries: well supported */
@container card (min-width: 400px) {
  .card { flex-direction: row; }
}

/* Style queries: Chrome/Edge/Safari only — use with care */
@supports (container-type: inline-size) {
  /* Size queries are safe — 95%+ coverage */
}

/* Style queries: progressive enhancement only */
@container style(--theme: dark) {
  .card { background: oklch(0.2 0.02 250); }
}
/* Fallback: use a class or media query for unsupported browsers */
```

---

## Progressive Enhancement Strategies

### Strategy 1: Layered Animation (Recommended)

Build in layers — each layer adds richness but nothing breaks without it.

```css
/* Layer 0: Content is visible, no animation */
.section-title {
  opacity: 1;
}

/* Layer 1: Simple transition (universally supported) */
.section-title {
  transition: opacity 400ms ease, transform 400ms ease;
}
.section-title.visible {
  opacity: 1;
  transform: translateY(0);
}

/* Layer 2: Scroll-driven (modern browsers only) */
@supports (animation-timeline: scroll()) {
  .section-title {
    animation: reveal linear both;
    animation-timeline: view();
    animation-range: entry 0% entry 80%;
    /* Remove the JS-toggled class approach */
    transition: none;
  }

  @keyframes reveal {
    from { opacity: 0; transform: translateY(1.5rem); }
    to   { opacity: 1; transform: translateY(0); }
  }
}
```

### Strategy 2: View Transition as Enhancement

```js
// Router integration example (works with any framework)
async function navigateTo(url) {
  const response = await fetch(url);
  const html = await response.text();
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');

  const updateDOM = () => {
    document.title = doc.title;
    document.querySelector('main').replaceWith(
      doc.querySelector('main')
    );
  };

  if (document.startViewTransition) {
    document.startViewTransition(updateDOM);
  } else {
    updateDOM();
  }
}
```

```css
/* Cross-document: progressive by nature */
@view-transition { navigation: auto; }

/* Reduce motion: respect user preferences */
@media (prefers-reduced-motion: reduce) {
  ::view-transition-group(*),
  ::view-transition-old(*),
  ::view-transition-new(*) {
    animation-duration: 0.01ms !important;
  }
}
```

### Strategy 3: @starting-style + Popover API

Full native modal with enter/exit animation, zero JavaScript.

```html
<button popovertarget="menu">Open</button>

<div id="menu" popover>
  <p>Menu content</p>
</div>
```

```css
[popover] {
  /* Open state */
  opacity: 1;
  transform: translateY(0) scale(1);
  transition: opacity 250ms ease, transform 250ms ease,
              display 250ms allow-discrete, overlay 250ms allow-discrete;

  /* Entry animation */
  @starting-style {
    opacity: 0;
    transform: translateY(-0.5rem) scale(0.97);
  }
}

/* Exit animation */
[popover]:not(:popover-open) {
  opacity: 0;
  transform: translateY(-0.5rem) scale(0.97);
}
```

### Strategy 4: Anchor + Popover Combo (Animated Tooltip)

```html
<button anchor="tip" popovertarget="tip">Hover me</button>

<div id="tip" popover="hint" anchor="trigger">
  Tooltip content
</div>
```

```css
[popover="hint"] {
  position: fixed;
  position-anchor: --trigger;
  inset-area: top center;
  margin-bottom: 0.5rem;

  /* Animation */
  opacity: 1;
  transform: translateY(0);
  transition: opacity 150ms ease, transform 150ms ease,
              display 150ms allow-discrete, overlay 150ms allow-discrete;

  @starting-style {
    opacity: 0;
    transform: translateY(4px);
  }

  position-try-fallbacks: --bottom, --left, --right;
}

@position-try --bottom {
  inset-area: bottom center;
  margin-top: 0.5rem;
}
@position-try --left {
  inset-area: left center;
  margin-right: 0.5rem;
}
@position-try --right {
  inset-area: right center;
  margin-left: 0.5rem;
}

/* Respect reduced motion */
@media (prefers-reduced-motion: reduce) {
  [popover="hint"] {
    transition-duration: 0.01ms;
  }
}
```

---

## Accessibility Checklist

```css
/* ALWAYS include this in any project with animations */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

For scroll-driven animations specifically:

```css
@media (prefers-reduced-motion: reduce) {
  .reveal {
    animation: none;
    opacity: 1;
    transform: none;
  }
}
```

---

## Performance Notes

| Property | Rendering Cost | GPU Composited |
|---|---|---|
| `transform` | Low | Yes |
| `opacity` | Low | Yes |
| `filter` / `backdrop-filter` | Medium | Yes |
| `clip-path` | Medium | Yes (in most browsers) |
| `background` (gradients) | Medium | No — repaint |
| `width` / `height` | High | No — reflow + repaint |
| `top` / `left` / `right` / `bottom` | High | No — reflow + repaint |
| `box-shadow` | High | No — repaint |

Best practices:
- Use `will-change` sparingly and only on elements about to animate — never `will-change: transform` on 50 elements
- Prefer `translate`, `scale`, `rotate` individual properties over `transform` shorthand when only one axis changes (allows independent transitions)
- For scroll-driven animations, the browser automatically optimizes — no `will-change` needed
- Test with Chrome DevTools > Rendering > "Highlight areas outside the compositing layers" to verify GPU compositing
