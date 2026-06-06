"use client";

import clsx from "clsx";
import { useMemo, useState } from "react";
import type { SpanOut } from "../lib/api";
import { spanMeta } from "../lib/meta";
import { CopyId } from "./CopyId";
import { IO } from "./IO";
import { HighlightedJson, prettyJson } from "./JsonView";
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

// Layout constants for the two-pane (fixed labels | scrollable track) timeline.
const LABEL_W = 280;
const ROW_H = 38;
const RULER_H = 32;
const BASE_PX_PER_MS = 0.3; // track px per ms of *active* time at zoom 1 (short traces fill the pane; longer ones scroll)
const GAP_THRESHOLD_MS = 1000; // idle longer than this (e.g. think-time between turns) is collapsed

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

// Human-readable idle/elapsed duration (ms → "820ms" / "1.4s" / "3m 12s" / "1h 5m").
function fmtGap(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${Math.round(s % 60)}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

type Break = { dPos: number; realMs: number };

// Build a *compressed* timeline: merge all spans into active intervals, then lay them out back-to-back
// on a display axis where any idle gap longer than GAP_THRESHOLD_MS (between turns, mostly) is collapsed
// to a zero-width break marker. So a reply an hour later doesn't render an hour of empty track.
function buildTimeline(spans: SpanOut[]): {
  totalDisplay: number;
  toDisplay: (abs: number) => number;
  breaks: Break[];
  activeMs: number;
} {
  if (spans.length === 0) return { totalDisplay: 1, toDisplay: () => 0, breaks: [], activeMs: 0 };
  const iv = spans
    .map((s) => {
      const start = new Date(s.start_time).getTime();
      const end = new Date(s.end_time ?? s.start_time).getTime();
      return [start, Math.max(end, start)] as [number, number];
    })
    .sort((a, b) => a[0] - b[0]);
  // merge overlapping/touching intervals (a parent span contains its children, so this yields the
  // real "busy" stretches — one per turn for a multi-turn conversation).
  const merged: [number, number][] = [];
  for (const [s, e] of iv) {
    const last = merged[merged.length - 1];
    if (last && s <= last[1]) last[1] = Math.max(last[1], e);
    else merged.push([s, e]);
  }
  const segs: { aStart: number; aEnd: number; dStart: number }[] = [];
  const breaks: Break[] = [];
  let d = 0;
  for (let i = 0; i < merged.length; i++) {
    const [aStart, aEnd] = merged[i];
    segs.push({ aStart, aEnd, dStart: d });
    d += aEnd - aStart;
    if (i < merged.length - 1) {
      const gap = merged[i + 1][0] - aEnd;
      if (gap > GAP_THRESHOLD_MS) breaks.push({ dPos: d, realMs: gap }); // collapse: add 0 display width
      else d += gap; // keep short (intra-turn) gaps to scale
    }
  }
  const totalDisplay = Math.max(1, d);
  const activeMs = merged.reduce((a, [s, e]) => a + (e - s), 0);
  const toDisplay = (abs: number): number => {
    for (const seg of segs) if (abs <= seg.aEnd) return seg.dStart + Math.max(0, abs - seg.aStart);
    const last = segs[segs.length - 1];
    return last.dStart + (last.aEnd - last.aStart);
  };
  return { totalDisplay, toDisplay, breaks, activeMs };
}

const TICKS = [0, 0.25, 0.5, 0.75, 1];

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
  const [zoom, setZoom] = useState(1);
  const ordered = useMemo(
    () => [...spans].sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()),
    [spans],
  );
  const byId = useMemo(() => new Map(ordered.map((s) => [s.span_id, s])), [ordered]);
  const tl = useMemo(() => buildTimeline(ordered), [ordered]);

  const sel = controlledSel !== undefined ? controlledSel : internalSel;
  const setSel = onSel ?? setInternalSel;
  if (ordered.length === 0) {
    return <div className="card p-8 text-center text-[13px] text-fg-faint">No spans in this trace.</div>;
  }
  const selected = ordered.find((s) => s.span_id === sel) ?? null;
  const { totalDisplay, toDisplay, breaks, activeMs } = tl;
  const trackPx = Math.round(totalDisplay * BASE_PX_PER_MS * zoom);
  const clampZoom = (z: number) => Math.min(8, Math.max(0.1, z));

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_360px]">
      <div className="card overflow-hidden">
        {/* toolbar: active span of the timeline + collapsed-gap note + zoom */}
        <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-1.5">
          <span className="truncate font-mono text-[10px] text-fg-faint">
            active {fmtGap(activeMs)}
            {breaks.length > 0 && (
              <span className="text-amber-300/80">
                {" · "}
                {breaks.length} idle gap{breaks.length > 1 ? "s" : ""} collapsed
              </span>
            )}
          </span>
          <div className="flex items-center gap-1 font-mono text-[11px]">
            <button onClick={() => setZoom((z) => clampZoom(z / 1.5))} className="rounded px-2 py-0.5 text-fg-muted transition-colors hover:bg-white/[0.05] hover:text-fg" title="Zoom out">−</button>
            <button onClick={() => setZoom(1)} className={clsx("rounded px-2 py-0.5 transition-colors hover:bg-white/[0.05]", zoom === 1 ? "text-fg-faint" : "text-signal")} title="Reset zoom">{zoom === 1 ? "fit" : `${zoom.toFixed(1)}×`}</button>
            <button onClick={() => setZoom((z) => clampZoom(z * 1.5))} className="rounded px-2 py-0.5 text-fg-muted transition-colors hover:bg-white/[0.05] hover:text-fg" title="Zoom in">+</button>
          </div>
        </div>

        <div className="flex">
          {/* fixed label column (never scrolls horizontally) */}
          <div className="shrink-0 border-r border-line bg-ink-900/30" style={{ width: LABEL_W }}>
            <div style={{ height: RULER_H }} className="border-b border-line" />
            {ordered.map((s) => {
              const err = s.level === "ERROR";
              const active = s.span_id === sel;
              return (
                <button
                  key={s.span_id}
                  onClick={() => setSel(s.span_id)}
                  style={{ height: ROW_H, paddingLeft: 12 + depthOf(s, byId) * 14 }}
                  className={clsx(
                    "flex w-full items-center gap-2 border-b border-line/50 pr-3 text-left transition-colors last:border-0",
                    active ? "bg-signal/[0.06]" : "hover:bg-white/[0.025]",
                  )}
                >
                  <TypeChip type={s.type} />
                  <span className={clsx("truncate font-mono text-[12.5px]", err ? "text-fail" : "text-fg")}>{s.name}</span>
                  {err && <IconError className="h-3.5 w-3.5 shrink-0 text-fail" />}
                </button>
              );
            })}
          </div>

          {/* scrollable timeline track */}
          <div className="flex-1 overflow-x-auto">
            <div className="relative" style={{ minWidth: trackPx }}>
              {/* ruler — labels are *active-elapsed* time (idle is collapsed) */}
              <div className="relative border-b border-line" style={{ height: RULER_H }}>
                {TICKS.map((f) => (
                  <span
                    key={f}
                    className="absolute whitespace-nowrap font-mono text-[10px] text-fg-faint"
                    style={{ left: `${f * 100}%`, top: "50%", transform: `translate(${f === 0 ? "0%" : f === 1 ? "-100%" : "-50%"}, -50%)` }}
                  >
                    {f === 0 ? "0ms" : fmtGap(totalDisplay * f)}
                  </span>
                ))}
              </div>

              {/* collapsed-idle break markers (dashed line + chip), spanning the rows */}
              {breaks.map((b, i) => (
                <div
                  key={i}
                  className="absolute z-10"
                  style={{ left: `${(b.dPos / totalDisplay) * 100}%`, top: RULER_H, bottom: 0 }}
                >
                  <div className="h-full border-l border-dashed border-amber-400/40" />
                  <span
                    className="absolute left-1/2 top-0 -translate-x-1/2 whitespace-nowrap rounded-b bg-amber-400/15 px-1 py-0.5 font-mono text-[8.5px] leading-none text-amber-300/90"
                    title={`idle ${fmtGap(b.realMs)} skipped between turns`}
                  >
                    ⏸ {fmtGap(b.realMs)}
                  </span>
                </div>
              ))}

              {/* bars */}
              {ordered.map((s) => {
                const start = new Date(s.start_time).getTime();
                const end = new Date(s.end_time ?? s.start_time).getTime();
                const left = (toDisplay(start) / totalDisplay) * 100;
                const width = Math.max(0.6, ((toDisplay(end) - toDisplay(start)) / totalDisplay) * 100);
                const endPct = left + width;
                const labelInside = endPct > 85;
                const err = s.level === "ERROR";
                const active = s.span_id === sel;
                return (
                  <button
                    key={s.span_id}
                    onClick={() => setSel(s.span_id)}
                    style={{ height: ROW_H }}
                    className={clsx(
                      "relative block w-full border-b border-line/50 transition-colors last:border-0",
                      active ? "bg-signal/[0.06]" : "hover:bg-white/[0.025]",
                    )}
                  >
                    <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 bg-white/[0.03]" />
                    <div
                      className={clsx(
                        "absolute top-1/2 h-2.5 -translate-y-1/2 rounded-[3px] shadow-sm",
                        err ? "bg-fail" : (BAR[s.type] ?? "bg-t_step"),
                        active && "ring-1 ring-white/40",
                      )}
                      style={{ left: `${left}%`, width: `${width}%` }}
                    />
                    <span
                      className={clsx(
                        "pointer-events-none absolute top-1/2 font-mono text-[10px]",
                        labelInside ? "pr-1.5 text-white/90" : "pl-1.5 text-fg-faint",
                      )}
                      style={{ left: `${Math.min(endPct, 100)}%`, transform: labelInside ? "translate(-100%, -50%)" : "translateY(-50%)" }}
                    >
                      {fmtMs(s.latency_ms)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
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
        {/* LLM sampling params + any user metadata (temperature, top_p, …) */}
        {Object.entries(spanMeta(span)).map(([k, v]) => (
          <Row key={k} k={k} v={typeof v === "object" ? JSON.stringify(v) : String(v)} />
        ))}
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

// A single attribute value: JSON (object/array) is pretty-printed + syntax-highlighted; everything
// else renders as plain text.
function AttrValue({ value }: { value: string }) {
  const t = value.trim();
  const pretty = t.startsWith("{") || t.startsWith("[") ? prettyJson(value) : null;
  if (pretty && pretty !== value) {
    return (
      <pre className="min-w-0 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-slate-300">
        <HighlightedJson text={pretty} />
      </pre>
    );
  }
  return <span className="min-w-0 break-words font-mono text-fg-muted">{value || "—"}</span>;
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
          className="grid grid-cols-[150px_1fr] items-start gap-3 border-b border-line/40 px-4 py-1.5 text-[11.5px] last:border-0"
        >
          <span className="truncate font-mono text-sky-300/80" title={k}>
            {k}
          </span>
          <AttrValue value={v} />
        </div>
      ))}
    </div>
  );
}
