import { describe, expect, it } from "vitest";
import {
  EMPTY_LOCAL,
  EMPTY_STATUS,
  deriveSteps,
  questRank,
  stepComplete,
  visitMarker,
  type QuestStatus,
} from "./quest";

const status = (over: Partial<QuestStatus> = {}): QuestStatus => ({ ...EMPTY_STATUS, ...over });

describe("visitMarker", () => {
  it("maps routes to the step they tick — most specific first", () => {
    expect(visitMarker("/trends")).toBe("trends");
    expect(visitMarker("/settings/api-keys")).toBe("keys");
    expect(visitMarker("/sessions/th-1/fleet")).toBe("fleet");
    expect(visitMarker("/sessions/th-1/replay")).toBe("fleet");
    expect(visitMarker("/sessions/th-1")).toBe("trace");
    expect(visitMarker("/traces/abc123")).toBe("trace");
    // the LIST pages tick nothing — only opening a trace counts
    expect(visitMarker("/traces")).toBeNull();
    expect(visitMarker("/dashboard")).toBeNull();
  });
});

describe("deriveSteps", () => {
  it("a fresh workspace has everything to do", () => {
    const steps = deriveSteps(status(), EMPTY_LOCAL);
    expect(steps).toHaveLength(10);
    expect(steps.filter(stepComplete)).toHaveLength(0);
  });

  it("data-derived steps read real counts, visit steps read markers", () => {
    const steps = deriveSteps(
      status({ traces: 12, evaluators: 2, clusters: 1, llm_key: true }),
      { visited: ["trace", "trends"] },
    );
    const done = Object.fromEntries(steps.map((s) => [s.id, stepComplete(s)]));
    expect(done).toEqual({
      key: false,
      llm: true,
      trace: true,
      open: true,
      eval: true,
      trends: true,
      fleet: false,
      fail: true, // a cluster counts as a caught failure, same as Activation
      case: false,
      gate: false,
    });
  });

  it("skipping the OpenRouter key completes the step without marking it done", () => {
    const [, llm] = deriveSteps(status(), { visited: [], llm_skipped: true });
    expect(llm.id).toBe("llm");
    expect(llm.done).toBe(false);
    expect(llm.skipped).toBe(true);
    expect(stepComplete(llm)).toBe(true);
    // ...but a real key wins over the skip flag
    const [, llm2] = deriveSteps(status({ llm_key: true }), { visited: [], llm_skipped: true });
    expect(llm2.done).toBe(true);
    expect(llm2.skipped).toBe(false);
  });

  it("copying the key or visiting the keys page both tick the key step", () => {
    expect(deriveSteps(status(), { visited: [], key_copied: true })[0].done).toBe(true);
    expect(deriveSteps(status(), { visited: ["keys"] })[0].done).toBe(true);
  });
});

describe("questRank", () => {
  it("climbs from Rookie to Trace Master", () => {
    expect(questRank(0, 10)).toBe("Rookie");
    expect(questRank(1, 10)).toBe("Observer");
    expect(questRank(4, 10)).toBe("Trace Detective");
    expect(questRank(7, 10)).toBe("Gate Keeper");
    expect(questRank(10, 10)).toBe("Trace Master");
  });
});
