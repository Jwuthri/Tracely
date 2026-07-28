"use client";

import { useState } from "react";
import { IconCheck, IconCopy } from "./icons";

/** Mint a public link for a conversation and copy it. The link is unlisted, read-only, and expires
 *  on its own — there is no revoke, so the warning below is not decoration. */
export function ShareButton({ threadId }: { threadId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);
  const [copied, setCopied] = useState(false);

  async function mint() {
    if (busy) return;
    setBusy(true);
    setErr(false);
    try {
      const r = await fetch("/api/share", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threadId }),
      });
      const j = await r.json();
      if (!r.ok || !j.token) throw new Error(j.detail ?? "failed");
      const link = `${window.location.origin}/share/${j.token}`;
      setUrl(link);
      await copy(link);
    } catch {
      setErr(true);
    } finally {
      setBusy(false);
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked (insecure origin / permissions) — the input below is selectable */
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <button
        type="button"
        onClick={() => (url ? copy(url) : mint())}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-fg-muted transition-colors hover:border-signal/40 hover:text-fg disabled:opacity-50"
      >
        {copied ? <IconCheck className="h-3.5 w-3.5 text-ok" /> : <IconCopy className="h-3.5 w-3.5" />}
        {busy ? "Creating…" : copied ? "Link copied" : url ? "Copy link" : "Share"}
      </button>

      {url && (
        <div className="flex flex-col gap-1">
          <input
            readOnly
            value={url}
            onFocus={(e) => e.currentTarget.select()}
            className="w-[min(28rem,80vw)] rounded-md border border-line bg-ink-900 px-2 py-1 font-mono text-[11px] text-fg-muted"
          />
          <span className="text-[11px] text-fg-faint">
            Anyone with this link can read the full conversation. Expires in 30 days; it cannot be
            revoked before then.
          </span>
        </div>
      )}
      {err && <span className="text-[11px] text-fail">Couldn&apos;t create a link — try again.</span>}
    </div>
  );
}
