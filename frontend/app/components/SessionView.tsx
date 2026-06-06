"use client";

import { useMemo, useState } from "react";
import type { ConvNode, FullTurn } from "../lib/api";
import { Evaluations } from "./Evaluations";
import { TabButton } from "./SingleTraceView";
import { TraceTable } from "./TraceTable";
import { Waterfall } from "./Waterfall";
import { Badge, verdictVariant } from "./ui";

// A whole multi-turn conversation, with the same three lenses a single trace gets:
//   • Table       — the hierarchical conversation → message → step tree (pre-expanded)
//   • Timeline    — a waterfall across every span of every turn, with idle think-time between
//                   turns collapsed (so an hour-later reply doesn't render an hour of empty track)
//   • Evaluations — each turn's auto-eval scores, grouped + labelled by turn
export function SessionView({ conv, turns }: { conv: ConvNode; turns: FullTurn[] }) {
  const [tab, setTab] = useState<"table" | "timeline" | "evaluations">("table");

  // Every span across all turns; the Waterfall compresses the idle gaps between turns.
  const allSpans = useMemo(
    () => turns.flatMap((t) => t.spans).sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()),
    [turns],
  );
  const totalScores = turns.reduce((a, t) => a + t.scores.length, 0);
  const anyFail = turns.some((t) => t.verdict === "FAIL" || t.failing === 1);
  const overallVerdict = anyFail ? "FAIL" : totalScores > 0 ? "PASS" : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1 border-b border-line">
        <TabButton active={tab === "table"} onClick={() => setTab("table")}>
          Table
        </TabButton>
        <TabButton active={tab === "timeline"} onClick={() => setTab("timeline")}>
          Timeline <span className="font-mono text-[11px] text-fg-faint">{allSpans.length}</span>
        </TabButton>
        <TabButton active={tab === "evaluations"} onClick={() => setTab("evaluations")}>
          Evaluations
          {overallVerdict ? (
            <Badge variant={verdictVariant(overallVerdict)}>{overallVerdict}</Badge>
          ) : (
            <span className="font-mono text-[11px] text-fg-faint">{totalScores}</span>
          )}
        </TabButton>
      </div>

      {tab === "table" && <TraceTable conversations={[conv]} mode="detail" autoSelectFirst />}
      {tab === "timeline" && <Waterfall spans={allSpans} />}
      {tab === "evaluations" && (
        <div className="space-y-5">
          {turns.map((t, i) => (
            <div key={t.trace_id} className="space-y-2">
              <div className="flex items-center gap-2.5 px-1">
                <span className="font-mono text-[11px] uppercase tracking-wider text-fg-faint">Turn {i + 1}</span>
                {t.verdict && (
                  <Badge variant={verdictVariant(t.verdict)} dot>
                    {t.verdict}
                  </Badge>
                )}
                <a href={`/traces/${t.trace_id}`} className="font-mono text-[10.5px] text-signal transition-colors hover:underline">
                  view trace →
                </a>
              </div>
              <Evaluations scores={t.scores} verdict={t.verdict} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
