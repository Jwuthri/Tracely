import Link from "next/link";

// Custom 404 — a real page instead of the bare Next default.
export default function NotFound() {
  return (
    <div className="grid min-h-screen place-items-center px-6 text-center">
      <div className="reveal">
        <div className="font-mono text-[12px] uppercase tracking-[0.3em] text-fg-faint">404</div>
        <h1 className="mt-3 font-display text-[28px] font-extrabold tracking-tight">Page not found</h1>
        <p className="mx-auto mt-2 max-w-sm text-[14px] text-fg-muted">
          That route doesn’t exist. It may have moved, or the link was mistyped.
        </p>
        <Link
          href="/"
          className="mt-6 inline-block rounded-lg border border-signal/40 bg-signal/10 px-4 py-2 text-[13px] font-medium text-fg transition-colors hover:bg-signal/20"
        >
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
