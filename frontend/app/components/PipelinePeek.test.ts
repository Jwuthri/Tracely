import { describe, expect, it } from "vitest";
import { shape, type PipelineCounts } from "./PipelinePeek";

const counts = (over: Partial<PipelineCounts> = {}): PipelineCounts => ({
  traces: 0,
  evaluators: 0,
  failures: 0,
  clusters: 0,
  cases: 0,
  gates: 0,
  ...over,
});

describe("shape", () => {
  it("tells the canned story when there are no counts to show", () => {
    const { stages, outs } = shape();
    expect(stages.every((s) => s.lit)).toBe(true);
    expect(outs.map((o) => o.lit)).toEqual([true, true, true]);
  });

  it("keeps a fresh workspace completely dark", () => {
    const { stages, outs, status } = shape(counts());
    expect(stages.map((s) => s.lit)).toEqual([false, false, false]);
    expect(outs.map((o) => o.lit)).toEqual([false, false, false]);
    expect(status).toBe("0 traces · 0 evaluators");
  });

  it("lights storage off traces alone — nothing else has happened yet", () => {
    const { stages, outs } = shape(counts({ traces: 12 }));
    expect(stages.map((s) => s.lit)).toEqual([true, true, false]);
    expect(stages[0].sub).toBe("12 traces");
    expect(outs.every((o) => o.lit)).toBe(false);
  });

  it("counts a cluster as a caught failure even when no evaluator scored FAIL", () => {
    // a raw execution error is clustered without a FAIL score — same rule as the checklist
    expect(shape(counts({ clusters: 3 })).outs[0]).toMatchObject({ label: "3 caught", lit: true });
    expect(shape(counts({ failures: 5 })).outs[0]).toMatchObject({ label: "5 caught", lit: true });
  });

  it("lights the whole loop once a gate has run", () => {
    const { stages, outs } = shape(counts({ traces: 1200, evaluators: 4, failures: 9, cases: 2, gates: 1 }));
    expect(stages.map((s) => s.lit)).toEqual([true, true, true]);
    expect(outs.map((o) => o.label)).toEqual(["9 caught", "2 cases", "1 gate run"]);
    expect(shape(counts({ cases: 1 })).outs[1].label).toBe("1 case");
    expect(outs.every((o) => o.lit)).toBe(true);
  });
});
