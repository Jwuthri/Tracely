"use client";

import clsx from "clsx";
import { useEffect, useState } from "react";
import type { SpanOut, Thread, ThreadTurn } from "../lib/api";
import { resolvePromptPreview, type EvaluatorLevel, type ResolvedPreview } from "../lib/evaluators";
import { catalogLevel } from "../lib/templateVariables";
import { Markdown } from "./Markdown";

// Live preview: resolve the advanced @VARIABLE prompt against a real conversation/turn/step and
// show the result with used (green) / missing (amber) badges. Navigation reuses the existing
// /api/sessions + /api/trace proxies; resolution hits /api/evaluators/resolve (no LLM).

function clip(s: string | null | undefined, n = 56): string {
  const t = (s ?? "").replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t || "(empty)";
}

const selectCls =
  "min-w-0 flex-1 rounded-md border border-line bg-ink-900/60 px-2 py-1.5 text-[11.5px] text-fg-muted focus:border-signal/40 focus:outline-none";

export function PromptPreview({
  prompt,
  level,
  defaultThread,
}: {
  prompt: string;
  level: EvaluatorLevel;
  defaultThread?: string;
}) {
  const cl = catalogLevel(level);
  const [threads, setThreads] = useState<Thread[] | null>(null);
  const [thread, setThread] = useState<string>(defaultThread ?? "");
  const [turns, setTurns] = useState<ThreadTurn[]>([]);
  const [trace, setTrace] = useState<string>("");
  const [spans, setSpans] = useState<SpanOut[]>([]);
  const [span, setSpan] = useState<string>("");
  const [result, setResult] = useState<ResolvedPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [raw, setRaw] = useState(false);

  // conversations (once)
  useEffect(() => {
    let alive = true;
    fetch("/api/sessions?limit=25", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Thread[]) => {
        if (!alive) return;
        setThreads(list);
        setThread((t) => t || list.find((x) => x.thread === defaultThread)?.thread || list[0]?.thread || "");
      })
      .catch(() => alive && setThreads([]));
    return () => { alive = false; };
  }, [defaultThread]);

  // turns of the chosen conversation (message / step levels)
  useEffect(() => {
    if (!thread || cl === "conversation") { setTurns([]); setTrace(""); return; }
    let alive = true;
    fetch(`/api/sessions/${encodeURIComponent(thread)}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { turns: [] }))
      .then((d: { turns?: ThreadTurn[] }) => {
        if (!alive) return;
        const ts = d.turns ?? [];
        setTurns(ts);
        setTrace(ts[0]?.trace_id ?? "");
      })
      .catch(() => alive && setTurns([]));
    return () => { alive = false; };
  }, [thread, cl]);

  // steps of the chosen turn (step level)
  useEffect(() => {
    if (!trace || cl !== "step") { setSpans([]); setSpan(""); return; }
    let alive = true;
    fetch(`/api/trace?id=${encodeURIComponent(trace)}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { spans: [] }))
      .then((d: { spans?: SpanOut[] }) => {
        if (!alive) return;
        const ss = d.spans ?? [];
        setSpans(ss);
        setSpan(ss[0]?.span_id ?? "");
      })
      .catch(() => alive && setSpans([]));
    return () => { alive = false; };
  }, [trace, cl]);

  // debounced resolve
  useEffect(() => {
    if (!prompt.trim() || !thread) { setResult(null); return; }
    const id = setTimeout(() => {
      setLoading(true);
      setError("");
      resolvePromptPreview({
        prompt,
        level,
        thread_id: thread,
        trace_id: cl !== "conversation" ? trace : undefined,
        span_id: cl === "step" ? span : undefined,
      })
        .then(setResult)
        .catch((e) => setError(e instanceof Error ? e.message : "preview failed"))
        .finally(() => setLoading(false));
    }, 500);
    return () => clearTimeout(id);
  }, [prompt, level, thread, trace, span, cl]);

  return (
    <div className="space-y-2 rounded-lg border border-line bg-ink-900/40 p-3">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[10.5px] font-medium uppercase tracking-wider text-fg-faint">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="h-3 w-3">
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" />
          </svg>
          Preview
        </span>
        {loading && <span className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-fg-faint" />}
      </div>

      {/* navigation */}
      {threads === null ? (
        <p className="text-[11px] text-fg-faint">Loading conversations…</p>
      ) : threads.length === 0 ? (
        <p className="text-[11px] text-fg-faint">No conversations to preview against yet.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <select className={selectCls} value={thread} onChange={(e) => setThread(e.target.value)}>
            {threads.map((t) => (
              <option key={t.thread} value={t.thread}>Conv · {clip(t.first_input)}</option>
            ))}
          </select>
          {cl !== "conversation" && (
            <select className={selectCls} value={trace} onChange={(e) => setTrace(e.target.value)}>
              {turns.map((t, i) => (
                <option key={t.trace_id} value={t.trace_id}>Turn {i + 1} · {clip(t.input)}</option>
              ))}
            </select>
          )}
          {cl === "step" && (
            <select className={selectCls} value={span} onChange={(e) => setSpan(e.target.value)}>
              {spans.map((s, i) => (
                <option key={s.span_id} value={s.span_id}>{i + 1}. {s.type} {clip(s.name, 20)}</option>
              ))}
            </select>
          )}
        </div>
      )}

      {/* used / missing badges */}
      {result && (result.variables_used.length > 0 || result.variables_missing.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {result.variables_used.length > 0 && (
            <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[9.5px] font-medium text-emerald-400">
              Resolved: {result.variables_used.join(", ")}
            </span>
          )}
          {result.variables_missing.length > 0 && (
            <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[9.5px] font-medium text-amber-400">
              Missing: {result.variables_missing.join(", ")}
            </span>
          )}
        </div>
      )}

      {/* resolved prompt (exactly what the judge will receive) */}
      {error ? (
        <p className="text-[11px] text-fail">{error}</p>
      ) : !prompt.trim() ? (
        <p className="text-[11px] text-fg-faint">Write a prompt with <span className="font-mono text-emerald-400">@variables</span> to preview the resolved text.</p>
      ) : result ? (
        <>
          {raw ? (
            <pre
              className={clsx(
                "overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-ink-950/60 p-2.5 font-mono text-[11px] leading-relaxed text-fg-muted",
                expanded ? "max-h-96" : "max-h-44",
              )}
            >
              {result.resolved_prompt}
            </pre>
          ) : (
            <div
              className={clsx(
                "overflow-auto rounded-md border border-line bg-ink-950/60 p-2.5",
                expanded ? "max-h-96" : "max-h-44",
              )}
            >
              <Markdown content={result.resolved_prompt} className="space-y-1.5" />
            </div>
          )}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setExpanded((x) => !x)}
              className="text-[10.5px] text-fg-faint transition-colors hover:text-fg-muted"
            >
              {expanded ? "Collapse" : "Expand"}
            </button>
            <span className="text-fg-faint">·</span>
            <button
              type="button"
              onClick={() => setRaw((x) => !x)}
              title={raw ? "Render as Markdown" : "Show the exact resolved text the judge receives"}
              className="text-[10.5px] text-fg-faint transition-colors hover:text-fg-muted"
            >
              {raw ? "Rendered" : "Raw"}
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
