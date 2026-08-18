import { describe, expect, it } from "vitest";
import { judgeTakeaway } from "./calibration";

const c = (o: Partial<Parameters<typeof judgeTakeaway>[0]>) => ({
  labeled: 10,
  agreement: 1,
  false_pass: 0,
  false_fail: 0,
  ...o,
});

describe("judgeTakeaway", () => {
  it("says nothing until there are enough labels", () => {
    expect(judgeTakeaway(c({ labeled: 2, false_fail: 2 }))).toBeNull();
  });

  it("clears a judge that never disagreed", () => {
    expect(judgeTakeaway(c({}))?.tone).toBe("ok");
  });

  it("calls out missed failures as the dangerous direction", () => {
    const t = judgeTakeaway(c({ false_pass: 3, false_fail: 1 }));
    expect(t?.tone).toBe("fail");
    expect(t?.text).toContain("Misses failures");
  });

  it("calls out over-flags when that dominates", () => {
    const t = judgeTakeaway(c({ false_pass: 0, false_fail: 3 }));
    expect(t?.tone).toBe("warn");
    expect(t?.text).toContain("Over-flags");
  });
});
