"use client";

import clsx from "clsx";
import { useState } from "react";
import type { SpanOut } from "../lib/api";
import { CopyId } from "./CopyId";
import { IO } from "./IO";
import { IconError } from "./icons";
import { Badge, TypeChip } from "./ui";

const BAR: Record<string, string> = {
  AGENT: "bg-t_agent",
  SUBAGENT: "bg-t_agent",
  GENERATION: "bg-t_llm",
  EMBEDDING: "bg-t_llm",
  TOOL: "bg-t_tool",
  RETRIEVER: "bg-t_retriever",
};

function depthOf(span: SpanOut, byId: Map<string, SpanOut>): number {
  let d = 0;
  let cur = span;
  const seen = new Set<string>();
  while (cur.parent_span_id && byId.has(cur.parent_span_id) && !seen.has(cur.span_id)) {
    seen.add(cur.span_id);
    cur = byId.get(cur.parent_span_id)!;
    d++;
    if (d > 100) break;
  }
  return d;
}

function fmtMs(ms?: number | null): string {
  if (ms == null) return "—";
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function Waterfall({
  spans,
  sel: controlledSel,
  onSel,
}: {
  spans: SpanOut[];
  sel?: string | null;
  onSel?: (id: string) => void;
}) {
  const [internalSel, setInternalSel] = useState<string | null>(spans[0]?.span_id ?? null);
  const sel = controlledSel !== undefined ? controlledSel : internalSel;
  const setSel = onSel ?? setInternalSel;
  if (spans.length === 0) {
    return <div className="card p-8 text-center text-[13px] text-fg-faint">No spans in this trace.</div>;
  }
  const byId = new Map(spans.map((s) => [s.span_id, s]));
  const t0 = Math.min(...spans.map((s) => new Date(s.start_time).getTime()));
  const t1 = Math.max(...spans.map((s) => new Date(s.end_time ?? s.start_time).getTime()));
  const total = Math.max(1, t1 - t0);
  const selected = spans.find((s) => s.span_id === sel) ?? null;

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_360px]">
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-4 py-2 font-mono text-[10px] text-fg-faint">
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <span key={f}>{fmtMs(total * f)}</span>
          ))}
        </div>
        <div>
          {spans.map((s, i) => {
            const depth = depthOf(s, byId);
            const start = new Date(s.start_time).getTime();
            const end = new Date(s.end_time ?? s.start_time).getTime();
            const left = ((start - t0) / total) * 100;
            const width = Math.max(0.8, ((end - start) / total) * 100);
            const err = s.level === "ERROR";
            const active = s.span_id === sel;
            return (
              <button
                key={s.span_id}
                onClick={() => setSel(s.span_id)}
                className={clsx(
                  "group grid w-full grid-cols-[300px_1fr] items-center gap-3 border-b border-line/50 px-4 py-2.5 text-left transition-colors last:border-0",
                  active ? "bg-signal/[0.06]" : "hover:bg-white/[0.025]",
                )}
              >
                <div className="flex min-w-0 items-center gap-2" style={{ paddingLeft: depth * 16 }}>
                  <TypeChip type={s.type} />
                  <span className={clsx("truncate font-mono text-[12.5px]", err ? "text-fail" : "text-fg")}>
                    {s.name}
                  </span>
                  {err && <IconError className="h-3.5 w-3.5 shrink-0 text-fail" />}
                </div>
                <div className="relative h-5">
                  <div className="absolute inset-y-[8px] left-0 right-0 rounded bg-white/[0.03]" />
                  <div
                    className={clsx(
                      "absolute inset-y-1 origin-left animate-grow rounded-[4px] shadow-sm",
                      err ? "bg-fail" : (BAR[s.type] ?? "bg-t_step"),
                      active && "ring-1 ring-white/40",
                    )}
                    style={{ left: `${left}%`, width: `${width}%`, animationDelay: `${i * 45}ms` }}
                  />
                  <span className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 font-mono text-[10px] text-fg-faint">
                    {fmtMs(s.latency_ms)}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <SpanPanel span={selected} />
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-2.5">
      <dt className="shrink-0 text-fg-faint">{k}</dt>
      <dd className="min-w-0 font-mono text-fg">{v}</dd>
    </div>
  );
}

const TABS = ["input", "output", "attributes"] as const;
type Tab = (typeof TABS)[number];

function SpanPanel({ span }: { span: SpanOut | null }) {
  const [tab, setTab] = useState<Tab>("input");
  if (!span) {
    return (
      <div className="card grid h-fit place-items-center p-8 text-[13px] text-fg-faint">
        Select a span
      </div>
    );
  }
  const attrs = Object.entries(span.metadata || {}).sort(([a], [b]) => a.localeCompare(b));
  return (
    <div className="card sticky top-20 h-fit overflow-hidden">
      <div className="border-b border-line px-4 py-3.5">
        <div className="flex items-center justify-between">
          <TypeChip type={span.type} />
          {span.level === "ERROR" ? (
            <Badge variant="fail" dot>
              error
            </Badge>
          ) : (
            <Badge variant="ok" dot>
              ok
            </Badge>
          )}
        </div>
        <div className="mt-2.5 font-mono text-[14px] text-fg">{span.name}</div>
      </div>
      <dl className="divide-y divide-line/50 text-[12px]">
        <Row k="Duration" v={fmtMs(span.latency_ms)} />
        {span.model_id && <Row k="Model" v={span.model_id} />}
        {span.tokens > 0 && <Row k="Tokens" v={span.tokens.toLocaleString()} />}
        {span.cost > 0 && <Row k="Cost" v={`$${span.cost.toFixed(4)}`} />}
        {span.status_message && (
          <Row k="Status" v={<span className="text-fail">{span.status_message}</span>} />
        )}
        <Row k="Span id" v={<CopyId value={span.span_id} label="span id" />} />
      </dl>
      <div className="flex border-t border-line">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              "flex-1 px-3 py-2 font-mono text-[10.5px] uppercase tracking-wider transition-colors",
              tab === t ? "border-b-2 border-signal text-signal" : "text-fg-faint hover:text-fg-muted",
            )}
          >
            {t}
            {t === "attributes" && attrs.length > 0 ? ` (${attrs.length})` : ""}
          </button>
        ))}
      </div>
      {tab === "input" && <IO value={span.input} />}
      {tab === "output" && <IO value={span.output} />}
      {tab === "attributes" && <Attributes entries={attrs} />}
    </div>
  );
}

function Attributes({ entries }: { entries: [string, string][] }) {
  if (entries.length === 0) {
    return <div className="px-4 py-6 text-center text-[12px] text-fg-faint">No attributes.</div>;
  }
  return (
    <div className="max-h-80 overflow-auto">
      {entries.map(([k, v]) => (
        <div
          key={k}
          className="grid grid-cols-[150px_1fr] gap-3 border-b border-line/40 px-4 py-1.5 text-[11.5px] last:border-0"
        >
          <span className="truncate font-mono text-fg-faint" title={k}>
            {k}
          </span>
          <span className="min-w-0 break-words font-mono text-fg-muted">{v}</span>
        </div>
      ))}
    </div>
  );
}
