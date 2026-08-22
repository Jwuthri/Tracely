"use client";

import clsx from "clsx";
import { toolLabel } from "@/app/lib/assistant";

/* The assistant's tool calls as they happen, as a terminal-style stream: a minute of bouncing
   dots reads as broken, a log that ticks over reads as work. The entries arrive from the SSE
   stream, so nothing here fakes a cadence — the stagger is the real one. */

export type Activity = { name: string; at: number; state: "run" | "ok" | "fail" };

/** A `tool_done` frame closes the most recent still-running call of that name. */
export function closeActivity(list: Activity[], name: string, ok: boolean): Activity[] {
  const i = list.findLastIndex((a) => a.name === name && a.state === "run");
  if (i < 0) return list;
  const next = [...list];
  next[i] = { ...next[i], state: ok ? "ok" : "fail" };
  return next;
}

const DOT = {
  run: "bg-signal animate-pulse2 shadow-glow",
  ok: "bg-ok",
  fail: "bg-fail",
} as const;
const LABEL = { run: "text-fg", ok: "text-fg-muted", fail: "text-fail" } as const;

// ponytail: the last few lines only — newest always visible without a scroll container or a
// scroll-to-bottom effect. Raise it if anyone ever wants the whole trail.
const VISIBLE = 6;

export function ActivityLog({ items }: { items: Activity[] }) {
  if (!items.length) return null;
  const t0 = items[0].at;
  const done = items.filter((a) => a.state !== "run").length;
  return (
    <div className="animate-fadeup overflow-hidden rounded-xl border border-line bg-ink-900/60 font-mono text-[10px]">
      <div className="flex items-center gap-2 border-b border-line/60 px-2.5 py-1.5">
        <span className="h-1.5 w-1.5 animate-pulse2 rounded-full bg-signal shadow-glow" />
        <span className="uppercase tracking-[0.18em] text-fg-muted">working</span>
        <span className="ml-auto text-fg-faint">
          {done}/{items.length}
        </span>
      </div>
      {items.slice(-VISIBLE).map((a, i) => (
        <div
          key={items.length - Math.min(items.length, VISIBLE) + i}
          className="animate-fadeup flex items-center gap-2 border-b border-line/30 px-2.5 py-1 last:border-b-0"
        >
          <span className={clsx("h-1 w-1 shrink-0 rounded-full", DOT[a.state])} />
          <span className="shrink-0 text-fg-faint">+{((a.at - t0) / 1000).toFixed(1)}s</span>
          <span className={clsx("truncate", LABEL[a.state])}>
            {toolLabel(a.name)}
            {a.state === "run" && "…"}
          </span>
          {a.state !== "run" && (
            <span className={clsx("ml-auto shrink-0", a.state === "ok" ? "text-ok" : "text-fail")}>
              {a.state === "ok" ? "✓" : "✕"}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
