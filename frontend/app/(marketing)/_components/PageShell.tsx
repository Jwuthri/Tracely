import Link from "next/link";

import { DOCS_URL, GITHUB_URL } from "@/app/lib/site";

// Static nav + footer for marketing sub-pages. Deliberately NOT shared with Landing.tsx: that one's
// header is animation-coupled (GSAP sets `.site-nav` opacity before first paint and reveals it on a
// timeline), so lifting a common shell would mean either dragging GSAP onto every content page or
// unpicking the intro animation. Content pages want neither.

// Only routes that exist. A nav entry pointing at an unbuilt page is a 404 for readers and a dead
// internal link for crawlers — add each entry in the same commit as the page it points to.
const NAV = [
  { href: "/llm-evaluation", label: "LLM evaluation" },
  { href: "/langfuse-alternatives", label: "Comparisons" },
  { href: DOCS_URL, label: "Docs", external: true },
  { href: "/#pricing", label: "Pricing" },
];

function Mark({ size = 30 }: { size?: number }) {
  return (
    <span
      className="relative grid shrink-0 place-items-center border border-signal/30 bg-signal/10"
      style={{ width: size, height: size, borderRadius: size * 0.32 }}
    >
      <svg width={size * 0.5} height={size * 0.5} viewBox="0 0 24 24" fill="none" aria-hidden>
        <path d="M12 2 22 12 12 22 2 12Z" stroke="#22d3ee" strokeWidth="1.8" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="2.7" fill="#22d3ee" />
      </svg>
    </span>
  );
}

export function PageShell({ children }: { children: React.ReactNode }) {
  return (
    // overflow-x-clip lets content pages use full-bleed (w-screen) decoration inside the fixed
    // column without producing a horizontal scrollbar.
    <div className="min-h-screen overflow-x-clip bg-ink-950">
      <header className="sticky top-0 z-50 border-b border-line/60 bg-ink-950/80 backdrop-blur-md">
        <nav className="mx-auto flex h-16 max-w-[1100px] items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <Mark />
            <span className="font-display text-lg font-bold tracking-tight">Tracely</span>
          </Link>
          <div className="hidden items-center gap-6 text-sm text-fg-muted md:flex">
            {NAV.map((n) =>
              n.external ? (
                <a key={n.href} className="transition hover:text-fg" href={n.href} target="_blank" rel="noreferrer">
                  {n.label}
                </a>
              ) : (
                <Link key={n.href} className="transition hover:text-fg" href={n.href}>
                  {n.label}
                </Link>
              )
            )}
          </div>
          <a
            className="inline-flex items-center gap-2 rounded-full bg-signal px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-signal-soft"
            href="/dashboard"
          >
            Start free
          </a>
        </nav>
      </header>

      <main className="mx-auto max-w-[820px] px-6 py-16">{children}</main>

      <footer className="border-t border-line/60">
        <div className="mx-auto flex max-w-[1100px] flex-col gap-4 px-6 py-10 text-sm text-fg-faint sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-center gap-2.5">
            <Mark size={20} />
            <span className="font-display font-bold text-fg-muted">Tracely</span> · © 2026
          </p>
          <div className="flex flex-wrap items-center gap-5">
            <Link className="transition hover:text-fg" href="/">Home</Link>
            <a className="transition hover:text-fg" href={DOCS_URL} target="_blank" rel="noreferrer">Docs</a>
            <a className="transition hover:text-fg" href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a>
          </div>
        </div>
      </footer>
    </div>
  );
}

/** Shared prose rhythm for content pages — one place to change type scale across all of them. */
export const prose = {
  h2: "mt-14 scroll-mt-24 font-display text-3xl font-bold tracking-tight text-fg",
  h3: "mt-9 font-display text-xl font-bold tracking-tight text-fg",
  p: "mt-4 leading-relaxed text-fg-muted",
  ul: "mt-4 space-y-2 text-fg-muted",
};
