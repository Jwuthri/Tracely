"use client";

import { useEffect, useState } from "react";
import { CopyId } from "./CopyId";

type Invite = { id: string; email: string; role: string; status: string; created_at: string | null };

export function InviteManager() {
  const [invites, setInvites] = useState<Invite[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("MEMBER");
  const [link, setLink] = useState<string | null>(null);
  const [emailed, setEmailed] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  async function load() {
    const r = await fetch("/api/auth/invite", { cache: "no-store" });
    if (r.ok) setInvites(await r.json());
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr(null);
    setLink(null);
    setEmailed(false);
    const r = await fetch("/api/auth/invite", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, role }),
    });
    const d = await r.json().catch(() => ({}));
    if (r.ok) {
      setLink(`${window.location.origin}/accept-invite?token=${d.token}`);
      setEmailed(!!d.emailed);
      setEmail("");
      load();
    } else {
      setErr(d.detail || "Could not create invite");
    }
    setLoading(false);
  }

  async function revoke(id: string) {
    if (!confirm("Revoke this invite? The link will stop working.")) return;
    setRevoking(id);
    const r = await fetch(`/api/auth/invite?id=${id}`, { method: "DELETE" });
    if (r.ok) await load();
    setRevoking(null);
  }

  // Hide revoked invites — the link is dead, so they're just clutter (still kept in the DB/API).
  const visible = invites.filter((i) => i.status !== "REVOKED");

  return (
    <div className="space-y-6">
      <section className="card p-5">
        <div className="mb-3 text-[13px] font-semibold text-fg">Invite a teammate</div>
        <form onSubmit={create} className="flex flex-wrap items-end gap-3">
          <label className="flex-1">
            <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-[0.18em] text-fg-faint">
              Email
            </span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="teammate@company.com"
              className="w-full rounded-lg border border-line bg-ink-800 px-3.5 py-2.5 text-[14px] text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-signal/50"
            />
          </label>
          <label>
            <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-[0.18em] text-fg-faint">
              Role
            </span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="rounded-lg border border-line bg-ink-800 px-3 py-2.5 text-[14px] text-fg outline-none focus:border-signal/50"
            >
              <option value="MEMBER">Member</option>
              <option value="ADMIN">Admin</option>
            </select>
          </label>
          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-signal px-4 py-2.5 text-[14px] font-semibold text-ink transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {loading ? "…" : "Create invite"}
          </button>
        </form>
        {err && <div className="mt-3 text-[12.5px] text-fail">{err}</div>}
        {link && (
          <div className="mt-4 rounded-lg border border-signal/30 bg-signal/5 p-3">
            <div className="mb-1.5 text-[11px] text-fg-muted">
              {emailed
                ? "Invite emailed — it lets them set a password and join. You can also share this link directly:"
                : "Share this link (shown once) — it lets them set a password and join:"}
            </div>
            <div className="flex items-center justify-between gap-3">
              <code className="truncate font-mono text-[12px] text-signal">{link}</code>
              <CopyId value={link} text="copy" label="invite link" />
            </div>
          </div>
        )}
      </section>

      <section className="card overflow-hidden">
        <div className="hairline px-4 py-3 text-[13px] font-semibold text-fg">Invitations</div>
        {visible.length === 0 ? (
          <div className="px-4 py-8 text-center text-[13px] text-fg-faint">No invitations yet.</div>
        ) : (
          visible.map((i) => (
            <div
              key={i.id}
              className="flex items-center justify-between border-b border-line/50 px-4 py-3 text-[13px] last:border-0"
            >
              <span className="text-fg">{i.email}</span>
              <span className="flex items-center gap-3 font-mono text-[11px] text-fg-faint">
                <span>{i.role}</span>
                <span
                  className={
                    i.status === "PENDING"
                      ? "text-warn"
                      : i.status === "ACCEPTED"
                        ? "text-ok"
                        : "text-fg-faint"
                  }
                >
                  {i.status.toLowerCase()}
                </span>
                {i.status === "PENDING" && (
                  <button
                    type="button"
                    onClick={() => revoke(i.id)}
                    disabled={revoking === i.id}
                    className="text-fg-faint underline-offset-2 transition-colors hover:text-fail hover:underline disabled:opacity-50"
                  >
                    {revoking === i.id ? "…" : "revoke"}
                  </button>
                )}
              </span>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
