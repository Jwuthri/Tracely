"use client";

import clsx from "clsx";
import { useMemo, useState } from "react";
import type { ConvNode } from "../lib/api";
import { mergeMeta, metaText } from "../lib/meta";
import { TraceTable } from "./TraceTable";

type Filter = "all" | "failing" | "multi";

// The /traces landing: filter + search bar over conversation threads, rendered as the
// hierarchical conv → message → step table (turns + steps lazy-load on expand).
export function TracesExplorer({ conversations }: { conversations: ConvNode[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");

  const counts = useMemo(
    () => ({
      all: conversations.length,
      failing: conversations.filter((t) => t.failing === 1).length,
      multi: conversations.filter((t) => t.turns > 1).length,
    }),
    [conversations],
  );

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return conversations.filter((t) => {
      if (filter === "failing" && t.failing !== 1) return false;
      if (filter === "multi" && t.turns <= 1) return false;
      if (needle) {
        // user-set metadata comes aggregated from the backend (list); fall back to loaded spans.
        const meta =
          t.metadata && Object.keys(t.metadata).length
            ? t.metadata
            : mergeMeta((t.turnsData ?? []).flatMap((tt) => tt.spans));
        const hay = [t.first_input ?? "", t.last_output ?? "", t.model ?? "", metaText(meta)].join(" ").toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [conversations, filter, q]);

  return (
    <div className="space-y-3">
      {/* Password-manager extensions (e.g. Proton Pass) inject data-protonpass-form="" onto this
          input wrapper before hydration; suppress the resulting attribute-only mismatch. */}
      <div
        className="reveal flex flex-wrap items-center justify-between gap-3"
        style={{ animationDelay: "60ms" }}
        suppressHydrationWarning
      >
        <div className="flex items-center gap-1.5">
          {(["all", "failing", "multi"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={clsx(
                "rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-colors",
                filter === f
                  ? "border-signal/50 bg-signal/15 text-signal"
                  : "border-line bg-ink-800 text-fg-muted hover:text-fg",
              )}
            >
              {f === "all" ? "All" : f === "failing" ? "Failing" : "Multi-turn"}
              <span className="ml-1.5 font-mono text-[10.5px] opacity-70">{counts[f]}</span>
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by text, model, metadata…"
          className="w-56 rounded-lg border border-line bg-ink-800 px-3 py-1.5 text-[12.5px] text-fg placeholder:text-fg-faint focus:border-signal/40 focus:outline-none"
          suppressHydrationWarning
        />
      </div>

      <div className="reveal" style={{ animationDelay: "80ms" }}>
        <TraceTable conversations={shown} />
      </div>
    </div>
  );
}
