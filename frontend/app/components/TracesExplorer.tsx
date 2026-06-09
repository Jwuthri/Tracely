"use client";

import clsx from "clsx";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ConvNode } from "../lib/api";
import { mergeMeta, metaText } from "../lib/meta";
import { TraceTable } from "./TraceTable";

type Filter = "all" | "failing" | "multi";
type Range = { from: string | null; to: string | null }; // ISO-8601 (UTC); null = unbounded

const PRESETS: { key: string; label: string; hours: number | null }[] = [
  { key: "all", label: "All time", hours: null },
  { key: "24h", label: "24h", hours: 24 },
  { key: "7d", label: "7d", hours: 24 * 7 },
  { key: "30d", label: "30d", hours: 24 * 30 },
];

const inputCls =
  "rounded-lg border border-line bg-ink-800 px-2.5 py-1.5 text-[12px] text-fg placeholder:text-fg-faint focus:border-signal/40 focus:outline-none [color-scheme:dark]";

// The /traces landing: time-range + status + text filters over conversation threads, rendered as the
// hierarchical conv → message → step table. The thread list is server-paginated ("Load more"); status
// and text filters refine the rows already loaded (see plan note). The time range and pagination hit
// the backend via /api/sessions so the browser never holds the whole table.
export function TracesExplorer({
  initial,
  pageSize,
  hasMore: initialHasMore,
}: {
  initial: ConvNode[];
  pageSize: number;
  hasMore: boolean;
}) {
  const [rows, setRows] = useState<ConvNode[]>(initial);
  const [hasMore, setHasMore] = useState(initialHasMore);
  const [loading, setLoading] = useState(false);
  const [range, setRange] = useState<Range>({ from: null, to: null });
  const [preset, setPreset] = useState<string>("all");
  const [fromInput, setFromInput] = useState("");
  const [toInput, setToInput] = useState("");

  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");

  // Re-seed from the server when the page re-renders (e.g. after switching workspace), resetting the
  // window back to the first page.
  useEffect(() => {
    setRows(initial);
    setHasMore(initialHasMore);
    setRange({ from: null, to: null });
    setPreset("all");
    setFromInput("");
    setToInput("");
  }, [initial, initialHasMore]);

  const load = useCallback(
    async (next: Range, offset: number, replace: boolean) => {
      setLoading(true);
      try {
        const qs = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
        if (next.from) qs.set("from", next.from);
        if (next.to) qs.set("to", next.to);
        const r = await fetch(`/api/sessions?${qs.toString()}`, { cache: "no-store" });
        const data: ConvNode[] = r.ok ? await r.json() : [];
        setRows((prev) => (replace ? data : [...prev, ...data]));
        setHasMore(data.length === pageSize);
      } finally {
        setLoading(false);
      }
    },
    [pageSize],
  );

  function applyPreset(p: (typeof PRESETS)[number]) {
    const next: Range = {
      from: p.hours == null ? null : new Date(Date.now() - p.hours * 3_600_000).toISOString(),
      to: null,
    };
    setPreset(p.key);
    setFromInput("");
    setToInput("");
    setRange(next);
    void load(next, 0, true);
  }

  function applyCustom(nextFrom: string, nextTo: string) {
    setFromInput(nextFrom);
    setToInput(nextTo);
    // datetime-local values are wall-clock local; toISOString() normalizes them to the UTC the backend
    // compares against.
    const next: Range = {
      from: nextFrom ? new Date(nextFrom).toISOString() : null,
      to: nextTo ? new Date(nextTo).toISOString() : null,
    };
    setPreset("custom");
    setRange(next);
    void load(next, 0, true);
  }

  const counts = useMemo(
    () => ({
      all: rows.length,
      failing: rows.filter((t) => t.failing === 1).length,
      multi: rows.filter((t) => t.turns > 1).length,
    }),
    [rows],
  );

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((t) => {
      if (filter === "failing" && t.failing !== 1) return false;
      if (filter === "multi" && t.turns <= 1) return false;
      if (needle) {
        // user-set metadata comes aggregated from the backend (list); fall back to loaded spans.
        const meta =
          t.metadata && Object.keys(t.metadata).length
            ? t.metadata
            : mergeMeta((t.turnsData ?? []).flatMap((tt) => tt.spans));
        const hay = [t.first_input ?? "", t.last_output ?? "", t.model ?? "", metaText(meta)].join(" ").toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [rows, filter, q]);

  const ranged = range.from != null || range.to != null;

  return (
    <div className="space-y-3">
      {/* Time-range bar */}
      <div className="reveal flex flex-wrap items-center gap-2" suppressHydrationWarning>
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">Range</span>
        <div className="flex items-center gap-1.5">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => applyPreset(p)}
              disabled={loading}
              className={clsx(
                "rounded-lg border px-2.5 py-1.5 text-[12px] font-medium transition-colors disabled:opacity-50",
                preset === p.key
                  ? "border-signal/50 bg-signal/15 text-signal"
                  : "border-line bg-ink-800 text-fg-muted hover:text-fg",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-fg-faint">
          <input
            type="datetime-local"
            value={fromInput}
            onChange={(e) => applyCustom(e.target.value, toInput)}
            aria-label="From"
            className={inputCls}
            suppressHydrationWarning
          />
          <span>→</span>
          <input
            type="datetime-local"
            value={toInput}
            onChange={(e) => applyCustom(fromInput, e.target.value)}
            aria-label="To"
            className={inputCls}
            suppressHydrationWarning
          />
        </div>
      </div>

      {/* Status + text filters (refine the loaded rows) */}
      <div
        className="reveal flex flex-wrap items-center justify-between gap-3"
        style={{ animationDelay: "60ms" }}
        suppressHydrationWarning
      >
        <div className="flex items-center gap-1.5">
          {(["all", "failing", "multi"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={clsx(
                "rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-colors",
                filter === f
                  ? "border-signal/50 bg-signal/15 text-signal"
                  : "border-line bg-ink-800 text-fg-muted hover:text-fg",
              )}
            >
              {f === "all" ? "All" : f === "failing" ? "Failing" : "Multi-turn"}
              <span className="ml-1.5 font-mono text-[10.5px] opacity-70">{counts[f]}</span>
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by text, model, metadata…"
          className="w-56 rounded-lg border border-line bg-ink-800 px-3 py-1.5 text-[12.5px] text-fg placeholder:text-fg-faint focus:border-signal/40 focus:outline-none"
          suppressHydrationWarning
        />
      </div>

      {rows.length === 0 ? (
        <div className="card px-4 py-14 text-center text-[13px] text-fg-faint">
          {loading ? (
            "Loading…"
          ) : ranged ? (
            "No traces in this time range — widen the range or pick All time."
          ) : (
            <>
              No traces yet — send one with the SDK or point an OTLP exporter at{" "}
              <code className="text-fg-muted">/v1/traces</code>.
            </>
          )}
        </div>
      ) : (
        <div className="reveal space-y-3" style={{ animationDelay: "80ms" }}>
          {shown.length > 0 ? (
            <TraceTable conversations={shown} />
          ) : (
            <div className="card px-4 py-10 text-center text-[13px] text-fg-faint">
              No loaded threads match this filter{hasMore ? " — try Load more." : "."}
            </div>
          )}

          <div className="flex items-center justify-center gap-3 pt-1">
            {hasMore ? (
              <button
                onClick={() => void load(range, rows.length, false)}
                disabled={loading}
                className="rounded-lg border border-line bg-ink-800 px-4 py-2 text-[12.5px] font-medium text-fg-muted transition-colors hover:text-fg disabled:opacity-50"
              >
                {loading ? "Loading…" : "Load more"}
              </button>
            ) : null}
            <span className="font-mono text-[10.5px] text-fg-faint">
              {rows.length} loaded{hasMore ? "+" : ""}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
