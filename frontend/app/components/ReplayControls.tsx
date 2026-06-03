"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconPlay } from "./icons";
import { Badge } from "./ui";

export function ReplayControls({ caseId }: { caseId: string; sourceTraceId?: string }) {
  const [busy, setBusy] = useState(false);
  const [candidate, setCandidate] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const router = useRouter();

  async function replay(candidateTraceId?: string) {
    setBusy(true);
    setResult(null);
    const r = await fetch("/api/replay", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ caseId, candidateTraceId }),
    });
    const data = await r.json();
    setBusy(false);
    setResult(data?.verdict ?? "ERROR");
    router.refresh();
  }

  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <button
        onClick={() => replay()}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-lg border border-signal/40 bg-signal/15 px-3.5 py-2 text-[13px] font-medium text-signal transition-all hover:bg-signal/25 hover:shadow-glow disabled:opacity-60"
      >
        <IconPlay className="h-3.5 w-3.5" />
        {busy ? "Replaying…" : "Replay vs source"}
      </button>
      <div className="flex items-center gap-2">
        <input
          value={candidate}
          onChange={(e) => setCandidate(e.target.value)}
          placeholder="candidate trace_id (e.g. a fixed run)"
          className="w-[300px] rounded-lg border border-line bg-ink-900 px-3 py-2 font-mono text-[12px] text-fg placeholder:text-fg-faint focus:border-signal/50 focus:outline-none focus:ring-1 focus:ring-signal/30"
        />
        <button
          onClick={() => replay(candidate)}
          disabled={busy || !candidate}
          className="rounded-lg border border-line bg-ink-700 px-3.5 py-2 text-[13px] text-fg-muted transition-colors hover:border-line-bright hover:text-fg disabled:opacity-40"
        >
          Replay vs trace
        </button>
      </div>
      {result && (
        <Badge variant={result === "PASS" ? "ok" : "fail"} dot>
          {result}
        </Badge>
      )}
    </div>
  );
}
