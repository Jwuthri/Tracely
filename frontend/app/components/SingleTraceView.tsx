"use client";

import clsx from "clsx";
import { useState } from "react";
import type { ConvNode, SpanOut } from "../lib/api";
import { useWide, WideToggle, WIDE_STYLE } from "../lib/useWide";
import { AgentsSidePanel } from "./AgentsSidePanel";
import { TraceTable } from "./TraceTable";
import { Waterfall } from "./Waterfall";
import { Badge, verdictVariant } from "./ui";

// One trace = a single-turn conversation. The hierarchical table is primary — evaluation
// results live INSIDE it as metric columns (with per-row/per-column Run buttons), so there is
// no separate Evaluations tab anymore; the waterfall timeline remains as an alternate lens.
export function SingleTraceView({
  conv,
  spans,
  verdict,
}: {
  conv: ConvNode;
  spans: SpanOut[];
  verdict: string | null;
}) {
  const [tab, setTab] = useState<"table" | "timeline">("table");
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
            Timeline <span className="font-mono text-[11px] text-fg-faint">{spans.length}</span>
          </TabButton>
        </div>
        <div className="flex items-center gap-2">
          {verdict && (
            <Badge variant={verdictVariant(verdict)} dot>
              evals {verdict}
            </Badge>
          )}
          <button
            onClick={() => setShowAgents(true)}
            title="Agents & tools in this trace"
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
      <div style={wide ? WIDE_STYLE : undefined} className="transition-[width,margin] duration-200">
        {tab === "table" && <TraceTable conversations={[conv]} embedded />}
        {tab === "timeline" && <Waterfall spans={spans} />}
      </div>
      {showAgents && (
        <AgentsSidePanel threadId={conv.thread} onClose={() => setShowAgents(false)} />
      )}
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
