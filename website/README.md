# `website/` — the Tracely marketing site

A standalone Next.js 15 app (like `docs/`): one landing page, animated with GSAP
(`ScrollTrigger` + `@gsap/react`), wearing the web app's exact theme tokens
(`tailwind.config.ts` is copied from `../frontend`, same fonts: Bricolage Grotesque /
Hanken Grotesk / JetBrains Mono).

```bash
make website        # or: cd website && pnpm install && pnpm dev   → http://localhost:3003
```

- `app/Landing.tsx` — the whole page: hero with a looping "self-writing trace" panel,
  scroll-driven pipeline (Trace → Detect → Freeze → Gate), features, CI-gate demo, SDK,
  final CTA. All motion is gated behind `prefers-reduced-motion: no-preference` via
  `gsap.matchMedia` — with reduced motion (or no JS) the page renders fully static.
- `NEXT_PUBLIC_APP_URL` (default `http://localhost:3001`) — where the "Open dashboard"
  CTAs point. Set it to the deployed app URL in production.
