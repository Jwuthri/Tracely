import { describe, expect, it } from "vitest";
import { SEQUENCE_MS, STAGES, scramble, stageProgress } from "./ScramblePipeline";

describe("scramble", () => {
  const target = "failure detection";

  it("resolves to the target at full progress", () => {
    expect(scramble(target, 1)).toBe(target);
  });

  it("holds the line width at every progress — mono glyphs only work if the count is stable", () => {
    for (const p of [0, 0.13, 0.5, 0.87, 1]) {
      expect(scramble(target, p)).toHaveLength(target.length);
    }
  });

  it("reveals a prefix of the target", () => {
    const out = scramble(target, 0.5);
    const reveal = Math.round(target.length * 0.5);
    expect(out.slice(0, reveal)).toBe(target.slice(0, reveal));
  });

  it("never scrambles spaces, so word boundaries survive the decode", () => {
    const spaces = [...target].flatMap((ch, i) => (ch === " " ? [i] : []));
    expect(spaces.length).toBeGreaterThan(0);
    for (const i of spaces) expect(scramble(target, 0)[i]).toBe(" ");
  });

  it("clamps progress outside 0..1 instead of over-slicing", () => {
    expect(scramble(target, -1)).toHaveLength(target.length);
    expect(scramble(target, 5)).toBe(target);
  });
});

describe("stageProgress", () => {
  it("staggers: at the moment stage 0 finishes, later stages still have work left", () => {
    const t = 520;
    expect(stageProgress(t, 0)).toBe(1);
    expect(stageProgress(t, 1)).toBeLessThan(1);
    expect(stageProgress(t, STAGES.length - 1)).toBeLessThan(stageProgress(t, 1));
  });

  it("has every stage resolved by the end of the sequence", () => {
    STAGES.forEach((_, i) => expect(stageProgress(SEQUENCE_MS, i)).toBe(1));
  });

  it("never reports progress before a stage's turn", () => {
    expect(stageProgress(0, 1)).toBe(0);
    expect(stageProgress(0, 3)).toBe(0);
  });
});
