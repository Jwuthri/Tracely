import type { Edge, Node } from "@xyflow/react";
import { describe, expect, it } from "vitest";
import {
  CYCLE_ERROR,
  RULE_TRIGGER_NODE_ID as T,
  buildFlowFromRule,
  dedupeEdges,
  flowToStepDrafts,
  priorStepsOrdered,
  splitVariableTokens,
  stepOutputs,
  tokenDeletionRange,
  topoOrder,
  type StepDraft,
} from "./ruleFlow";

/** These mirror `backend/tests/test_alert_flow.py`. The two implementations of the graph rules
 *  have to agree, so they get the same cases. */

const e = (source: string, target: string): Edge => ({ id: `e-${source}-${target}`, source, target });

const stepNode = (id: string, over: Partial<Node> = {}): Node => ({
  id,
  type: "ruleStep",
  position: { x: 0, y: 0 },
  data: { name: id, step_type: "slack", config: {} },
  ...over,
});

describe("topoOrder", () => {
  it("orders by the wiring, and pops ties in sorted-id order", () => {
    const ids = new Set(["a", "b", "c", "d"]);
    const { order, error } = topoOrder([e(T, "a"), e("a", "b"), e("a", "c"), e("b", "d"), e("c", "d")], ids);
    expect(error).toBeNull();
    expect(order).toEqual(["a", "b", "c", "d"]);
  });

  it("reports a cycle instead of running half a graph", () => {
    const { order, error } = topoOrder([e(T, "a"), e("a", "b"), e("b", "a")], new Set(["a", "b"]));
    expect(order).toEqual([]);
    expect(error).toBe(CYCLE_ERROR);
  });
});

describe("dedupeEdges", () => {
  it("drops duplicates and self-loops", () => {
    expect(dedupeEdges([e("a", "b"), e("a", "b"), e("a", "a")]).map((x) => x.id)).toEqual(["e-a-b"]);
  });
});

describe("flowToStepDrafts", () => {
  it("numbers reachable steps in run order and appends orphans", () => {
    const nodes = [stepNode("a"), stepNode("b"), stepNode("parked")];
    const { drafts, orphanIds, error } = flowToStepDrafts(nodes, [e(T, "a"), e("a", "b")]);
    expect(error).toBeNull();
    expect(drafts.map((d) => [d.id, d.order_index])).toEqual([
      ["a", 0],
      ["b", 1],
      ["parked", 2],
    ]);
    // Parked, not deleted: a save must never drop work someone dragged off the flow.
    expect(orphanIds).toEqual(["parked"]);
  });

  it("refuses to produce drafts for a cyclic canvas", () => {
    const { drafts, error } = flowToStepDrafts([stepNode("a"), stepNode("b")], [
      e(T, "a"),
      e("a", "b"),
      e("b", "a"),
    ]);
    expect(drafts).toEqual([]);
    expect(error).toBe(CYCLE_ERROR);
  });

  it("ignores the trigger node", () => {
    const { drafts } = flowToStepDrafts([{ id: T, type: "trigger", position: { x: 0, y: 0 }, data: {} }, stepNode("a")], [
      e(T, "a"),
    ]);
    expect(drafts.map((d) => d.id)).toEqual(["a"]);
  });
});

describe("priorStepsOrdered", () => {
  const drafts: StepDraft[] = ["a", "b", "c", "d"].map((id, i) => ({
    id,
    order_index: i,
    name: id,
    step_type: "slack",
    config: {},
  }));

  it("gives each branch its own upstream list — steps[0] is per branch, not global", () => {
    const edges = [e(T, "a"), e("a", "b"), e("a", "c"), e("b", "d")];
    const ids = new Set(["a", "b", "c", "d"]);
    expect(priorStepsOrdered("c", drafts, edges, ids).map((d) => d.id)).toEqual(["a"]);
    expect(priorStepsOrdered("d", drafts, edges, ids).map((d) => d.id)).toEqual(["a", "b"]);
    expect(priorStepsOrdered("a", drafts, edges, ids)).toEqual([]);
  });
});

describe("buildFlowFromRule", () => {
  it("synthesises a chain when there is no saved layout", () => {
    const flow = buildFlowFromRule({
      steps: [
        { id: "s2", order_index: 1, name: "Two", step_type: "slack", config: {} },
        { id: "s1", order_index: 0, name: "One", step_type: "webhook", config: {} },
      ],
      flow_layout: null,
      triggerLabel: "CI gate failed",
    });
    expect(flow.nodes.map((n) => n.id)).toEqual([T, "s1", "s2"]);
    expect(flow.edges.map((x) => [x.source, x.target])).toEqual([
      [T, "s1"],
      ["s1", "s2"],
    ]);
  });

  it("lets the row win over a stale layout blob", () => {
    const flow = buildFlowFromRule({
      steps: [{ id: "s1", order_index: 0, name: "Renamed", step_type: "webhook", config: { url: "u" } }],
      flow_layout: {
        nodes: [
          { id: T, type: "trigger", position: { x: 0, y: 0 }, data: {} },
          stepNode("s1", { data: { name: "Stale", step_type: "slack", config: {} } }),
        ],
        edges: [e(T, "s1")],
      },
      triggerLabel: "x",
    });
    expect(flow.nodes[1]?.data).toMatchObject({ name: "Renamed", step_type: "webhook" });
  });

  it("re-adds a trigger node a layout is missing", () => {
    const flow = buildFlowFromRule({
      steps: [{ id: "s1", order_index: 0, name: "One", step_type: "slack", config: {} }],
      flow_layout: { nodes: [stepNode("s1")], edges: [] },
      triggerLabel: "x",
    });
    expect(flow.nodes[0]?.id).toBe(T);
  });
});

describe("stepOutputs", () => {
  it("uses an LLM step's declared schema when it has one", () => {
    expect(stepOutputs("llm_prompt").map((o) => o.name)).toEqual(["text"]);
    expect(
      stepOutputs("llm_prompt", { output_schema: [{ name: "severity", type: "string", description: "" }] }).map(
        (o) => o.name,
      ),
    ).toEqual(["severity"]);
  });
});

describe("variable tokens", () => {
  it("splits text from tokens", () => {
    expect(splitVariableTokens("hi {{ alert.name }}!")).toEqual([
      { kind: "text", value: "hi " },
      { kind: "token", value: "{{ alert.name }}" },
      { kind: "text", value: "!" },
    ]);
  });

  it("deletes a whole token, not one character", () => {
    const v = "a {{ alert.name }} b";
    expect(tokenDeletionRange(v, 18, "Backspace")).toEqual([2, 18]);
    expect(tokenDeletionRange(v, 2, "Delete")).toEqual([2, 18]);
    expect(tokenDeletionRange(v, 1, "Backspace")).toBeNull();
  });
});
