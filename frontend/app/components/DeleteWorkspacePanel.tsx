"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Danger zone, one step past the wipe: removes the workspace itself. Confirmation is the
 *  workspace's own NAME rather than a fixed word — the two panels sit next to each other, and
 *  muscle-memory typing "DELETE" should not be able to destroy the workspace. */
export function DeleteWorkspacePanel({
  name,
  onlyWorkspace,
}: {
  name: string;
  onlyWorkspace: boolean;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const router = useRouter();

  async function go() {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/project/delete", {
        method: "DELETE",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ confirm: typed }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `Delete failed (HTTP ${r.status})`);
        return;
      }
      // The proxy already moved the active-workspace cookie to the surviving sibling; a full
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
        Delete this workspace
      </div>
      <div className="space-y-4 p-5">
        <p className="text-[13.5px] leading-relaxed text-fg-muted">
          Removes <span className="font-medium text-fg">{name}</span> entirely — its traces and
          blobs, its ingest keys, evaluators and monitors, and the workspace itself. Your
          organization, its members and its other workspaces are untouched, and this month&apos;s
          usage still counts against the account.
        </p>

        {onlyWorkspace ? (
          <p className="rounded-lg border border-line bg-ink-900 px-3.5 py-3 text-[13px] text-fg-muted">
            This is your organization&apos;s only workspace, so it can&apos;t be deleted — everyone
            in the organization reaches Tracely through it. Create another workspace first.
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
                {busy ? "Deleting…" : "Delete workspace"}
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
