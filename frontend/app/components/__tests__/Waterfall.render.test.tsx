import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Waterfall } from "@/app/components/Waterfall";
import type { SpanOut } from "@/app/lib/api";

function span(p: Partial<SpanOut> & { span_id: string; agent_run_id: string; start_time: string }): SpanOut {
  return {
    parent_span_id: "", name: "step", type: "CHAIN", level: "DEFAULT", status_message: "",
    end_time: null, latency_ms: 10, agent_id: "", turn_id: "", step_name: "", model_id: "",
    tokens: 0, cost: 0, metadata: {}, input: null, output: null,
    ...p,
  };
}

// Two turns of one conversation: span ids repeat across turns (they are only unique per trace).
// The turns are shaped DIFFERENTLY on purpose — turn B wraps its root in an outer span reusing
// id …03 — so a byId keyed on the bare span_id walks turn A's child into turn B's tree.
const SPANS = [
  span({ span_id: "01", agent_run_id: "traceA", start_time: "2026-06-14T10:00:00Z", name: "root-traceA" }),
  span({ span_id: "02", agent_run_id: "traceA", parent_span_id: "01", start_time: "2026-06-14T10:00:01Z", name: "_BroadcastChat-traceA" }),
  span({ span_id: "03", agent_run_id: "traceB", start_time: "2026-06-14T10:05:00Z", name: "outer-traceB" }),
  span({ span_id: "01", agent_run_id: "traceB", parent_span_id: "03", start_time: "2026-06-14T10:05:01Z", name: "root-traceB" }),
  span({ span_id: "02", agent_run_id: "traceB", parent_span_id: "01", start_time: "2026-06-14T10:05:02Z", name: "_BroadcastChat-traceB" }),
];

const rows = () => screen.getAllByRole("button").filter((b) => b.className.includes("bg-signal/[0.06]"));

describe("Waterfall across turns with repeating span ids", () => {
  it("selects only the clicked turn's span, not its twin in the other turn", () => {
    render(<Waterfall spans={SPANS} />);
    fireEvent.click(screen.getByText("_BroadcastChat-traceB"));
    // one label row + one bar row, both from turn B
    expect(rows().length).toBe(2);
    // the detail panel shows turn B's span, not turn A's
    expect(screen.getByText("_BroadcastChat-traceB", { selector: ".text-\\[14px\\]" })).toBeInTheDocument();
  });

  it("indents each child under its own turn's root (depth 1, not a cross-turn walk)", () => {
    render(<Waterfall spans={SPANS} />);
    for (const run of ["traceA", "traceB"]) {
      // [0] = the fixed label column, which renders before the track and the detail panel.
      const root = screen.getAllByText(`root-${run}`)[0].closest("button")!;
      const child = screen.getAllByText(`_BroadcastChat-${run}`)[0].closest("button")!;
      const depth = run === "traceA" ? 0 : 1; // turn B's root sits under its outer span
      expect(root.style.paddingLeft).toBe(`${12 + depth * 14}px`);
      expect(child.style.paddingLeft).toBe(`${12 + (depth + 1) * 14}px`);
    }
  });
});
