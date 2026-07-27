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

import type { ConvNode } from "@/app/lib/api";
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
