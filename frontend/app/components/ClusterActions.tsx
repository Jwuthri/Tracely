"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconPromote } from "./icons";

export function ClusterActions({ clusterId, status }: { clusterId: string; status: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const router = useRouter();

  async function act(action: "promote" | "ignore") {
    setBusy(action);
    setError("");
    try {
      const r = await fetch("/api/cluster", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ clusterId, action }),
      });
      const d = await r.json().catch(() => ({}));
      // Without this the button was a silent no-op on every failure: a 404 body has no
      // `case_id`, so it fell through to refresh() and the page re-rendered unchanged.
      if (!r.ok) throw new Error(d?.detail ?? `${action} failed (${r.status})`);
      if (action === "promote" && d?.case_id) router.push(`/cases/${d.case_id}`);
      else router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : `${action} failed`);
    } finally {
      setBusy(null);
    }
  }

  if (status === "PROMOTED")
    return <span className="font-mono text-[12px] text-ok">promoted → case ✓</span>;
  if (status === "IGNORED") return <span className="font-mono text-[12px] text-fg-faint">ignored</span>;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2.5">
        <button onClick={() => act("promote")} disabled={!!busy} className="btn-primary">
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
      {error && (
        <p role="alert" className="text-[12.5px] text-fail">
          {error}
        </p>
      )}
    </div>
  );
}
