"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconGate } from "./icons";

export function RunGateButton({ agent = "planner" }: { agent?: string }) {
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function go() {
    setBusy(true);
    const r = await fetch("/api/gate", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ agent, env: "ci" }),
    });
    const d = await r.json();
    setBusy(false);
    if (d?.id) router.push(`/gates/${d.id}`);
    else alert("Gate failed: " + (d?.detail ?? "unknown error"));
  }

  return (
    <button
      onClick={go}
      disabled={busy}
      className="inline-flex items-center gap-2 rounded-lg border border-signal/40 bg-signal/15 px-3.5 py-2 text-[13px] font-medium text-signal transition-all hover:bg-signal/25 hover:shadow-glow disabled:opacity-60"
    >
      <IconGate className="h-4 w-4" />
      {busy ? "Running gate…" : `Run gate · ${agent} · ci`}
    </button>
  );
}
