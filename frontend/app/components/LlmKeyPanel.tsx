"use client";

import { useEffect, useState } from "react";

type Status = "loading" | "unset" | "set";

/** Settings -> LLM key: a workspace's own OpenRouter key for its eval spend (judge, failure
 *  intelligence, meta-analysis, rolling summary), instead of billing to ours. The key is only
 *  ever sent once — after saving, the server shows "configured", never the value again. */
export function LlmKeyPanel() {
  const [status, setStatus] = useState<Status>("loading");
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/project/llm-key", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setStatus(d?.configured ? "set" : "unset"))
      .catch(() => setStatus("unset"));
  }, []);

  async function save() {
    if (!value.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/project/llm-key", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ api_key: value.trim() }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `Save failed (HTTP ${r.status})`);
        return;
      }
      setStatus("set");
      setEditing(false);
      setValue("");
    } catch {
      setErr("Save failed: could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/project/llm-key", { method: "DELETE" });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        setErr(d?.detail ?? `Remove failed (HTTP ${r.status})`);
        return;
      }
      setStatus("unset");
    } catch {
      setErr("Remove failed: could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card overflow-hidden">
      <div className="hairline px-4 py-3 text-[13px] font-semibold text-fg">OpenRouter key</div>
      <div className="space-y-4 p-5">
        <p className="text-[13.5px] leading-relaxed text-fg-muted">
          Required. Every LLM-backed feature — judge evaluators, clustering and failure
          intelligence, meta-analysis, rolling summary, scenario gates — runs on this workspace's
          own OpenRouter key and bills to your account. Without one, those features stay off.
        </p>

        {status === "unset" && (
          <p className="rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-[13px] text-warn">
            No key configured — LLM evaluations and clustering will not run.
          </p>
        )}

        {status === "loading" && <p className="text-[13px] text-fg-faint">Loading…</p>}

        {status === "set" && !editing && (
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="rounded-lg border border-ok/30 bg-ok/10 px-3 py-2 text-[13px] text-ok">
              A workspace key is configured
            </span>
            <button
              onClick={() => setEditing(true)}
              disabled={busy}
              className="rounded-lg border border-line bg-ink-800 px-3.5 py-2 text-[13px] font-medium text-fg transition-colors hover:border-line-bright disabled:cursor-not-allowed disabled:opacity-40"
            >
              Replace
            </button>
            <button
              onClick={remove}
              disabled={busy}
              className="rounded-lg border border-fail/40 bg-fail/15 px-3.5 py-2 text-[13px] font-medium text-fail transition-colors hover:bg-fail/25 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? "Removing…" : "Remove"}
            </button>
          </div>
        )}

        {(status === "unset" || editing) && (
          <div className="flex flex-wrap items-center gap-2.5">
            <input
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="sk-or-v1-…"
              aria-label="OpenRouter API key"
              className="w-72 max-w-full rounded-lg border border-line bg-ink-900 px-3 py-2 font-mono text-[13px] text-fg placeholder:text-fg-faint focus:border-signal/50 focus:outline-none"
            />
            <button
              onClick={save}
              disabled={!value.trim() || busy}
              className="rounded-lg border border-signal/40 bg-signal/15 px-3.5 py-2 text-[13px] font-medium text-signal transition-colors hover:bg-signal/25 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? "Saving…" : "Save key"}
            </button>
            {editing && (
              <button
                onClick={() => {
                  setEditing(false);
                  setValue("");
                  setErr(null);
                }}
                disabled={busy}
                className="text-[13px] text-fg-faint transition-colors hover:text-fg-muted"
              >
                Cancel
              </button>
            )}
          </div>
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
