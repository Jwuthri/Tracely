"use client";

import { useState } from "react";
import { IconBolt } from "./icons";

/** Turn this production conversation into a replayable scenario.
 *
 *  The point of the whole feature: the thread that broke in production becomes the thread that
 *  gates the PR claiming to fix it. The backend reads the thread's turns and keeps the user side,
 *  unwrapping recorded envelopes (`{"prompt": …}`, `{"messages": […]}`) back to plain text. */
export function SaveAsScenarioButton({
  threadId,
  agent,
  defaultTitle,
}: {
  threadId: string;
  agent: string;
  defaultTitle?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ id: string; turns: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/scenarios/import", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, agent, title: defaultTitle }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `Could not import (HTTP ${r.status})`);
        return;
      }
      setDone({ id: d.id, turns: (d.turns ?? []).length });
    } catch {
      setErr("Could not import: the server is unreachable.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <a href="/scenarios" className="text-right font-mono text-[12px] text-ok transition-colors hover:text-signal">
        ✓ saved as a {done.turns}-turn scenario → manage
      </a>
    );
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button onClick={save} disabled={busy} className="btn-ghost text-[12.5px]">
        <IconBolt className="h-4 w-4" />
        {busy ? "Saving…" : "Save as scenario"}
      </button>
      {err && (
        <p role="alert" className="text-[12px] text-fail">
          {err}
        </p>
      )}
    </div>
  );
}
