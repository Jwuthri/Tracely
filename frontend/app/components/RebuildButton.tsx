"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconBolt } from "./icons";

export function RebuildButton() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const router = useRouter();

  async function go() {
    setBusy(true);
    setMsg(null);
    const r = await fetch("/api/cluster-rebuild", { method: "POST" });
    const d = await r.json();
    setBusy(false);
    setMsg(r.ok ? "Analyzing… refresh in ~30s" : d?.detail ?? "failed");
    setTimeout(() => router.refresh(), 1500);
  }

  return (
    <div className="flex items-center gap-3">
      {msg && <span className="text-[12px] text-fg-faint">{msg}</span>}
      <button
        onClick={go}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-lg border border-signal/40 bg-signal/15 px-3.5 py-2 text-[13px] font-medium text-signal transition-all hover:bg-signal/25 hover:shadow-glow disabled:opacity-60"
      >
        <IconBolt className="h-4 w-4" />
        {busy ? "Starting…" : "Analyze failures"}
      </button>
    </div>
  );
}
