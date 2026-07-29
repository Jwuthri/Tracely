"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const CONFIRM = "DELETE";

/** Danger zone: wipe every trace + everything derived from it. Typed confirmation rather than a
 *  `confirm()` dialog — this one can't be undone by re-promoting or re-analyzing. */
export function WipeDataPanel() {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<Record<string, number> | null>(null);
  const router = useRouter();

  async function go() {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/project/data", {
        method: "DELETE",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ confirm: CONFIRM }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `Delete failed (HTTP ${r.status})`);
        return;
      }
      setDone(d?.deleted ?? {});
      setTyped("");
      router.refresh();
    } catch {
      setErr("Delete failed: could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  const rows = Object.entries(done ?? {});

  return (
    <section className="card overflow-hidden border-fail/30">
      <div className="hairline border-fail/20 bg-fail-dim/20 px-4 py-3 text-[13px] font-semibold text-fail">
        Delete all data
      </div>
      <div className="space-y-4 p-5">
        <p className="text-[13.5px] leading-relaxed text-fg-muted">
          Removes every trace, span and score in this project, plus everything derived from them —
          agents, regression cases and replays, gate runs, failure clusters, meta-analyses, rolling
          summaries and judge annotations. Your ingest keys, evaluator columns, monitors and team
          stay, so the workspace works the moment the next trace lands.
        </p>
        <p className="text-[13px] text-fg-faint">
          This cannot be undone. Type <span className="font-mono text-fg">{CONFIRM}</span> to
          enable the button.
        </p>

        <div className="flex flex-wrap items-center gap-2.5">
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={CONFIRM}
            aria-label={`Type ${CONFIRM} to confirm`}
            className="w-40 rounded-lg border border-line bg-ink-900 px-3 py-2 font-mono text-[13px] text-fg placeholder:text-fg-faint focus:border-fail/50 focus:outline-none"
          />
          <button
            onClick={go}
            disabled={typed !== CONFIRM || busy}
            className="rounded-lg border border-fail/40 bg-fail/15 px-3.5 py-2 text-[13px] font-medium text-fail transition-colors hover:bg-fail/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "Deleting…" : "Delete all project data"}
          </button>
        </div>

        {err && (
          <p role="alert" className="text-[12.5px] text-rose-400">
            {err}
          </p>
        )}
        {done && (
          <div role="status" className="rounded-lg border border-line bg-ink-900 p-3.5">
            {rows.length === 0 ? (
              <p className="text-[13px] text-fg-muted">Nothing to delete — the project was empty.</p>
            ) : (
              <>
                <p className="text-[13px] text-ok">Deleted:</p>
                <ul className="mt-1.5 space-y-0.5 font-mono text-[12px] text-fg-muted">
                  {rows.map(([k, v]) => (
                    <li key={k}>
                      {v.toLocaleString()} {k}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
