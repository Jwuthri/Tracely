"use client";

import { useState } from "react";
import type { EvalScore, SpanOut } from "../lib/api";
import { Evaluations } from "./Evaluations";
import { Waterfall } from "./Waterfall";

// Holds the selected span so clicking an evaluation (with a target span) highlights it in the
// waterfall and shows it in the inspector.
export function TraceBody({
  spans,
  scores,
  verdict,
}: {
  spans: SpanOut[];
  scores: EvalScore[];
  verdict: string | null;
}) {
  const [sel, setSel] = useState<string | null>(spans[0]?.span_id ?? null);
  return (
    <div className="space-y-6">
      <div className="reveal">
        <Evaluations scores={scores} verdict={verdict} onPick={setSel} />
      </div>
      <div className="reveal" style={{ animationDelay: "60ms" }}>
        <Waterfall spans={spans} sel={sel} onSel={setSel} />
      </div>
    </div>
  );
}
