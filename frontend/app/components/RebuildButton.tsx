"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconBolt } from "./icons";

/** The clusters page's "Analyze failures" trigger. The job is async, so a missing OpenRouter key
 *  would otherwise be the classic silent no-op — "Analyzing…" forever, nothing appears. The page
 *  passes `hasLlmKey` (server-checked) so the button says why instead of pretending to work. */
export function RebuildButton({ hasLlmKey = true }: { hasLlmKey?: boolean }) {
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

  if (!hasLlmKey) {
    return (
      <div className="flex items-center gap-3">
        <span className="text-[12px] text-warn">
          Analyze needs your OpenRouter key —{" "}
          <a href="/settings/llm" className="underline underline-offset-2">
            add it in Settings
          </a>
        </span>
        <button disabled className="btn-primary opacity-50" title="Add an OpenRouter key first">
          <IconBolt className="h-4 w-4" />
          Analyze failures
        </button>
      </div>
    );
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
