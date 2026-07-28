# Designer Reference Profiles

Three design philosophies that define modern motion on the web.
Use this to calibrate the animation intensity and style for a given project.

---

## Emil Kowalski

### Philosophy

Motion should be invisible. The best animation is one the user never consciously notices -- it just makes the interface feel "right." Every millisecond of duration and every pixel of displacement must earn its place. If removing an animation makes the UI feel the same, the animation was wrong.

### Signatures

- **Micro-transitions:** opacity + translateY(2-6px), never more
- **Ultra-short springs:** stiffness 400+, damping 30+, near-zero overshoot
- **Durations:** 100-200ms, rarely exceeds 250ms
- **Easing:** ease-out or critically-damped springs
- **No blur, no scale, no rotation** on standard UI elements
- **Stagger:** 30-50ms, barely perceptible
- **Exit:** faster than enter, often just opacity fade in 100ms

### When to Channel Kowalski

- User performs an action 10+ times per session
- The animation accompanies a frequent interaction (toggle, dropdown, tab)
- The product's identity is "fast" or "professional"
- You want the UI to feel polished without anyone being able to point at why

### Key Principle

> "The animation should feel like it was always there."

---

## Jakub Krehel

### Philosophy

Motion is a storytelling medium. Every transition should feel intentional and crafted -- like a camera movement in film. Blur, scale, and layered timing create depth and dimensionality. The interface isn't flat; it's a stage where elements perform choreographed entrances and exits.

### Signatures

- **Layered transitions:** opacity + translateY(8-16px) + blur(4-8px) simultaneously
- **Blur as depth cue:** entering elements are "out of focus" then sharpen
- **Medium springs:** stiffness 150-250, damping 15-25, gentle overshoot
- **Durations:** 300-500ms, comfortable for storytelling
- **Stagger:** 60-100ms, clearly visible choreography
- **Clip-path reveals:** sections revealed through geometric masks
- **Parallax layers:** foreground/background at different scroll speeds
- **Exit:** mirrors enter but compressed (60-70% of enter duration), blur increases

### When to Channel Krehel

- First impression matters (landing pages, portfolios, hero sections)
- The product's identity is "premium" or "crafted"
- Content is consumed, not manipulated (editorial, showcase)
- You have room for 300ms+ without blocking user flow

### Key Principle

> "Every element deserves a moment on stage."

---

## Jhey Tompkins

### Philosophy

The web should spark joy. Animation is not just functional polish -- it's personality, surprise, and delight. Scale, rotation, color shifts, and elastic physics make interfaces feel alive and playful. Rules exist to be bent (not broken). The unexpected is the reward.

### Signatures

- **Scale + rotation combos:** elements spin, bounce, pop in
- **Elastic/bounce easing:** intentional overshoot, wobble
- **Color shifts:** hue rotation, gradient animations during transitions
- **SVG path animations:** morphing shapes, drawing strokes
- **3D transforms:** perspective flips, card rotations
- **Easter eggs:** hover states that surprise, scroll-triggered delights
- **Custom properties animations:** `@property` for animating gradients, counters
- **Durations:** 400-800ms, the animation IS the experience
- **Stagger:** 60-100ms with bounce, creates a "wave" effect

### When to Channel Jhey

- The brand is playful, young, or creative
- Onboarding flows where engagement > speed
- Marketing pages where "wow factor" converts
- Game UI, kids apps, creative tools
- Easter eggs and micro-delights in any product

### Key Principle

> "If it doesn't make you smile, animate it differently."

---

## Weighting Table by Project Type

Use this to decide which philosophy drives the motion design. **Primary** sets the overall feel, **Secondary** adds depth in key moments, **Selective** is used sparingly for specific contexts.

| Project Type | Primary | Secondary | Selective |
|---|---|---|---|
| SaaS / Productivity | Kowalski | Krehel | Jhey (onboarding, empty states) |
| Portfolio / Creative | Krehel | Jhey | Kowalski (nav, forms) |
| E-commerce | Kowalski | Krehel (product pages) | Jhey (promos, seasonal) |
| Landing page | Krehel | Jhey (CTAs, social proof) | Kowalski (pricing, FAQ) |
| Kids / Playful | Jhey | Krehel (storytelling) | Kowalski (forms, settings) |
| Developer tools | Kowalski | -- | Krehel (docs, changelog) |
| Editorial / Magazine | Krehel | Kowalski (reading UI) | Jhey (interactive pieces) |
| Dashboard / Analytics | Kowalski | -- | Krehel (data viz transitions) |
| Mobile app (React Native) | Kowalski | Krehel (onboarding) | Jhey (achievements) |

### How to Read the Table

- **Primary (70-80% of animations):** This style governs the default motion language. Every component starts here.
- **Secondary (15-25%):** Used for key moments -- first impressions, important state changes, section transitions.
- **Selective (5-10%):** Reserved for specific contexts noted in parentheses. Overuse kills the effect.

### Mixing Styles -- Rules

1. **Never mix styles within a single animation.** One element = one philosophy.
2. **Transition between styles at section boundaries.** Hero (Krehel) then content area (Kowalski) = fine.
3. **The more interactive the element, the more Kowalski it should be.** Buttons, inputs, toggles are always snappy.
4. **The more "look at me" the element, the more Jhey it can be.** Badges, confetti, achievements, celebrations.
5. **When in doubt, go Kowalski.** Subtle is always safer than expressive.
