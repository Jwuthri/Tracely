import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SpanOut } from "@/app/lib/api";
import { StatePanel } from "@/app/components/StatePanel";

function span(p: Partial<SpanOut> & { span_id: string; start_time: string }): SpanOut {
  return {
    parent_span_id: "", name: "", type: "CHAIN", level: "DEFAULT", status_message: "",
    end_time: null, latency_ms: null, agent_id: "", agent_run_id: "", turn_id: "",
    step_name: "", model_id: "", tokens: 0, cost: 0, metadata: {}, input: null, output: null,
    ...p,
  };
}

// A LangGraph-shaped conversation: two auto-captured node deltas (output + marker) and one
// explicit set_state write, with `plan` emptied by the second node.
const SPANS = [
  span({
    span_id: "s1", start_time: "2026-06-14T10:00:01Z", step_name: "planner", agent_id: "support",
    metadata: { "tracely.state_source": "output" },
    output: '{"plan":["step-a","step-b"],"retries":0}',
  }),
  span({
    span_id: "s2", start_time: "2026-06-14T10:00:02Z", step_name: "replan", agent_id: "support",
    metadata: { "tracely.state_source": "output", "tracely.state.note": "plan was unusable" },
    output: '{"plan":[],"retries":1}',
  }),
];

describe("StatePanel", () => {
  it("renders the folded current state and the per-step timeline", () => {
    render(<StatePanel threadId="thread-1" spans={SPANS} onClose={vi.fn()} />);

    expect(screen.getByText("Conversation State")).toBeInTheDocument();
    expect(screen.getByText("planner")).toBeInTheDocument();
    expect(screen.getByText("replan")).toBeInTheDocument();
    // explicit tracely.state.* wins over the output marker on the same span; the channel shows up
    // in both the folded "Current" section and its step in the timeline.
    expect(screen.getAllByText("note").length).toBe(2);
    expect(screen.queryByText(/No shared state recorded/)).not.toBeInTheDocument();
  });

  it("expands a channel to its full value on click", () => {
    render(<StatePanel threadId="thread-1" spans={SPANS} onClose={vi.fn()} />);
    // "Current" section lists `plan`; first match is the folded one.
    fireEvent.click(screen.getAllByText("plan")[0]);
    expect(screen.getAllByRole("button", { expanded: true }).length).toBeGreaterThan(0);
  });

  it("shows the empty state when nothing in the conversation carries state", () => {
    const plain = [span({ span_id: "x", start_time: "2026-06-14T10:00:01Z", output: "hello" })];
    render(<StatePanel threadId="thread-1" spans={plain} onClose={vi.fn()} />);
    expect(screen.getByText(/No shared state recorded/)).toBeInTheDocument();
  });

  it("hides unchanged rewrites until asked, so re-emitted channels don't bury real writes", () => {
    const noisy = [
      span({
        span_id: "a", start_time: "2026-06-14T10:00:01Z", step_name: "first",
        metadata: { "tracely.state.plan": '["a"]' },
      }),
      span({
        span_id: "b", start_time: "2026-06-14T10:00:02Z", step_name: "rewrites-same",
        metadata: { "tracely.state.plan": '["a"]' },
      }),
    ];
    render(<StatePanel threadId="thread-1" spans={noisy} onClose={vi.fn()} />);
    expect(screen.queryByText("rewrites-same")).not.toBeInTheDocument();
    expect(screen.getByText(/1 step changed nothing/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("show unchanged"));
    expect(screen.getByText("rewrites-same")).toBeInTheDocument();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<StatePanel threadId="thread-1" spans={SPANS} onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
