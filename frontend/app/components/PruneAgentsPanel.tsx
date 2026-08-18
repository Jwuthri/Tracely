"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Clear out registered agents that no longer have any spans. Agents come from what a trace
 *  DECLARES (`tracely.agent.id`); this removes the ones an older rule invented from framework
 *  attributes — every sub-agent a harness spins up. Anything still referenced is kept, so this
 *  needs no typed confirmation. */
export function PruneAgentsPanel() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const router = useRouter();

  async function go() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fetch("/api/project/agents/prune", { method: "POST" });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setMsg(d?.detail ?? `Clean-up failed (HTTP ${r.status})`);
        return;
      }
      const pruned: string[] = d?.pruned ?? [];
      setMsg(
        pruned.length === 0
          ? "Nothing to clean up — every agent is still in use."
          : `Removed ${pruned.length} unused agent${pruned.length === 1 ? "" : "s"}: ${pruned.join(", ")}`,
      );
      router.refresh();
    } catch {
      setMsg("Clean-up failed: could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card p-5">
      <h2 className="text-[15px] font-semibold text-fg">Unused agents</h2>
      <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-fg-muted">
        Agents are registered from the name your traces declare. Remove the ones left with no
        spans — including every sub-agent older versions of Tracely invented from framework
        attributes. Agents still used by a scenario, case, gate or endpoint stay.
      </p>
      <button type="button" className="btn-ghost mt-3" onClick={go} disabled={busy}>
        {busy ? "Cleaning up…" : "Remove unused agents"}
      </button>
      {msg && (
        <p role="status" className="mt-3 text-[12.5px] text-fg-muted">
          {msg}
        </p>
      )}
    </section>
  );
}
