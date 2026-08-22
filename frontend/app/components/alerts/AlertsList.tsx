"use client";

import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Monitor } from "@/app/lib/api";
import { RECIPES, TRIGGERS, intervalLabel, triggerSummary, type TriggerId } from "@/app/lib/alerts";
import { STEP_META, type StepType } from "@/app/lib/ruleFlow";
import { Toggle } from "../Toggle";
import { Badge } from "../ui";
import { STEP_GLYPH } from "./nodes";
import { TONE } from "./tone";

/** The alert list: what exists, what it does, and whether it has fired.
 *  Rows open the flow editor; the gallery opens a new one already drawn. */

const ago = (iso: string | null): string => {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
};

function FlowStrip({ monitor }: { monitor: Monitor }) {
  const steps = (monitor.steps ?? []).slice().sort((a, b) => a.order_index - b.order_index);
  if (steps.length === 0) {
    const channels = monitor.channels ?? [];
    return (
      <span className="font-mono text-[11px] text-fg-faint">
        {channels.length > 0
          ? `${channels.map((c) => c.type).join(" + ")} · no flow yet`
          : "no steps — this alert does nothing"}
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      {steps.map((s, i) => {
        const meta = STEP_META[s.step_type as StepType];
        const tone = TONE[meta?.tone ?? "info"];
        return (
          <span key={s.id} className="flex items-center gap-1">
            {i > 0 ? (
              <span aria-hidden className="text-fg-faint">
                →
              </span>
            ) : null}
            <span
              className={clsx(
                "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10.5px]",
                tone.chip,
              )}
              title={meta?.label ?? s.step_type}
            >
              {STEP_GLYPH[s.step_type as StepType] ?? "•"} {s.name || meta?.label}
            </span>
          </span>
        );
      })}
    </span>
  );
}

export function AlertsList({ initial }: { initial: Monitor[] }) {
  const router = useRouter();
  const [rows, setRows] = useState(initial);
  const [err, setErr] = useState<string | null>(null);

  async function toggle(m: Monitor, enabled: boolean) {
    const r = await fetch(`/api/monitors/${m.id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    if (!r.ok) {
      // A toggle that silently didn't apply reads as "armed" while nothing is watching.
      setErr(`Could not ${enabled ? "arm" : "disarm"} “${m.name}” (HTTP ${r.status}).`);
      return;
    }
    const d: Monitor = await r.json();
    setRows((prev) => prev.map((x) => (x.id === d.id ? d : x)));
  }

  async function remove(m: Monitor) {
    if (!confirm(`Delete alert “${m.name}”? Its run history goes with it.`)) return;
    const r = await fetch(`/api/monitors/${m.id}`, { method: "DELETE" });
    if (r.ok) setRows((prev) => prev.filter((x) => x.id !== m.id));
  }

  return (
    <div className="space-y-5">
      <section className="reveal card overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <span className="text-[13px] font-semibold text-fg">Start from a use case</span>
          <button onClick={() => router.push("/settings/alerts/new")} className="btn-ghost text-[12.5px]">
            + Blank alert
          </button>
        </div>
        <div className="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-3">
          {RECIPES.map((r, i) => (
            <button
              key={r.title}
              onClick={() => router.push(`/settings/alerts/new?recipe=${i}`)}
              className="group bg-ink-800 px-4 py-3.5 text-left transition-colors hover:bg-hilite/[0.03]"
            >
              <div className="text-[13px] font-medium text-fg">{r.title}</div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-fg-muted">{r.why}</p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <Badge variant={TRIGGERS[r.draft.type as TriggerId].family === "event" ? "signal" : "info"}>
                  {TRIGGERS[r.draft.type as TriggerId].label}
                </Badge>
                <span className="font-mono text-[10.5px] text-fg-faint">
                  {r.steps.map((s) => STEP_META[s.step_type].label).join(" → ")}
                </span>
              </div>
            </button>
          ))}
        </div>
      </section>

      {err ? (
        <p role="alert" className="text-[12.5px] text-fail">
          {err}
        </p>
      ) : null}

      <section className="reveal card overflow-hidden" style={{ animationDelay: "60ms" }}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <span className="text-[13px] font-semibold text-fg">
            Alerts <span className="font-mono text-[11px] text-fg-faint">({rows.length})</span>
          </span>
        </div>
        {rows.length === 0 ? (
          <div className="px-4 py-12 text-center text-[13px] text-fg-faint">
            No alerts yet — pick a use case above.
          </div>
        ) : (
          <div className="divide-y divide-line">
            {rows.map((m) => {
              const type = m.condition?.type as TriggerId;
              const meta = TRIGGERS[type];
              return (
                <div key={m.id} className="px-4 py-3.5">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <button
                      onClick={() => router.push(`/settings/alerts/${m.id}`)}
                      className="text-[13.5px] font-medium text-fg transition-colors hover:text-signal"
                    >
                      {m.name}
                    </button>
                    <Badge variant={meta?.family === "event" ? "signal" : "info"}>
                      {meta?.label ?? type ?? "unknown"}
                    </Badge>
                    <span className="font-mono text-[10.5px] text-fg-faint">
                      {intervalLabel(m.min_interval_seconds)}
                    </span>
                    <div className="ml-auto flex items-center gap-1.5">
                      <Toggle
                        checked={m.enabled}
                        onChange={(next) => toggle(m, next)}
                        label={m.enabled ? "armed" : "off"}
                      />
                      <button
                        onClick={() => router.push(`/settings/alerts/${m.id}`)}
                        className="btn-ghost text-[12px]"
                      >
                        Edit flow
                      </button>
                      <button onClick={() => remove(m)} className="btn-ghost text-[12px]" title="Delete">
                        ✕
                      </button>
                    </div>
                  </div>
                  <p className="mt-1.5 font-mono text-[11px] text-fg-muted">
                    {triggerSummary({
                      type,
                      target_agent: m.target_agent,
                      env: m.condition?.env,
                      score_name: m.condition?.score_name,
                      contains: m.condition?.contains,
                      threshold: m.condition?.threshold,
                      window_minutes: m.condition?.window_minutes,
                    })}
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                    <FlowStrip monitor={m} />
                    <span className="font-mono text-[11px] text-fg-faint">fired {ago(m.last_fired_at)}</span>
                  </div>
                  {m.last_fired_summary ? (
                    <p className="mt-1 truncate font-mono text-[11px] text-fg-faint">{m.last_fired_summary}</p>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
