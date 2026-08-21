import { describe, expect, it } from "vitest";
import { lit } from "./Meter";

describe("lit", () => {
  it("clamps out-of-range values", () => {
    expect(lit(-5, 10)).toBe(0);
    expect(lit(140, 10)).toBe(10);
  });

  it("lights segments proportionally", () => {
    expect(lit(82, 10)).toBe(8);
    expect(lit(4, 10)).toBe(0); // sub-half-segment reads as empty, not as a lie
    expect(lit(100, 20)).toBe(20);
  });
});
