import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Mount-time effects fetch evaluator defs/costs + navigation — stub so the table renders offline.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
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
});
