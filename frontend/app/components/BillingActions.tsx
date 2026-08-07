"use client";

import { useState } from "react";

/** The Stripe buttons on Settings → Billing. Both endpoints answer `{url}` and the browser
 *  follows it — checkout for a free workspace, the billing portal (card, cancel, invoices)
 *  once subscribed. Hidden entirely for viewers who can't manage billing (members, dev mode,
 *  ingest principals) — the backend enforces the same rule with a 403 regardless. */
export function BillingActions({ plan, canManage }: { plan: string; canManage: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (!canManage || plan === "unlimited") return null;

  async function go(endpoint: "checkout" | "portal") {
    setBusy(endpoint);
    setErr(null);
    try {
      const r = await fetch(`/api/billing/${endpoint}`, { method: "POST" });
      const d = await r.json().catch(() => null);
      if (!r.ok || !d?.url) {
        setErr(d?.detail ?? `Could not reach billing (HTTP ${r.status}).`);
        return;
      }
      window.location.assign(d.url);
    } catch {
      setErr("Could not reach billing: the server is unreachable.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 pt-1">
      {plan === "free" ? (
        <button onClick={() => go("checkout")} disabled={busy !== null} className="btn-primary">
          {busy === "checkout" ? "Opening checkout…" : "Upgrade to Pro"}
        </button>
      ) : (
        <button onClick={() => go("portal")} disabled={busy !== null} className="btn-primary">
          {busy === "portal" ? "Opening portal…" : "Manage subscription"}
        </button>
      )}
      {plan === "free" && (
        <span className="text-[12.5px] text-fg-faint">
          Pro raises the monthly trace quota and keeps everything else identical.
        </span>
      )}
      {err && (
        <p role="alert" className="text-[12px] text-fail">
          {err}
        </p>
      )}
    </div>
  );
}
