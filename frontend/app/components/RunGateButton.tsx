"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconGate } from "./icons";
import type { AgentRow } from "@/app/lib/api";

/** Run the regression suite for one agent. `agents` comes from the project's registry (ordered by
 *  the page so agents that actually have promoted cases come first) — no hardcoded slug, which is
 *  what used to make this button 404 with "agent 'planner' not found" on every fresh project. */
export function RunGateButton({
  agents,
  caseCounts = {},
}: {
  agents: AgentRow[];
  caseCounts?: Record<string, number>;
}) {
  const [agentId, setAgentId] = useState(agents[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const router = useRouter();

  const agent = agents.find((a) => a.id === agentId) ?? agents[0];
  const cases = agent ? (caseCounts[agent.id] ?? 0) : 0;

  if (!agent) {
    return (
      <p className="max-w-xs text-right text-[12.5px] text-fg-faint">
        No agents yet — send a trace, then promote a failing run to a case.
      </p>
    );
  }

  async function go() {
    if (!agent) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/gate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ agent: agent.slug, env: "ci" }),
      });
      const d = await r.json().catch(() => null);
      if (r.ok && d?.id) {
        router.push(`/gates/${d.id}`);
        return;
      }
      setErr(d?.detail ?? `Gate failed (HTTP ${r.status})`);
    } catch {
      setErr("Gate failed: could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2">
        {agents.length > 1 && (
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            aria-label="Agent to gate"
            className="rounded-lg border border-line bg-ink-700 px-2.5 py-2 font-mono text-[12.5px] text-fg-muted transition-colors hover:border-line-bright focus:border-signal/50 focus:outline-none"
          >
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.slug} ({caseCounts[a.id] ?? 0})
              </option>
            ))}
          </select>
        )}
        <button
          onClick={go}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg border border-signal/40 bg-signal/15 px-3.5 py-2 text-[13px] font-medium text-signal transition-all hover:bg-signal/25 hover:shadow-glow disabled:opacity-60"
        >
          <IconGate className="h-4 w-4" />
          {busy ? "Running gate…" : `Run gate · ${agent.slug} · ci`}
        </button>
      </div>
      {cases === 0 && !err && (
        // total == 0 → PASS (nothing to protect yet), so say that rather than let the run look
        // like a real green.
        <p className="text-[12px] text-fg-faint">
          No promoted cases for <span className="font-mono">{agent.slug}</span> — the gate passes
          with nothing to check. Promote a failing trace first.
        </p>
      )}
      {err && (
        <p role="alert" className="text-[12px] text-rose-400">
          {err}
        </p>
      )}
    </div>
  );
}
