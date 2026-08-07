"use client";

import clsx from "clsx";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Me } from "@/app/lib/auth/types";

const MODE = process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev";

// Clerk's UserButton, loaded only in clerk mode (kept out of the local/dev bundle entirely).
const ClerkUserButton =
  MODE === "clerk"
    ? dynamic(() => import("@clerk/nextjs").then((m) => ({ default: m.UserButton })), { ssr: false })
    : null;

export function AccountMenu({ me }: { me: Me | null }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Inline naming instead of window.prompt(), which browsers refuse to render in some contexts
  // ("prompt() is not supported") and which can't show the backend's 409 copy anyway.
  const [creating, setCreating] = useState<{ path: string; label: string } | null>(null);
  const [draft, setDraft] = useState("");
  const workspace = me?.project_name || "Workspace";
  const role = me?.role || (MODE === "dev" ? "dev" : "");
  const projects = me?.projects ?? [];
  const orgs = me?.organizations ?? [];
  const canCreate = MODE === "local" && (me?.role === "OWNER" || me?.role === "ADMIN");
  // Workspaces are listed under the account that owns them — with several accounts (a personal
  // one plus companies you've joined) the flat list gave no clue which tenant you were entering.
  const groups = orgs.map((o) => ({
    org: o,
    items: projects.filter((p) => p.organization_id === o.id),
  }));
  const ungrouped = projects.filter((p) => !orgs.some((o) => o.id === p.organization_id));

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }

  async function switchTo(id: string) {
    if (busy || id === me?.project_id) {
      setOpen(false);
      return;
    }
    setBusy(true);
    try {
      const r = await fetch("/api/auth/switch", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ project_id: id }),
      });
      if (r.ok) {
        setOpen(false);
        router.refresh();
      }
    } finally {
      setBusy(false);
    }
  }

  function startCreating(path: string, label: string) {
    setCreating({ path, label });
    setDraft("");
    setError("");
  }

  /** POST the create action, surfacing the backend's message — the plan caps answer 409 with copy
   *  that tells the user what to do about it ("upgrade", "create an organization"). */
  async function submitCreate() {
    const name = draft.trim();
    if (!name || !creating) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch(creating.path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (r.ok) {
        setCreating(null);
        setOpen(false);
        router.refresh();
      } else {
        const body = await r.json().catch(() => null);
        setError(body?.detail || "Could not create that. Try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between rounded-lg border border-line bg-ink-800 px-3 py-2 text-left transition-colors hover:border-line-bright"
      >
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[12.5px] text-fg">{workspace}</div>
          <div className="truncate font-mono text-[9.5px] uppercase tracking-wider text-fg-faint">
            {me?.organization_name ? `${me.organization_name} · ${role}` : role || "workspace"}
          </div>
        </div>
        {MODE === "clerk" && ClerkUserButton ? (
          <ClerkUserButton />
        ) : (
          <span className="ml-2 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-signal/15 font-mono text-[11px] font-semibold text-signal">
            {(me?.email || "T").slice(0, 1).toUpperCase()}
          </span>
        )}
      </button>

      {open && MODE !== "clerk" && (
        <div className="absolute bottom-full left-0 z-30 mb-2 w-full overflow-hidden rounded-lg border border-line bg-ink-800 shadow-xl">
          {me?.email && (
            <div className="truncate border-b border-line/60 px-3 py-2 text-[11px] text-fg-faint">
              {me.email}
            </div>
          )}

          {projects.length > 0 && (
            <div className="border-b border-line/60 py-1">
              {[...groups, ...(ungrouped.length ? [{ org: null, items: ungrouped }] : [])].map(
                ({ org, items }) =>
                  items.length === 0 ? null : (
                    <div key={org?.id ?? "_"}>
                      <div className="flex items-baseline justify-between gap-2 px-3 pb-1 pt-1.5">
                        <span className="truncate font-mono text-[9.5px] uppercase tracking-wider text-fg-faint">
                          {org?.name ?? "Workspaces"}
                        </span>
                        {org && (
                          <span className="shrink-0 font-mono text-[9px] uppercase tracking-wider text-fg-faint">
                            {org.kind === "personal" ? "personal" : org.plan}
                          </span>
                        )}
                      </div>
                      {items.map((p) => (
                        <button
                          key={p.id}
                          onClick={() => switchTo(p.id)}
                          disabled={busy}
                          className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left transition-colors hover:bg-white/[0.04] disabled:opacity-50"
                        >
                          <span
                            className={clsx(
                              "truncate pl-1.5 text-[12.5px]",
                              p.id === me?.project_id ? "text-fg" : "text-fg-muted",
                            )}
                          >
                            {p.name}
                          </span>
                          {p.id === me?.project_id && (
                            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-signal" />
                          )}
                        </button>
                      ))}
                    </div>
                  ),
              )}
              {creating ? (
                <div className="px-3 py-2">
                  <label className="mb-1 block font-mono text-[9.5px] uppercase tracking-wider text-fg-faint">
                    {creating.label}
                  </label>
                  <input
                    autoFocus
                    value={draft}
                    disabled={busy}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") submitCreate();
                      if (e.key === "Escape") setCreating(null);
                    }}
                    placeholder="Name"
                    className="w-full rounded-md border border-line bg-ink-900 px-2 py-1.5 text-[12.5px] text-fg outline-none placeholder:text-fg-faint focus:border-signal/50 disabled:opacity-50"
                  />
                  <div className="mt-1.5 flex gap-2">
                    <button
                      onClick={submitCreate}
                      disabled={busy || !draft.trim()}
                      className="rounded-md bg-signal px-2.5 py-1 text-[11.5px] font-semibold text-ink transition-opacity hover:opacity-90 disabled:opacity-50"
                    >
                      {busy ? "…" : "Create"}
                    </button>
                    <button
                      onClick={() => setCreating(null)}
                      disabled={busy}
                      className="rounded-md px-2 py-1 text-[11.5px] text-fg-muted transition-colors hover:text-fg"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {canCreate && (
                    <button
                      onClick={() => startCreating("/api/auth/projects", "New workspace")}
                      className="block w-full px-3 py-1.5 text-left text-[12.5px] text-signal transition-colors hover:bg-signal/10"
                    >
                      + New workspace
                    </button>
                  )}
                  {MODE === "local" && !!me?.user_id && me.can_create_organization && (
                    <button
                      onClick={() => startCreating("/api/auth/organizations", "New organization")}
                      className="block w-full px-3 py-1.5 text-left text-[12.5px] text-signal transition-colors hover:bg-signal/10"
                    >
                      + New organization
                    </button>
                  )}
                </>
              )}
              {error && (
                <p role="alert" className="px-3 py-1.5 text-[11.5px] leading-snug text-fail">
                  {error}
                </p>
              )}
            </div>
          )}

          {/* Workspace settings live in the sidebar's Configure group — this menu is the account:
              who you're signed in as, which workspace, and how to leave. */}
          {MODE === "local" && me?.user_id && (
            <a
              href="/settings/account"
              className="block px-3 py-2 text-[12.5px] text-fg-muted transition-colors hover:bg-white/[0.04] hover:text-fg"
            >
              Change password
            </a>
          )}
          {MODE === "local" && (
            <button
              onClick={signOut}
              className="block w-full px-3 py-2 text-left text-[12.5px] text-fail transition-colors hover:bg-fail/10"
            >
              Sign out
            </button>
          )}
        </div>
      )}
    </div>
  );
}
