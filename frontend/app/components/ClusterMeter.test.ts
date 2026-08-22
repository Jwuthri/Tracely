import { describe, expect, it } from "vitest";
import { clusterTone } from "./ClusterMeter";

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
