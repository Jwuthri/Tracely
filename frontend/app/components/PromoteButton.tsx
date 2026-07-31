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
        className="btn-primary"
      >
        <IconPromote className="h-4 w-4" />
        {busy ? "Promoting…" : "Promote to regression test"}
      </button>
      {err && (
        <p role="alert" className="text-[12px] text-fail">
          {err}
        </p>
      )}
    </div>
  );
}
