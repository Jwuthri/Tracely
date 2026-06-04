"use client";

import { useState } from "react";
import type { EvalScore } from "../lib/api";
import { Badge, verdictVariant } from "./ui";

const LEVEL: Record<string, string> = { AGENT_RUN: "run", TURN: "turn", STEP: "step", TOOL: "tool" };
const NICE: Record<string, string> = {
  "tracely.run.outcome": "Run outcome",
  "tracely.run.tool_consistency": "Tool consistency",
  "tracely.run.latency_ms": "Latency",
  "tracely.run.quality": "Answer quality · LLM judge",
  "tracely.tool.success": "Tool success",
};
// plain-English: what each check means (so you never stare at unexplained jargon)
const DOCS: Record<string, string> = {
  "tracely.run.outcome": "Fails if any step in the run errored.",
  "tracely.run.tool_consistency": "Fails if the model said it would call a tool but the tool never actually ran (a silent failure).",
  "tracely.run.latency_ms": "Fails if the run took longer than the latency budget.",
  "tracely.run.quality": "An LLM judge grades the final answer for correctness and faithfulness to the tool results.",
  "tracely.tool.success": "Fails if this specific tool call errored.",
};

function fmtVal(s: EvalScore): string {
  if (s.data_type === "NUMERIC" && s.value != null) {
    if (s.name.endsWith("latency_ms")) {
      return s.value < 1000 ? `${Math.round(s.value)}ms` : `${(s.value / 1000).toFixed(2)}s`;
    }
    return String(s.value);
  }
  return "";
}

export function Evaluations({
  scores,
  verdict,
  onPick,
}: {
  scores: EvalScore[];
  verdict: string | null;
  onPick?: (spanId: string) => void;
}) {
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <h3 className="text-[13px] font-semibold text-fg">Evaluations</h3>
          <span className="rounded bg-signal/10 px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wider text-signal">
            auto
          </span>
        </div>
        {verdict ? (
          <Badge variant={verdictVariant(verdict)} dot>
            {verdict}
          </Badge>
        ) : (
          <span className="text-[12px] text-fg-faint">not evaluated</span>
        )}
      </div>
      {scores.length === 0 ? (
        <div className="px-4 py-6 text-center text-[12.5px] text-fg-faint">No evaluations yet.</div>
      ) : (
        scores.map((s, i) => <EvalRow key={i} s={s} onPick={onPick} />)
      )}
    </div>
  );
}

function EvalRow({ s, onPick }: { s: EvalScore; onPick?: (spanId: string) => void }) {
  const [open, setOpen] = useState(false);
  const linkable = !!(onPick && s.observation_id);
  const val = fmtVal(s);
  const doc = DOCS[s.name];
  const longComment = s.comment && s.comment.length > 60;
  return (
    <div
      className={linkable ? "cursor-pointer border-b border-line/50 last:border-0 hover:bg-white/[0.025]" : "border-b border-line/50 last:border-0"}
      onClick={linkable ? () => onPick!(s.observation_id!) : undefined}
      title={linkable ? "Show the related span" : undefined}
    >
      <div className="flex items-start justify-between gap-3 px-4 py-2.5 text-[12.5px]">
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="flex items-center gap-2.5">
            <Badge variant={verdictVariant(s.verdict)}>{s.verdict}</Badge>
            <span className="text-fg">{NICE[s.name] ?? s.name}</span>
            <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">
              {LEVEL[s.evaluation_level] ?? s.evaluation_level.toLowerCase()}
            </span>
            {linkable && <span className="font-mono text-[10px] text-signal">→ span</span>}
          </span>
          {doc && <span className="text-[11px] leading-snug text-fg-faint">{doc}</span>}
        </span>
        <span className="flex shrink-0 items-center gap-3">
          {s.comment && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (longComment) setOpen((o) => !o);
              }}
              className={`max-w-[260px] text-right font-mono text-[11px] text-fail ${open ? "" : "truncate"} ${longComment ? "hover:underline" : ""}`}
            >
              {s.comment}
            </button>
          )}
          {val && <span className="font-mono text-[11.5px] text-fg-muted">{val}</span>}
        </span>
      </div>
    </div>
  );
}
