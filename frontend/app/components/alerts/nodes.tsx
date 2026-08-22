"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import clsx from "clsx";
import { STEP_ORDER, STEP_META, readStepNodeData, type StepType } from "@/app/lib/ruleFlow";
import { TONE } from "./tone";

/** The two node types. Everything else the canvas uses comes from React Flow itself. */

const HANDLE = "!h-3 !w-3 !border-2 !border-ink-800";

export function TriggerNode(props: NodeProps) {
  const data = (props.data ?? {}) as { label?: string; filters?: string };
  const selected = props.selected === true;
  return (
    <div
      className={clsx(
        "relative w-[236px] overflow-hidden rounded-xl border border-l-[3px] bg-ink-800 shadow-panel transition-shadow",
        TONE.signal.accent,
        selected ? "border-signal ring-[3px] ring-signal/25" : "border-line",
      )}
    >
      <div className={clsx("flex items-center gap-2 px-3 py-2", TONE.signal.tint)}>
        <span className={clsx("grid h-6 w-6 place-items-center rounded-md text-[12px]", TONE.signal.chip)}>⚡</span>
        <span className={clsx("font-mono text-[9.5px] font-semibold uppercase tracking-[0.16em]", TONE.signal.fg)}>
          When
        </span>
      </div>
      <div className="px-3 pb-3 pt-2">
        <div className="truncate text-[12.5px] font-medium text-fg">{data.label ?? "Trigger"}</div>
        <div className="mt-0.5 truncate font-mono text-[10.5px] text-fg-faint">
          {data.filters ? data.filters : "click to configure"}
        </div>
      </div>
      <Handle type="source" position={Position.Right} className={clsx(HANDLE, "!bg-signal nodrag")} />
    </div>
  );
}

export function RuleStepNode(props: NodeProps) {
  const data = readStepNodeData(props.data);
  const meta = STEP_META[data.step_type] ?? { label: data.step_type || "Unknown", tone: "info" as const };
  const tone = TONE[meta.tone];
  const selected = props.selected === true;
  return (
    <div
      className={clsx(
        "relative w-[236px] overflow-hidden rounded-xl border border-l-[3px] bg-ink-800 shadow-panel transition-shadow",
        tone.accent,
        selected ? clsx("border-signal ring-[3px]", tone.ring) : "border-line",
      )}
    >
      <Handle type="target" position={Position.Left} className={clsx(HANDLE, "!bg-fg-faint nodrag")} />
      <div className={clsx("flex items-start gap-2.5 px-3 py-2.5", tone.tint)}>
        <span className={clsx("grid h-7 w-7 shrink-0 place-items-center rounded-md text-[12px]", tone.chip)}>
          {STEP_GLYPH[data.step_type] ?? "•"}
        </span>
        <div className="min-w-0 flex-1">
          <div className={clsx("font-mono text-[9.5px] font-semibold uppercase tracking-[0.16em]", tone.fg)}>
            {meta.label}
          </div>
          <div className="truncate text-[12.5px] font-medium text-fg">{data.name || "Untitled step"}</div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className={clsx(HANDLE, "nodrag")}
        style={{ background: `rgb(var(--c-${TONE_VAR[meta.tone]}))` }}
      />
    </div>
  );
}

// Emoji instead of an icon dependency: six glyphs, no bundle, and they read at 12px.
export const STEP_GLYPH: Record<StepType, string> = {
  condition: "⑃",
  slack: "◈",
  send_email: "✉",
  webhook: "↗",
  llm_prompt: "✦",
  python_expression: "λ",
};

const TONE_VAR: Record<string, string> = {
  signal: "signal",
  info: "info",
  ok: "ok",
  warn: "warn",
  fail: "fail",
  tool: "t-tool",
};

export function NodePicker({
  onPick,
  onClose,
}: {
  onPick: (t: StepType) => void;
  onClose: () => void;
}) {
  return (
    <div className="absolute right-0 top-full z-50 mt-1.5 w-[280px] overflow-hidden rounded-xl border border-line bg-ink-800 shadow-frame">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">Step type</span>
        <button onClick={onClose} aria-label="Close step picker" className="px-1 text-fg-faint hover:text-fg">
          ×
        </button>
      </div>
      <ul className="max-h-[300px] overflow-y-auto py-1">
        {STEP_ORDER.map((t) => {
          const meta = STEP_META[t];
          const tone = TONE[meta.tone];
          return (
            <li key={t}>
              <button
                onClick={() => onPick(t)}
                className="flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors hover:bg-hilite/[0.04]"
              >
                <span className={clsx("mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md text-[11px]", tone.chip)}>
                  {STEP_GLYPH[t]}
                </span>
                <span className="min-w-0">
                  <span className="block text-[12.5px] text-fg">{meta.label}</span>
                  <span className="block text-[11px] leading-snug text-fg-faint">{meta.blurb}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
