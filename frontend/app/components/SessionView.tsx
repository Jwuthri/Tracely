"use client";

import { useMemo, useState } from "react";
import type { ConvNode, FullTurn } from "../lib/api";
import { useWide, WideToggle, WIDE_STYLE } from "../lib/useWide";
import { AgentsSidePanel } from "./AgentsSidePanel";
import { TabButton } from "./SingleTraceView";
import { TraceTable } from "./TraceTable";
import { Waterfall } from "./Waterfall";
import { Badge, verdictVariant } from "./ui";

// A whole multi-turn conversation, with the same two lenses a single trace gets:
//   • Table    — the hierarchical conversation → message → step tree (pre-expanded), with
//                evaluation results as metric columns (run buttons per row/column)
//   • Timeline — a waterfall across every span of every turn, with idle think-time between
//                turns collapsed (so an hour-later reply doesn't render an hour of empty track)
export function SessionView({ conv, turns }: { conv: ConvNode; turns: FullTurn[] }) {
  const [tab, setTab] = useState<"table" | "timeline">("table");

  // Every span across all turns; the Waterfall compresses the idle gaps between turns.
  const allSpans = useMemo(
    () => turns.flatMap((t) => t.spans).sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()),
    [turns],
  );
  const totalScores = turns.reduce((a, t) => a + t.scores.length, 0) + (conv.scores?.length ?? 0);
  const anyFail =
    turns.some((t) => t.verdict === "FAIL" || t.failing === 1) ||
    (conv.scores ?? []).some((s) => s.verdict === "FAIL");
  const overallVerdict = anyFail ? "FAIL" : totalScores > 0 ? "PASS" : null;

  const [wide, setWide] = useWide();
  const [showAgents, setShowAgents] = useState(false);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-1 border-b border-line">
        <div className="flex items-center gap-1">
          <TabButton active={tab === "table"} onClick={() => setTab("table")}>
            Table
          </TabButton>
          <TabButton active={tab === "timeline"} onClick={() => setTab("timeline")}>
            Timeline <span className="font-mono text-[11px] text-fg-faint">{allSpans.length}</span>
          </TabButton>
        </div>
        <div className="flex items-center gap-2">
          {overallVerdict && (
            <Badge variant={verdictVariant(overallVerdict)} dot>
              evals {overallVerdict}
            </Badge>
          )}
          <button
            onClick={() => setShowAgents(true)}
            title="Agents & tools in this conversation"
            className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-fg-muted transition-colors hover:border-signal/40 hover:text-fg"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <rect x="4" y="8" width="16" height="11" rx="2.5" stroke="currentColor" strokeWidth="1.7" />
              <path d="M12 4v4M9 13h.01M15 13h.01" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              <circle cx="12" cy="3.5" r="1.2" fill="currentColor" />
            </svg>
            Agents
          </button>
          <WideToggle wide={wide} onToggle={() => setWide(!wide)} />
        </div>
      </div>

      {showAgents && (
        <AgentsSidePanel threadId={conv.thread} onClose={() => setShowAgents(false)} />
      )}

      <div style={wide ? WIDE_STYLE : undefined} className="transition-[width,margin] duration-200">
        {tab === "table" && <TraceTable conversations={[conv]} embedded />}
        {tab === "timeline" && <Waterfall spans={allSpans} />}
      </div>
    </div>
  );
}
