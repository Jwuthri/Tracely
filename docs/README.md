# `docs/` — Tracely SDK documentation site

A [Nextra](https://nextra.site) (Next.js + MDX) site documenting the **`tracely-sdk`** — how it
works, how to instrument an agent, the full API reference, hermetic replay, and the CI gate CLI.

## Run it

```bash
cd docs
pnpm install
pnpm dev            # http://localhost:3002  (live reload)
```

## Build / deploy

```bash
pnpm build          # production build
pnpm start          # serve the build on :3002
```

It's a standard Next.js app — deploy to Vercel/Netlify/any Node host (`next build` + `next start`),
or `make docs` from the repo root for local dev.

## Layout

| Path | What |
|---|---|
| `pages/*.mdx` | the content (one file per nav entry) |
| `pages/_meta.js` | sidebar order + labels |
| `pages/_app.jsx` | required Nextra app shell |
| `theme.config.jsx` | logo, links, footer, colors |
| `next.config.mjs` | the Nextra plugin wiring |

Keep it in sync with [`sdk/`](../sdk/README.md) — the API reference mirrors the SDK's public surface.
