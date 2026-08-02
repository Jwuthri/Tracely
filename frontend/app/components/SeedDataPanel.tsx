"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Fill an empty workspace with the demo dataset, without dropping to a terminal.
 *
 *  The seeder drives the product through its own HTTP API and takes a couple of minutes, so the
 *  request only QUEUES it — there is nothing to await. The page can't know when it finished, so it
 *  says so plainly and offers a refresh rather than faking a progress bar. */
export function SeedDataPanel({ empty }: { empty: boolean }) {
  const [state, setState] = useState<"idle" | "busy" | "queued">("idle");
  const [err, setErr] = useState<string | null>(null);
  const router = useRouter();

  async function go() {
    setState("busy");
    setErr(null);
    try {
      const r = await fetch("/api/project/seed", { method: "POST" });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `Seeding failed (HTTP ${r.status})`);
        setState("idle");
        return;
      }
      setState("queued");
    } catch {
      setErr("Seeding failed: could not reach the server.");
      setState("idle");
    }
  }

  return (
    <section className="card p-5">
      <h2 className="text-[15px] font-semibold text-fg">Seed demo data</h2>
      <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-fg-muted">
        Populates this workspace end to end — conversations of every shape (including failures),
        clustered issues, promoted regression cases, red→green CI gates, and scenarios. The same
        thing <code className="text-fg-muted">make demo</code> runs. Safe to repeat: each phase is
        skipped when its data already exists.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          onClick={go}
          disabled={state === "busy"}
          className="rounded-lg border border-signal/40 bg-signal/10 px-3.5 py-2 text-[13px] font-medium text-signal transition-colors hover:bg-signal/20 disabled:opacity-50"
        >
          {state === "busy" ? "Queueing…" : empty ? "Seed demo data" : "Seed demo data again"}
        </button>
        {state === "queued" && (
          <span className="text-[12.5px] text-fg-muted">
            Queued — it takes a minute or two.{" "}
            <button onClick={() => router.refresh()} className="text-signal hover:underline">
              Refresh
            </button>{" "}
            to see the counts climb.
          </span>
        )}
        {err && <span className="text-[12.5px] text-fail">{err}</span>}
      </div>
    </section>
  );
}
