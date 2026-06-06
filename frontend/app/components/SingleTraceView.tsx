"use client";

import clsx from "clsx";
import { useState } from "react";
import type { ConvNode, EvalScore, SpanOut } from "../lib/api";
import { Evaluations } from "./Evaluations";
import { TraceTable } from "./TraceTable";
import { Waterfall } from "./Waterfall";
import { Badge, verdictVariant } from "./ui";

// One trace = a single-turn conversation. The hierarchical table is primary; the waterfall
// timeline and the raw evaluations list remain available as alternate tabs.
export function SingleTraceView({
  conv,
  spans,
  scores,
  verdict,
}: {
  conv: ConvNode;
  spans: SpanOut[];
  scores: EvalScore[];
  verdict: string | null;
}) {
  const [tab, setTab] = useState<"table" | "timeline" | "evaluations">("table");
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1 border-b border-line">
        <TabButton active={tab === "table"} onClick={() => setTab("table")}>
          Table
        </TabButton>
        <TabButton active={tab === "timeline"} onClick={() => setTab("timeline")}>
          Timeline <span className="font-mono text-[11px] text-fg-faint">{spans.length}</span>
        </TabButton>
        <TabButton active={tab === "evaluations"} onClick={() => setTab("evaluations")}>
          Evaluations
          {verdict ? <Badge variant={verdictVariant(verdict)}>{verdict}</Badge> : <span className="font-mono text-[11px] text-fg-faint">{scores.length}</span>}
        </TabButton>
      </div>
      {tab === "table" && <TraceTable conversations={[conv]} mode="detail" autoSelectFirst />}
      {tab === "timeline" && <Waterfall spans={spans} />}
      {tab === "evaluations" && <Evaluations scores={scores} verdict={verdict} />}
    </div>
  );
}

export function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "relative flex items-center gap-2 px-4 py-2.5 text-[13px] font-medium transition-colors",
        active ? "text-fg" : "text-fg-faint hover:text-fg-muted",
      )}
    >
      {children}
      {active && <span className="absolute inset-x-3 -bottom-px h-0.5 rounded bg-signal" />}
    </button>
  );
}
