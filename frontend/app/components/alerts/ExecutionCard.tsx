"use client";

import clsx from "clsx";
import { useState } from "react";
import { STEP_META, type StepType } from "@/app/lib/ruleFlow";
import { STEP_GLYPH } from "./nodes";
import { TONE } from "./tone";

/** One run of a flow, per step, with what each field rendered to.
 *
 *  `rendered_config` is the point of this card: seeing that `{{ trace.url }}` resolved to a real
 *  link, and that the body you sent was the body you meant, without re-running anything. */

export type ExecutionStep = {
  step_id: string;
  name?: string;
  step_type: string;
  status: string;
  error_message?: string | null;
  result?: unknown;
  rendered_config?: Record<string, unknown> | null;
  ancestor_step_ids?: string[];
};

export type Execution = {
  id: string;
  status: string;
  trigger_type?: string;
  subject_id?: string;
  started_at: string | null;
  completed_at: string | null;
  error?: string | null;
  is_test?: boolean;
  steps: ExecutionStep[];
};

const STATUS_TONE: Record<string, { badge: string; label: string }> = {
  completed: { badge: "border-ok/30 bg-ok/10 text-ok", label: "ran" },
  failed: { badge: "border-fail/30 bg-fail/10 text-fail", label: "failed" },
  skipped: { badge: "border-warn/30 bg-warn/10 text-warn", label: "skipped by a gate" },
  running: { badge: "border-info/30 bg-info/10 text-info", label: "running" },
};

const when = (iso: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <span className="text-fg-faint">—</span>;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-ink-900/60 px-2 py-1.5 font-mono text-[11px] leading-relaxed text-fg-muted">
      {text}
    </pre>
  );
}

function StepRow({ step, index }: { step: ExecutionStep; index: number }) {
  const [open, setOpen] = useState(step.status === "failed");
  const meta = STEP_META[step.step_type as StepType];
  const tone = TONE[meta?.tone ?? "info"];
  const failed = step.status === "failed";
  const rendered = Object.entries(step.rendered_config ?? {});
  return (
    <div className="border-t border-line first:border-t-0">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2.5 px-3 py-2 text-left">
        <span className={clsx("grid h-6 w-6 shrink-0 place-items-center rounded-md text-[11px]", tone.chip)}>
          {STEP_GLYPH[step.step_type as StepType] ?? "•"}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] text-fg">
            {index + 1}. {step.name || meta?.label || step.step_type}
          </span>
          {failed ? (
            <span className="block truncate font-mono text-[11px] text-fail">{step.error_message}</span>
          ) : (
            <span className="block truncate font-mono text-[11px] text-fg-faint">{meta?.label ?? step.step_type}</span>
          )}
        </span>
        <span
          className={clsx(
            "shrink-0 rounded-md border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide",
            failed ? STATUS_TONE.failed.badge : STATUS_TONE.completed.badge,
          )}
        >
          {failed ? "failed" : "ok"}
        </span>
        <span aria-hidden className={clsx("text-fg-faint transition-transform", open && "rotate-90")}>
          ›
        </span>
      </button>
      {open ? (
        <div className="grid gap-3 px-3 pb-3 lg:grid-cols-2">
          <div className="space-y-1">
            <div className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">Sent (rendered)</div>
            {rendered.length === 0 ? (
              <Value value={null} />
            ) : (
              rendered.map(([k, v]) => (
                <div key={k}>
                  <div className="font-mono text-[10.5px] text-fg-muted">{k}</div>
                  <Value value={v} />
                </div>
              ))
            )}
          </div>
          <div className="space-y-1">
            <div className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">Result</div>
            <Value value={step.result} />
            {step.ancestor_step_ids && step.ancestor_step_ids.length > 0 ? (
              <p className="text-[10.5px] text-fg-faint">
                Read {step.ancestor_step_ids.length} upstream step
                {step.ancestor_step_ids.length === 1 ? "" : "s"} as{" "}
                <span className="font-mono">steps[0…{step.ancestor_step_ids.length - 1}]</span>
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function ExecutionCard({ execution, title }: { execution: Execution; title?: string }) {
  const tone = STATUS_TONE[execution.status] ?? STATUS_TONE.running;
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-ink-800">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className={clsx("rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide", tone.badge)}>
          {tone.label}
        </span>
        <span className="text-[12.5px] text-fg">{title ?? execution.trigger_type ?? "run"}</span>
        {execution.is_test ? (
          <span className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-fg-faint">
            test
          </span>
        ) : null}
        <span className="ml-auto font-mono text-[10.5px] text-fg-faint">{when(execution.started_at)}</span>
      </div>
      {execution.error ? (
        <p className="border-b border-line bg-fail/[0.06] px-3 py-2 font-mono text-[11px] text-fail">{execution.error}</p>
      ) : null}
      {execution.status === "skipped" ? (
        <p className="border-b border-line bg-warn/[0.06] px-3 py-2 text-[11.5px] text-warn">
          A condition step evaluated falsy, so the rest of the flow did not run — which is what a gate is for.
        </p>
      ) : null}
      {execution.steps.length === 0 ? (
        <p className="px-3 py-4 text-[12px] text-fg-faint">No steps ran.</p>
      ) : (
        execution.steps.map((s, i) => <StepRow key={`${s.step_id}-${i}`} step={s} index={i} />)
      )}
    </div>
  );
}
