"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconPromote } from "./icons";

export function ClusterActions({ clusterId, status }: { clusterId: string; status: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const router = useRouter();

  async function act(action: "promote" | "ignore") {
    setBusy(action);
    const r = await fetch("/api/cluster", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ clusterId, action }),
    });
    const d = await r.json();
    setBusy(null);
    if (action === "promote" && d?.case_id) router.push(`/cases/${d.case_id}`);
    else router.refresh();
  }

  if (status === "PROMOTED")
    return <span className="font-mono text-[12px] text-ok">promoted → case ✓</span>;
  if (status === "IGNORED") return <span className="font-mono text-[12px] text-fg-faint">ignored</span>;

  return (
    <div className="flex items-center gap-2.5">
      <button
        onClick={() => act("promote")}
        disabled={!!busy}
        className="inline-flex items-center gap-2 rounded-lg border border-signal/40 bg-signal/15 px-3.5 py-2 text-[13px] font-medium text-signal transition-all hover:bg-signal/25 hover:shadow-glow disabled:opacity-60"
      >
        <IconPromote className="h-4 w-4" />
        {busy === "promote" ? "Promoting…" : "Promote cluster to regression test"}
      </button>
      <button
        onClick={() => act("ignore")}
        disabled={!!busy}
        className="rounded-lg border border-line bg-ink-700 px-3.5 py-2 text-[13px] text-fg-muted transition-colors hover:border-line-bright hover:text-fg disabled:opacity-40"
      >
        {busy === "ignore" ? "…" : "Ignore"}
      </button>
    </div>
  );
}
