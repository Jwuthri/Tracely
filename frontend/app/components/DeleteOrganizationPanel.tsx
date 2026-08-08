"use client";

import { useState } from "react";

/** The last step of the danger ladder: wipe data → delete workspace → delete the organization.
 *  Confirmation is the organization's own NAME, so muscle memory from the other panels can't
 *  destroy an account. */
export function DeleteOrganizationPanel({
  name,
  canDelete,
}: {
  name: string;
  canDelete: boolean;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/auth/organizations", {
        method: "DELETE",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ confirm: typed }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `Delete failed (HTTP ${r.status})`);
        return;
      }
      // The proxy moved the active-workspace cookie to a workspace that still exists; a full
      // navigation re-reads it everywhere rather than leaving stale server components behind.
      window.location.href = "/dashboard";
    } catch {
      setErr("Delete failed: could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card overflow-hidden border-fail/30">
      <div className="hairline border-fail/20 bg-fail-dim/20 px-4 py-3 text-[13px] font-semibold text-fail">
        Delete this organization
      </div>
      <div className="space-y-4 p-5">
        <p className="text-[13.5px] leading-relaxed text-fg-muted">
          Removes <span className="font-medium text-fg">{name}</span> and{" "}
          <span className="font-medium text-fg">every workspace in it</span> — all traces and
          blobs, ingest keys, evaluators and monitors, plus the members&apos; access and any
          pending invites. Their accounts and personal workspaces are untouched.
        </p>

        {!canDelete ? (
          <p className="rounded-lg border border-line bg-ink-900 px-3.5 py-3 text-[13px] text-fg-muted">
            Only the organization&apos;s owner can delete it.
          </p>
        ) : (
          <>
            <p className="text-[13px] text-fg-faint">
              This cannot be undone. Type <span className="font-mono text-fg">{name}</span> to
              enable the button.
            </p>
            <div className="flex flex-wrap items-center gap-2.5">
              <input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={name}
                aria-label={`Type ${name} to confirm`}
                className="w-56 rounded-lg border border-line bg-ink-900 px-3 py-2 font-mono text-[13px] text-fg placeholder:text-fg-faint focus:border-fail/50 focus:outline-none"
              />
              <button
                onClick={go}
                disabled={typed !== name || busy}
                className="rounded-lg border border-fail/40 bg-fail/15 px-3.5 py-2 text-[13px] font-medium text-fail transition-colors hover:bg-fail/25 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy ? "Deleting…" : "Delete organization"}
              </button>
            </div>
          </>
        )}

        {err && (
          <p role="alert" className="text-[12.5px] text-fail">
            {err}
          </p>
        )}
      </div>
    </section>
  );
}
