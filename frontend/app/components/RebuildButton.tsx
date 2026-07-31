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
        className="btn-primary"
      >
        <IconBolt className="h-4 w-4" />
        {busy ? "Starting…" : "Analyze failures"}
      </button>
    </div>
  );
}
