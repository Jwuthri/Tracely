"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconX } from "./icons";

export function DeleteCaseButton({ caseId, title }: { caseId: string; title: string }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const router = useRouter();

  async function go() {
    if (
      !window.confirm(
        `Delete "${title || caseId}"? Its replay history goes too. The source trace stays — promote it again to recreate the case.`,
      )
    )
      return;
    setBusy(true);
    setErr(null);
    const r = await fetch(`/api/cases/${caseId}`, { method: "DELETE" });
    if (r.ok) {
      router.push("/cases");
      router.refresh();
      return;
    }
    const d = await r.json().catch(() => null);
    setErr(d?.detail ?? `Delete failed (HTTP ${r.status})`);
    setBusy(false);
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <button
        onClick={go}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-lg border border-line bg-ink-700 px-3 py-2 text-[13px] text-fg-muted transition-colors hover:border-fail/50 hover:text-fail disabled:opacity-40"
      >
        <IconX className="h-4 w-4" />
        {busy ? "Deleting…" : "Delete case"}
      </button>
      {err && (
        <p role="alert" className="text-[12px] text-rose-400">
          {err}
        </p>
      )}
    </div>
  );
}
