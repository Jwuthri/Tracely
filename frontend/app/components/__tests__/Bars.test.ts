import { describe, expect, it } from "vitest";
import { sparkPoints } from "@/app/components/Bars";

describe("sparkPoints", () => {
  it("spans the full width and flips y (max at top, 0 at baseline)", () => {
    expect(sparkPoints([0, 50, 100], 100)).toBe("0.00,100.00 50.00,50.00 100.00,0.00");
  });

  it("scales to the shared max, not the series' own max", () => {
    expect(sparkPoints([100, 100], 200)).toBe("0.00,50.00 100.00,50.00");
  });

  it("draws a lone sample edge-to-edge instead of an invisible one-point line", () => {
    expect(sparkPoints([100], 200)).toBe("0.00,50.00 100.00,50.00");
  });

  it("survives an all-zero series and an empty one", () => {
    expect(sparkPoints([0, 0], 0)).toBe("0.00,100.00 100.00,100.00");
    expect(sparkPoints([], 10)).toBe("");
  });
});
