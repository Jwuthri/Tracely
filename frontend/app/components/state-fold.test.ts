import { describe, expect, it } from "vitest";
import type { SpanOut } from "../lib/api";
import { foldState, spanStateWrites } from "./state-fold";

function span(p: Partial<SpanOut> & { span_id: string; start_time: string }): SpanOut {
  return {
    parent_span_id: "", name: "", type: "CHAIN", level: "DEFAULT", status_message: "",
    end_time: null, latency_ms: null, agent_id: "", agent_run_id: "", turn_id: "",
    step_name: "", model_id: "", tokens: 0, cost: 0, metadata: {}, input: null, output: null,
    ...p,
  };
}

describe("spanStateWrites", () => {
  it("reads explicit tracely.state.* keys, JSON-decoding values", () => {
    const s = span({
      span_id: "a", start_time: "2026-01-01T00:00:00Z",
      metadata: { "tracely.state.plan": '["x","y"]', "tracely.state.n": "3", "other": "ignored" },
    });
    expect(spanStateWrites(s)).toEqual({ plan: ["x", "y"], n: 3 });
  });

  it("reads a LangGraph node's output as the delta when marked", () => {
    const s = span({
      span_id: "a", start_time: "2026-01-01T00:00:00Z",
      metadata: { "tracely.state_source": "output" },
      output: '{"plan":["step-a"],"retries":0}',
    });
    expect(spanStateWrites(s)).toEqual({ plan: ["step-a"], retries: 0 });
  });

  it("ignores an unmarked span's output — most spans' output is an answer, not state", () => {
    const s = span({ span_id: "a", start_time: "2026-01-01T00:00:00Z", output: '{"answer":"hi"}' });
    expect(spanStateWrites(s)).toBeNull();
  });

  it("ignores a marked span whose output is not a channel map", () => {
    const s = span({
      span_id: "a", start_time: "2026-01-01T00:00:00Z",
      metadata: { "tracely.state_source": "output" }, output: '["not","a","dict"]',
    });
    expect(spanStateWrites(s)).toBeNull();
  });

  it("does not mistake a channel named `delta` for the source marker", () => {
    const s = span({
      span_id: "a", start_time: "2026-01-01T00:00:00Z",
      metadata: { "tracely.state.delta": '{"a":1}' },
    });
    expect(spanStateWrites(s)).toEqual({ delta: { a: 1 } });
  });
});

describe("foldState", () => {
  it("folds deltas oldest-first and classifies add/update/same", () => {
    const spans = [
      span({
        span_id: "s2", start_time: "2026-01-01T00:00:02Z", step_name: "worker",
        metadata: { "tracely.state.retries": "1", "tracely.state.plan": '["a","b"]' },
      }),
      span({
        span_id: "s1", start_time: "2026-01-01T00:00:01Z", step_name: "planner",
        metadata: { "tracely.state.plan": '["a","b"]', "tracely.state.retries": "0" },
      }),
    ];
    const { steps, final } = foldState(spans);

    expect(steps.map((s) => s.label)).toEqual(["planner", "worker"]); // reordered by time
    expect(steps[0].changes.every((c) => c.kind === "add")).toBe(true);
    expect(steps[1].changes.find((c) => c.key === "plan")?.kind).toBe("same");
    expect(steps[1].changes.find((c) => c.key === "retries")?.kind).toBe("update");
    expect(final).toEqual({ plan: ["a", "b"], retries: 1 });
  });

  it("skips spans that carry no state and survives an empty conversation", () => {
    expect(foldState([])).toEqual({ steps: [], final: {} });
    const plain = [span({ span_id: "s1", start_time: "2026-01-01T00:00:01Z", output: "hello" })];
    expect(foldState(plain).steps).toEqual([]);
  });

  it("keeps the last write when a channel is emptied — the failure case this exists for", () => {
    const spans = [
      span({
        span_id: "s1", start_time: "2026-01-01T00:00:01Z", step_name: "planner",
        metadata: { "tracely.state.plan": '["a"]' },
      }),
      span({
        span_id: "s2", start_time: "2026-01-01T00:00:02Z", step_name: "replan",
        metadata: { "tracely.state.plan": "[]" },
      }),
    ];
    const { steps, final } = foldState(spans);
    expect(final.plan).toEqual([]);
    expect(steps[1].changes[0]).toMatchObject({ key: "plan", kind: "update", value: [] });
  });
});
