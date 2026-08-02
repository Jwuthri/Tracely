"use client";

import { useEffect, useState } from "react";
import type { AgentEndpoint } from "@/app/lib/api";
import { Badge } from "./ui";

const FIELD =
  "w-full rounded-lg border border-line bg-ink-700 px-2.5 py-2 font-mono text-[12.5px] text-fg placeholder:text-fg-faint transition-colors hover:border-line-bright focus:border-signal/50 focus:outline-none";
const LABEL = "font-mono text-[10px] uppercase tracking-wider text-fg-faint";

/** Where Tracely calls this agent. The token is write-only: it is Fernet-encrypted server-side and
 *  the GET only ever reports `has_token`, so an existing token is never rendered back into the
 *  browser — leaving the field blank on an update keeps the stored one. */
export function EndpointPanel({
  agentSlug,
  onConfigured,
}: {
  agentSlug: string;
  onConfigured: (configured: boolean) => void;
}) {
  const [ep, setEp] = useState<AgentEndpoint | null>(null);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [replyPath, setReplyPath] = useState("");
  // Set when the ENDPOINT mints the session id and expects it echoed (see the label).
  const [sessionPath, setSessionPath] = useState("");
  const [extraBody, setExtraBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let live = true;
    setEp(null);
    setErr(null);
    setSaved(false);
    fetch(`/api/agents/${encodeURIComponent(agentSlug)}/endpoint`)
      .then((r) => r.json())
      .then((d: AgentEndpoint) => {
        if (!live) return;
        setEp(d);
        setUrl(d.url ?? "");
        setReplyPath(d.reply_path ?? "");
        setSessionPath(d.session_path ?? "");
        setExtraBody(
          d.extra_body && Object.keys(d.extra_body).length
            ? JSON.stringify(d.extra_body, null, 2)
            : "",
        );
        setToken("");
        setOpen(!d.configured); // nothing set up yet → open the form straight away
        onConfigured(Boolean(d.configured));
      })
      .catch(() => live && setErr("Could not load the endpoint config."));
    return () => {
      live = false;
    };
  }, [agentSlug, onConfigured]);

  async function save() {
    // Parse before any network call: a typo in the JSON should be an inline message, not a
    // 400 round-trip, and definitely not a body that breaks every future conversation.
    let parsedBody: unknown = {};
    if (extraBody.trim()) {
      try {
        parsedBody = JSON.parse(extraBody);
      } catch {
        setErr("Extra body fields must be valid JSON.");
        return;
      }
      if (parsedBody === null || typeof parsedBody !== "object" || Array.isArray(parsedBody)) {
        setErr("Extra body fields must be a JSON object, e.g. {\"tenant_id\": \"acme\"}.");
        return;
      }
    }
    setBusy(true);
    setErr(null);
    setSaved(false);
    try {
      const r = await fetch(`/api/agents/${encodeURIComponent(agentSlug)}/endpoint`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          url,
          token: token || undefined,
          reply_path: replyPath,
          session_path: sessionPath,
          extra_body: parsedBody,
        }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `Could not save (HTTP ${r.status})`);
        return;
      }
      setEp({ ...(ep ?? { agent_id: "" }), configured: true, url, has_token: d?.has_token });
      setToken("");
      setSaved(true);
      setOpen(false);
      onConfigured(true);
    } catch {
      setErr("Could not save: the server is unreachable.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="text-[13px] font-semibold text-fg">Agent endpoint</span>
          {ep &&
            (ep.configured ? (
              <Badge variant="ok" dot>
                configured
              </Badge>
            ) : (
              <Badge variant="warn" dot>
                not set
              </Badge>
            ))}
          {saved && <span className="font-mono text-[11px] text-ok">saved</span>}
        </div>
        <button onClick={() => setOpen((o) => !o)} className="btn-ghost text-[12.5px]">
          {open ? "Cancel" : ep?.configured ? "Edit" : "Set up"}
        </button>
      </div>

      {!open && ep?.configured && (
        <div className="grid gap-3 px-4 py-3 sm:grid-cols-[1fr_auto]">
          <div className="min-w-0">
            <div className={LABEL}>URL</div>
            <div className="mt-1 truncate font-mono text-[12.5px] text-fg">{ep.url}</div>
          </div>
          <div>
            <div className={LABEL}>Auth</div>
            <div className="mt-1 font-mono text-[12.5px] text-fg-muted">
              {ep.has_token ? "bearer token stored" : "none"}
            </div>
          </div>
        </div>
      )}

      {!open && ep && !ep.configured && (
        <p className="px-4 py-4 text-[12.5px] text-fg-faint">
          Scenarios can&apos;t run until Tracely knows where to reach this agent.
        </p>
      )}

      {open && (
        <div className="space-y-3 px-4 py-4">
          <div>
            <label className={LABEL} htmlFor="ep-url">
              URL
            </label>
            <input
              id="ep-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://staging.example.com/agent/chat"
              className={`${FIELD} mt-1`}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor="ep-token">
                Bearer token {ep?.has_token && <span className="text-fg-faint">(stored)</span>}
              </label>
              <input
                id="ep-token"
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder={ep?.has_token ? "leave blank to keep" : "optional"}
                className={`${FIELD} mt-1`}
              />
            </div>
            <div>
              <label className={LABEL} htmlFor="ep-reply">
                Reply path <span className="text-fg-faint">(optional)</span>
              </label>
              <input
                id="ep-reply"
                value={replyPath}
                onChange={(e) => setReplyPath(e.target.value)}
                placeholder="auto-detects OpenAI / reply / output"
                className={`${FIELD} mt-1`}
              />
            </div>
          </div>
          <div>
            <label className={LABEL} htmlFor="ep-session">
              Session path <span className="text-fg-faint">(optional)</span>
            </label>
            <input
              id="ep-session"
              value={sessionPath}
              onChange={(e) => setSessionPath(e.target.value)}
              placeholder="session_id — only if your API mints the session"
              className={`${FIELD} mt-1`}
            />
            <p className="mt-1 text-[11.5px] text-fg-faint">
              Leave blank if your API accepts a session id we supply. Set it when the API returns
              its own: turn 1 sends none, and every later turn echoes back what came out of this
              path — otherwise each turn starts a fresh conversation.
            </p>
          </div>
          <div>
            <label className={LABEL} htmlFor="ep-body">
              Extra body fields <span className="text-fg-faint">(optional JSON)</span>
            </label>
            <textarea
              id="ep-body"
              value={extraBody}
              onChange={(e) => setExtraBody(e.target.value)}
              rows={3}
              placeholder={'{"tenant_id": "acme", "locale": "en"}'}
              className={`${FIELD} mt-1 resize-y leading-relaxed`}
            />
            <p className="mt-1 text-[12px] text-fg-faint">
              Merged into every request. Query params don&apos;t need this — put them in the URL.
            </p>
          </div>
          <p className="text-[12px] leading-relaxed text-fg-faint">
            Tracely POSTs <code className="text-fg-muted">{`{messages, conversation_id}`}</code> and
            sends a <code className="text-fg-muted">traceparent</code> header. If your service is
            OTel-instrumented it continues that trace, so its tool calls nest inside the graded
            conversation.
          </p>
          <div className="flex items-center gap-3">
            <button onClick={save} disabled={busy || !url.trim()} className="btn-primary">
              {busy ? "Saving…" : "Save endpoint"}
            </button>
            {err && (
              <p role="alert" className="text-[12px] text-fail">
                {err}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
