"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconPromote } from "./icons";

export function PromoteButton({ traceId }: { traceId: string }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const router = useRouter();

  async function go() {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/promote", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ traceId }),
      });
      const data = await r.json().catch(() => null);
      if (r.ok && data?.id) {
        router.push(`/cases/${data.id}`);
        return;
      }
      setErr(data?.detail ?? `Promote failed (HTTP ${r.status})`);
    } catch {
      setErr("Promote failed: could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-1.5">
      <button
        onClick={go}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-lg border border-signal/40 bg-signal/15 px-3.5 py-2 text-[13px] font-medium text-signal transition-all hover:bg-signal/25 hover:shadow-glow disabled:opacity-60"
      >
        <IconPromote className="h-4 w-4" />
        {busy ? "Promoting…" : "Promote to regression test"}
      </button>
      {err && (
        <p role="alert" className="text-[12px] text-rose-400">
          {err}
        </p>
      )}
    </div>
  );
}
