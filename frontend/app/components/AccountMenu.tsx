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
  const workspace = me?.project_name || "Workspace";
  const role = me?.role || (MODE === "dev" ? "dev" : "");
  const canInvite = MODE === "local" && (me?.role === "OWNER" || me?.role === "ADMIN");
  const projects = me?.projects ?? [];
  const canCreate = MODE === "local" && !!me?.user_id;

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

  async function createWorkspace() {
    const name = window.prompt("New workspace name")?.trim();
    if (!name) return;
    setBusy(true);
    try {
      const r = await fetch("/api/auth/projects", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (r.ok) {
        setOpen(false);
        router.refresh();
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
          <div className="font-mono text-[9.5px] uppercase tracking-wider text-fg-faint">
            {role || "workspace"}
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
              <div className="px-3 pb-1 pt-1.5 font-mono text-[9.5px] uppercase tracking-wider text-fg-faint">
                Workspaces
              </div>
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => switchTo(p.id)}
                  disabled={busy}
                  className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left transition-colors hover:bg-white/[0.04] disabled:opacity-50"
                >
                  <span
                    className={clsx(
                      "truncate text-[12.5px]",
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
              {canCreate && (
                <button
                  onClick={createWorkspace}
                  disabled={busy}
                  className="block w-full px-3 py-1.5 text-left text-[12.5px] text-signal transition-colors hover:bg-signal/10 disabled:opacity-50"
                >
                  + New workspace
                </button>
              )}
            </div>
          )}

          <a
            href="/settings/api-keys"
            className="block px-3 py-2 text-[12.5px] text-fg-muted transition-colors hover:bg-white/[0.04] hover:text-fg"
          >
            Settings · API keys
          </a>
          {MODE === "local" && me?.user_id && (
            <a
              href="/settings/account"
              className="block px-3 py-2 text-[12.5px] text-fg-muted transition-colors hover:bg-white/[0.04] hover:text-fg"
            >
              Change password
            </a>
          )}
          {canInvite && (
            <a
              href="/settings/team"
              className="block px-3 py-2 text-[12.5px] text-fg-muted transition-colors hover:bg-white/[0.04] hover:text-fg"
            >
              Invite teammates
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
