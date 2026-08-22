import { describe, expect, it } from "vitest";
import { clusterTone, compactCount } from "./ClusterMeter";

// Both taxonomy vocabularies have to land in the same three buckets — the structural
// "family: detail" strings and the free-text ones the clustering LLM writes.
describe("clusterTone", () => {
  it("buckets structural taxonomies by family", () => {
    expect(clusterTone("output: low quality").text).toBe("text-warn");
    expect(clusterTone("execution: tool error").text).toBe("text-fail");
    expect(clusterTone("performance: latency").text).toBe("text-info");
  });

  it("buckets free-text LLM taxonomies by keyword", () => {
    expect(clusterTone("tool execution error").text).toBe("text-fail");
    expect(clusterTone("hallucinated citation").text).toBe("text-warn");
    expect(clusterTone("slow response").text).toBe("text-info");
  });

  it("falls back to execution for unknown or missing", () => {
    expect(clusterTone("").text).toBe("text-fail");
    expect(clusterTone(null).text).toBe("text-fail");
  });
});

// A runaway cluster must not squash the tail to nothing, and must not overflow its column.
describe("scale at 1000", () => {
  it("keeps a long tail distinguishable", () => {
    const seg = (v: number) => Math.min(20, Math.max(1, Math.round(Math.sqrt(v / 1000) * 20)));
    expect(seg(1000)).toBe(20);
    expect(seg(482)).toBeGreaterThan(seg(31));
    expect(seg(31)).toBeGreaterThan(seg(9));
  });

  it("compacts counts to at most 4 characters", () => {
    for (const n of [9, 999, 1000, 12345, 999999, 4200000]) {
      expect(compactCount(n).length).toBeLessThanOrEqual(4);
    }
    expect(compactCount(1000)).toBe("1K");
    expect(compactCount(12345)).toBe("12K");
    expect(compactCount(999)).toBe("999"); // exact below 1k
  });
});
