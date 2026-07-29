import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Mount-time effects fetch evaluator defs/costs + navigation — stub so the table renders offline.
// `push` is hoisted so a test can assert the row-click navigation did (or didn't) fire.
const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, prefetch: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/app/lib/evaluators", async (orig) => ({
  ...(await orig<typeof import("@/app/lib/evaluators")>()),
  listEvaluators: vi.fn(() => Promise.resolve([])),
  getEvaluatorCost: vi.fn(() => Promise.resolve({})),
}));

import type { ConvNode, FullTurn, SpanOut } from "@/app/lib/api";
import { TraceTable } from "@/app/components/TraceTable";

function conv(over: Partial<ConvNode> = {}): ConvNode {
  return {
    thread: "thread-1",
    turns: 1,
    first_input: "Where is my order ORD-4471?",
    last_output: "It is out for delivery.",
    tokens: 120,
    cost: 0,
    first_ts: "2026-06-14T10:00:00Z",
    last_ts: "2026-06-14T10:00:05Z",
    last_trace_id: "trace-1",
    failing: 0,
    ...over,
  } as ConvNode;
}

describe("TraceTable (render safety net)", () => {
  it("renders column headers and a conversation row from its title", async () => {
    render(<TraceTable conversations={[conv()]} />);
    // header (C-group "Conversation" column label is unique among the defaults)
    expect(await screen.findByText("Conversation")).toBeInTheDocument();
    // the conversation row, titled from first_input via deriveTitle
    expect(screen.getByText(/Where is my order ORD-4471/)).toBeInTheDocument();
  });

  it("shows an empty state when there are no conversations", async () => {
    render(<TraceTable conversations={[]} />);
    expect(await screen.findByText(/No conversations/i)).toBeInTheDocument();
  });

  // Multi-select delete: opt-in via onDeleted, DELETE /api/sessions with the picked threads.
  it("selects conversations and deletes them", async () => {
    const onDeleted = vi.fn();
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ threads: 1, traces: 2 }) }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn(() => true));

    render(<TraceTable conversations={[conv(), conv({ thread: "thread-2", last_trace_id: "trace-2" })]} onDeleted={onDeleted} />);
    // header select-all + one box per conversation row
    const boxes = await screen.findAllByRole("checkbox");
    expect(boxes).toHaveLength(3);
    fireEvent.click(boxes[2]);
    expect(screen.getByText("1 selected")).toBeInTheDocument();

    fireEvent.click(await screen.findByText("Delete"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(["thread-2"]));
    expect(fetchMock).toHaveBeenCalledWith("/api/sessions", expect.objectContaining({ method: "DELETE", body: JSON.stringify({ threads: ["thread-2"] }) }));
    vi.unstubAllGlobals();
  });

  it("select-all picks every conversation, and picking one never navigates", async () => {
    push.mockClear();
    render(<TraceTable conversations={[conv(), conv({ thread: "thread-2", last_trace_id: "trace-2" })]} onDeleted={vi.fn()} />);
    const [selectAll, first] = await screen.findAllByRole("checkbox");

    fireEvent.click(first); // the row's checkbox must not trigger the row's navigate-on-click
    expect(push).not.toHaveBeenCalled();

    fireEvent.click(selectAll);
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    fireEvent.click(selectAll);
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
  });

  it("has no checkboxes without onDeleted", async () => {
    render(<TraceTable conversations={[conv()]} />);
    await screen.findByText("Conversation");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});

// ── State Δ columns (M + S) ──────────────────────────────────────────────────
// Seeding `turnsData` puts the table in detail mode: spans are pre-loaded and every row is open,
// which is what the State Δ columns need to have anything to show.

function stateSpan(over: Partial<SpanOut> = {}): SpanOut {
  return {
    span_id: "sp-1", parent_span_id: "", name: "planner", type: "CHAIN", level: "DEFAULT",
    status_message: "", start_time: "2026-06-14T10:00:01Z", end_time: null, latency_ms: null,
    agent_id: "support", agent_run_id: "", turn_id: "", step_name: "planner", model_id: "",
    tokens: 0, cost: 0, metadata: { "tracely.state.plan": '["step-a"]' }, input: null, output: null,
    ...over,
  };
}

function turnWith(spans: SpanOut[]): FullTurn {
  return {
    trace_id: "trace-1", input: "hi", output: "done", tokens: 0, cost: 0, latency_ms: 10,
    ts: "2026-06-14T10:00:00Z", failing: 0, scores: [], verdict: null, spans,
  };
}

describe("TraceTable State Δ columns", () => {
  it("shows the written channel at step and message level", async () => {
    render(<TraceTable conversations={[conv({ turnsData: [turnWith([stateSpan()])] })]} />);
    // both the M and S columns carry the same header label
    expect(await screen.findAllByText("State Δ")).toHaveLength(2);
    // `plan` chip: once on the step row, once on the assistant message row (the union)
    expect(screen.getAllByText("plan")).toHaveLength(2);
  });

  it("hides both columns entirely when nothing loaded carries state", async () => {
    const plain = stateSpan({ metadata: {}, output: "just an answer" });
    render(<TraceTable conversations={[conv({ turnsData: [turnWith([plain])] })]} />);
    expect(await screen.findByText("Conversation")).toBeInTheDocument();
    expect(screen.queryByText("State Δ")).not.toBeInTheDocument();
  });
});
