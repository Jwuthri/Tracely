"use client";

import { useState } from "react";

const inputCls =
  "w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-[13px] text-fg outline-none transition-colors focus:border-signal/50";

export function ChangePasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const canSubmit = current && next.length >= 8 && next === confirm && !busy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (next.length < 8) {
      setMsg({ kind: "err", text: "New password must be at least 8 characters." });
      return;
    }
    if (next !== confirm) {
      setMsg({ kind: "err", text: "New password and confirmation don't match." });
      return;
    }
    setBusy(true);
    try {
      const r = await fetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.ok) {
        setMsg({ kind: "ok", text: "Password updated." });
        setCurrent("");
        setNext("");
        setConfirm("");
      } else {
        setMsg({ kind: "err", text: d?.detail ?? "Could not update password." });
      }
    } catch {
      setMsg({ kind: "err", text: "Could not reach the server." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="max-w-sm space-y-3">
      <label className="block">
        <span className="mb-1 block text-[12px] text-fg-muted">Current password</span>
        <input
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          className={inputCls}
        />
      </label>
      <label className="block">
        <span className="mb-1 block text-[12px] text-fg-muted">New password</span>
        <input
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          className={inputCls}
          placeholder="at least 8 characters"
        />
      </label>
      <label className="block">
        <span className="mb-1 block text-[12px] text-fg-muted">Confirm new password</span>
        <input
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className={inputCls}
        />
      </label>

      {msg && (
        <div
          className={
            msg.kind === "ok"
              ? "rounded-lg border border-ok/25 bg-ok/10 px-3 py-2 text-[12.5px] text-ok"
              : "rounded-lg border border-fail/25 bg-fail/10 px-3 py-2 text-[12.5px] text-fail"
          }
        >
          {msg.text}
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-[12.5px] font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
      >
        {busy && <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />}
        {busy ? "Updating…" : "Update password"}
      </button>
    </form>
  );
}
