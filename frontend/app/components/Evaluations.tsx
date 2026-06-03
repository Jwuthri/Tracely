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

function fmtVal(s: EvalScore): string {
  if (s.data_type === "NUMERIC" && s.value != null) {
    if (s.name.endsWith("latency_ms")) {
      return s.value < 1000 ? `${Math.round(s.value)}ms` : `${(s.value / 1000).toFixed(2)}s`;
    }
    return String(s.value);
  }
  return "";
}

export function Evaluations({ scores, verdict }: { scores: EvalScore[]; verdict: string | null }) {
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
        scores.map((s, i) => (
          <div
            key={i}
            className="flex items-center justify-between gap-3 border-b border-line/50 px-4 py-2.5 text-[12.5px] last:border-0"
          >
            <span className="flex min-w-0 items-center gap-2.5">
              <Badge variant={verdictVariant(s.verdict)}>{s.verdict}</Badge>
              <span className="text-fg">{NICE[s.name] ?? s.name}</span>
              <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                {LEVEL[s.evaluation_level] ?? s.evaluation_level.toLowerCase()}
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-3">
              {s.comment && <span className="max-w-[260px] truncate font-mono text-[11px] text-fail">{s.comment}</span>}
              {fmtVal(s) && <span className="font-mono text-[11.5px] text-fg-muted">{fmtVal(s)}</span>}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
