import { describe, expect, it } from "vitest";
import {
  RECIPES,
  TRIGGERS,
  draftProblem,
  emptyDraft,
  fromMonitor,
  intervalLabel,
  toBody,
  triggerSummary,
} from "./alerts";
import type { Monitor } from "./api";

const monitor = (o: Partial<Monitor> = {}): Monitor => ({
  id: "m1",
  name: "CI gate failed",
  description: "",
  target_agent: "support-bot",
  condition: { type: "gate_failed", env: "ci" },
  channels: [],
  steps: [],
  flow_layout: null,
  enabled: true,
  min_interval_seconds: 900,
  last_evaluated_at: null,
  last_fired_at: null,
  last_fired_summary: "",
  created_at: null,
  ...o,
});

describe("toBody", () => {
  it("sends only the condition fields the trigger uses", () => {
    // The draft always carries a threshold; an event condition must not ship it, or the rule
    // stores a filter the user never set.
    const body = toBody(emptyDraft({ name: "gate", type: "gate_failed", env: "ci", threshold: 0.9 }));
    expect(body.condition).toEqual({ type: "gate_failed", env: "ci" });
  });

  it("keeps window + threshold for a polled trigger", () => {
    const body = toBody(
      emptyDraft({ name: "q", type: "fail_rate_over", score_name: "tracely.run.quality", threshold: 0.2 }),
    );
    expect(body.condition).toEqual({
      type: "fail_rate_over",
      score_name: "tracely.run.quality",
      threshold: 0.2,
      window_minutes: 60,
      min_samples: 20,
    });
  });

  it("never sends channels — the flow is the action now", () => {
    expect(Object.keys(toBody(emptyDraft({ name: "x" })))).not.toContain("channels");
  });
});

describe("fromMonitor", () => {
  it("round-trips a saved rule's trigger half", () => {
    const m = monitor();
    const body = toBody(fromMonitor(m));
    expect(body.condition).toEqual(m.condition);
    expect(body.target_agent).toBe("support-bot");
  });

  it("falls back to a known trigger when the API grows one this build doesn't know", () => {
    expect(fromMonitor(monitor({ condition: { type: "quota_exceeded" } })).type).toBe("gate_failed");
  });
});

describe("draftProblem", () => {
  it("blocks a threshold rule with no evaluator picked", () => {
    expect(draftProblem(emptyDraft({ name: "x", type: "score_below" }))).toContain("evaluator");
  });

  it("passes a complete event trigger — the flow is validated by the canvas", () => {
    expect(draftProblem(emptyDraft({ name: "x", type: "cluster_new" }))).toBeNull();
  });
});

describe("triggerSummary", () => {
  it("reads as a sentence about scope, not a dump of fields", () => {
    expect(triggerSummary({ type: "gate_failed", env: "ci", target_agent: "support-bot" })).toBe(
      "env ci · support-bot",
    );
    expect(triggerSummary({ type: "trace_failed", contains: "pii" })).toBe("“pii” · all agents");
    expect(triggerSummary({ type: "fail_rate_over", score_name: "q", threshold: 0.2, window_minutes: 30 })).toBe(
      "q · > 20% / 30min · all agents",
    );
  });
});

describe("intervalLabel", () => {
  it("says every time when the rate limit is off", () => {
    expect(intervalLabel(0)).toBe("every time");
  });
  it("renders minutes and hours", () => {
    expect(intervalLabel(900)).toBe("at most 1×/15min");
    expect(intervalLabel(1800)).toBe("at most 1×/30min");
    expect(intervalLabel(3600)).toBe("at most 1×/1h");
  });
  it("labels every interval the recipes ask for", () => {
    // The rate-limit select is built from intervalLabel, so a recipe interval with no label would
    // render as some OTHER option while the draft kept its own value.
    for (const r of RECIPES) expect(intervalLabel(r.draft.min_interval_seconds ?? 0)).toBeTruthy();
  });
});

describe("RECIPES", () => {
  it("every recipe opens as a runnable flow, not an empty canvas", () => {
    for (const r of RECIPES) {
      expect(r.steps.length).toBeGreaterThan(0);
      expect(TRIGGERS[r.draft.type ?? "gate_failed"]).toBeDefined();
    }
  });

  it("a recipe's steps only use step types the backend knows", () => {
    const known = new Set(["condition", "slack", "send_email", "webhook", "llm_prompt", "python_expression"]);
    for (const r of RECIPES) for (const s of r.steps) expect(known.has(s.step_type)).toBe(true);
  });

  it("ships no pre-filled destinations — a recipe must not post to someone else's Slack", () => {
    for (const r of RECIPES) {
      for (const s of r.steps) {
        const url = (s.config as { url?: string }).url;
        if (url !== undefined) expect(url).toBe("");
      }
    }
  });
});
