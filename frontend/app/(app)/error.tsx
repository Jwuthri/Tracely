"use client";

// Error boundary for the authed dashboard. Without this, a failed server fetch (backend down, 500)
// renders as an empty page that looks identical to "no data" — this makes an outage legible and
// recoverable instead.
import { useEffect } from "react";

export default function DashboardError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error("dashboard error:", error);
  }, [error]);

  return (
    <div className="reveal mx-auto max-w-lg py-16 text-center">
      <div className="mx-auto mb-5 grid h-12 w-12 place-items-center rounded-xl border border-fail/40 bg-fail/10">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="text-fail">
          <path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <h2 className="font-display text-[20px] font-bold tracking-tight">Something went wrong</h2>
      <p className="mx-auto mt-2 max-w-md text-[13.5px] text-fg-muted">
        This view failed to load — usually the backend is unreachable or returned an error. Your data is
        fine; try again in a moment.
      </p>
      {error?.message && (
        <pre className="mx-auto mt-4 max-w-md overflow-x-auto rounded-lg border border-line bg-ink-900/60 p-3 text-left font-mono text-[11px] text-fg-faint">
          {error.message}
        </pre>
      )}
      <button
        onClick={reset}
        className="mt-5 rounded-lg border border-signal/40 bg-signal/10 px-4 py-2 text-[13px] font-medium text-fg transition-colors hover:bg-signal/20"
      >
        Try again
      </button>
    </div>
  );
}
