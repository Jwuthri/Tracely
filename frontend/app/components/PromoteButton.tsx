"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconPromote } from "./icons";

export function PromoteButton({ traceId }: { traceId: string }) {
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function go() {
    setBusy(true);
    const r = await fetch("/api/promote", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ traceId }),
    });
    const data = await r.json();
    setBusy(false);
    if (data?.id) router.push(`/cases/${data.id}`);
    else alert("Promote failed: " + (data?.detail ?? "unknown error"));
  }

  return (
    <button
      onClick={go}
      disabled={busy}
      className="inline-flex items-center gap-2 rounded-lg border border-signal/40 bg-signal/15 px-3.5 py-2 text-[13px] font-medium text-signal transition-all hover:bg-signal/25 hover:shadow-glow disabled:opacity-60"
    >
      <IconPromote className="h-4 w-4" />
      {busy ? "Promoting…" : "Promote to regression test"}
    </button>
  );
}
