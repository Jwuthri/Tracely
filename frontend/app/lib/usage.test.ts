import { describe, expect, it } from "vitest";
import type { SpanOut } from "./api";
import { spanUsage } from "./usage";

const span = (metadata: Record<string, string>): SpanOut =>
  ({ metadata, tokens: 0, cost: 0, model_id: "claude-sonnet-4" }) as unknown as SpanOut;

describe("spanUsage cache breakdown", () => {
  it("reads the OpenLLMetry/Anthropic keys and keeps them out of the total", () => {
    const u = spanUsage(
      span({
        "gen_ai.usage.input_tokens": "100",
        "gen_ai.usage.output_tokens": "50",
        "gen_ai.usage.cache_read_input_tokens": "900",
        "gen_ai.usage.cache_creation_input_tokens": "20",
      }),
    );
    expect(u.cached_tokens).toBe(900);
    expect(u.cache_write_tokens).toBe(20);
    expect(u.total_tokens).toBe(150);
  });

  it("reads OpenInference / bare provider keys", () => {
    expect(spanUsage(span({ "llm.token_count.prompt_details.cache_read": "7" })).cached_tokens).toBe(7);
    expect(spanUsage(span({ cached_tokens: "8" })).cached_tokens).toBe(8);
  });

  it("omits a zero cache read (cache-enabled miss) instead of showing an empty row", () => {
    expect(spanUsage(span({ "gen_ai.usage.cache_read_input_tokens": "0" })).cached_tokens).toBeUndefined();
  });
});
