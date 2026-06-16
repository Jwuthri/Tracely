import { describe, expect, it } from "vitest";
import type { EvalScore, SpanOut } from "../../lib/api";
import {
  asRoleMessage,
  assistantText,
  deriveTitle,
  durationMs,
  firstText,
  fmtDateTime,
  fmtMs,
  fmtScoreValue,
  fmtTokens,
  jsonResultLabel,
  lastTurnMessage,
  messageList,
  modelColor,
  msgRole,
  nearestAgentLabel,
  parseMaybe,
  scoreKey,
  toMsg,
} from "./format";

const span = (o: Partial<SpanOut> = {}): SpanOut => ({
  span_id: "s", parent_span_id: "", name: "", type: "SPAN", level: "", status_message: "",
  start_time: "2026-06-14T10:00:00Z", end_time: null, latency_ms: null, agent_id: "", agent_run_id: "",
  turn_id: "", step_name: "", model_id: "", tokens: 0, cost: 0, metadata: {}, input: null, output: null, ...o,
});

describe("fmtMs", () => {
  it("handles null / negative / zero / sub-ms / ms / s", () => {
    expect(fmtMs(null)).toBe("—");
    expect(fmtMs(-1)).toBe("—");
    expect(fmtMs(0)).toBe("<1ms");
    expect(fmtMs(0.5)).toBe("0.50ms");
    expect(fmtMs(250)).toBe("250ms");
    expect(fmtMs(1500)).toBe("1.50s");
  });
});

describe("fmtTokens", () => {
  it("scales to k / M", () => {
    expect(fmtTokens(900)).toBe("900");
    expect(fmtTokens(1500)).toBe("1.5k");
    expect(fmtTokens(2_000_000)).toBe("2.0M");
  });
});

describe("fmtDateTime", () => {
  it("returns '' for empty / invalid", () => {
    expect(fmtDateTime(null)).toBe("");
    expect(fmtDateTime("not-a-date")).toBe("");
  });
  it("formats a valid ISO timestamp", () => {
    expect(fmtDateTime("2026-06-14T10:05:09Z")).toMatch(/2026-06-14 \d\d:05:09/);
  });
});

describe("durationMs", () => {
  it("prefers latency_ms", () => expect(durationMs(span({ latency_ms: 42 }))).toBe(42));
  it("falls back to end-start", () =>
    expect(durationMs(span({ start_time: "2026-06-14T10:00:00Z", end_time: "2026-06-14T10:00:02Z" }))).toBe(2000));
  it("returns null when unknown", () => expect(durationMs(span())).toBeNull());
});

describe("firstText", () => {
  it("plucks the user turn from a chat array (over system/tool)", () => {
    const v = [{ role: "system", content: "you are a bot" }, { role: "user", content: "where is my order?" }];
    expect(firstText(v)).toBe("where is my order?");
  });
  it("unwraps {messages:[...]} and {question:...} envelopes", () => {
    expect(firstText({ messages: [{ role: "user", content: "hi" }] })).toBe("hi");
    expect(firstText({ question: "the q" })).toBe("the q");
  });
  it("reads content-block arrays", () => {
    expect(firstText([{ type: "text", text: "block text" }])).toBe("block text");
  });
});

describe("deriveTitle", () => {
  it("defaults to 'Conversation' for empty", () => expect(deriveTitle(null)).toBe("Conversation"));
  it("unwraps a JSON message envelope to the user text", () => {
    expect(deriveTitle('{"messages":[{"role":"user","content":"Where is my order?"}]}')).toBe("Where is my order?");
  });
  it("returns 'Conversation' when JSON parses but has no text (LangGraph empty root)", () => {
    expect(deriveTitle('[{"role":"user","content":""}]')).toBe("Conversation");
  });
  it("uses the first non-empty line (CrewAI '\\nCurrent Task:' prefix)", () => {
    expect(deriveTitle("\nCurrent Task: do the thing")).toBe("Current Task: do the thing");
  });
  it("truncates to 7 words with an ellipsis", () => {
    expect(deriveTitle("one two three four five six seven eight nine")).toBe("one two three four five six seven…");
  });
});

describe("parseMaybe", () => {
  it("parses JSON, passes plain strings through, null-safe", () => {
    expect(parseMaybe('{"a":1}')).toEqual({ a: 1 });
    expect(parseMaybe("plain")).toBe("plain");
    expect(parseMaybe("{bad json")).toBe("{bad json");
    expect(parseMaybe(null)).toBeNull();
  });
});

describe("msgRole", () => {
  it("normalizes LangChain human/ai to user/assistant", () => {
    expect(msgRole({ type: "human" })).toBe("user");
    expect(msgRole({ type: "ai" })).toBe("assistant");
    expect(msgRole({ role: "tool" })).toBe("tool");
  });
});

describe("messageList", () => {
  it("returns the messages of a {messages:[...]} wrapper or a bare chat array", () => {
    expect(messageList({ messages: [{ role: "user", content: "x" }] })).toHaveLength(1);
    expect(messageList([{ role: "user", content: "x" }])).toHaveLength(1);
  });
  it("returns null for non-message shapes", () => {
    expect(messageList("plain")).toBeNull();
    expect(messageList([{ foo: 1 }])).toBeNull();
  });
});

describe("lastTurnMessage", () => {
  const raw = JSON.stringify([
    { role: "user", content: "q1" },
    { role: "assistant", content: "a1" },
    { role: "user", content: "q2" },
  ]);
  it("returns the LAST message of the requested role", () => {
    expect(lastTurnMessage(raw, "user")?.content).toBe("q2");
    expect(lastTurnMessage(raw, "assistant")?.content).toBe("a1");
  });
  it("undefined for non-list, null for a list missing that side", () => {
    expect(lastTurnMessage("plain", "user")).toBeUndefined();
    expect(lastTurnMessage(JSON.stringify([{ role: "user", content: "q" }]), "assistant")).toBeNull();
  });
});

describe("asRoleMessage", () => {
  it("wraps a {question:...} kwarg dict into a {role,content} message", () => {
    expect(asRoleMessage("user", '{"question":"hi"}')).toBe('{"role":"user","content":"hi"}');
  });
  it("passes through values that already look like messages", () => {
    const m = '{"role":"user","content":"hi"}';
    expect(asRoleMessage("user", m)).toBe(m);
  });
  it("is null/empty-safe", () => expect(asRoleMessage("user", "")).toBe(""));
});

describe("assistantText", () => {
  it("takes the last assistant turn from a chat array", () => {
    const v = [{ role: "user", content: "q" }, { role: "assistant", content: "the answer" }];
    expect(assistantText(v)).toBe("the answer");
  });
});

describe("toMsg", () => {
  it("unwraps a single-element [{role,content}] array", () => {
    expect(toMsg("assistant", '[{"role":"assistant","content":"hi"}]')).toEqual({ role: "assistant", content: "hi" });
  });
  it("pulls this side's text from a kwarg dict", () => {
    expect(toMsg("user", '{"question":"where?"}')).toEqual({ role: "user", content: "where?" });
  });
  it("returns null for empty", () => expect(toMsg("user", null)).toBeNull());
});

describe("scoreKey", () => {
  const s = (o: Partial<EvalScore>): EvalScore => ({
    name: "faith", evaluation_level: "AGENT_RUN", observation_id: "", value: null, verdict: "", comment: "", data_type: "BOOLEAN", ...o,
  });
  it("keys by span / thread / trace in priority order", () => {
    expect(scoreKey(s({ observation_id: "sp1" }))).toBe("span:sp1|faith");
    expect(scoreKey(s({ evaluation_level: "CONVERSATION", session_id: "th1" }))).toBe("th:th1|faith");
    expect(scoreKey(s({ trace_id: "tr1" }))).toBe("tr:tr1|faith");
    expect(scoreKey(s({ evaluation_level: "CONVERSATION" }))).toBeNull();
  });
});

describe("jsonResultLabel", () => {
  it("headlines a short label field, skipping prose", () => {
    expect(jsonResultLabel('{"reason":"a long explanation here","intent":"refund"}')).toBe("refund");
  });
  it("null for pure-score objects / non-JSON", () => {
    expect(jsonResultLabel('{"score":0.9}')).toBeNull();
    expect(jsonResultLabel("not json")).toBeNull();
  });
});

describe("fmtScoreValue", () => {
  const s = (o: Partial<EvalScore>): EvalScore => ({
    name: "m", evaluation_level: "AGENT_RUN", observation_id: "", value: null, verdict: "", comment: "", data_type: "NUMERIC", ...o,
  });
  it("blanks BOOLEAN (the chip shows it)", () => expect(fmtScoreValue(s({ data_type: "BOOLEAN" }))).toBe(""));
  it("formats latency specially", () => expect(fmtScoreValue(s({ name: "x.latency_ms", value: 1500 }))).toBe("1.50s"));
  it("rounds floats to 2dp, keeps ints", () => {
    expect(fmtScoreValue(s({ value: 0.3333 }))).toBe("0.33");
    expect(fmtScoreValue(s({ value: 4 }))).toBe("4");
  });
});

describe("modelColor", () => {
  it("maps families to tints", () => {
    expect(modelColor("gpt-4o")).toContain("emerald");
    expect(modelColor("claude-haiku-4-5")).toContain("orange");
    expect(modelColor("mystery-model")).toContain("slate");
  });
});

describe("nearestAgentLabel", () => {
  it("walks up to the nearest AGENT ancestor", () => {
    const all = [
      span({ span_id: "agent", type: "AGENT", name: "support-agent" }),
      span({ span_id: "gen", parent_span_id: "agent", type: "GENERATION" }),
    ];
    expect(nearestAgentLabel(all[1], all)).toBe("support-agent");
  });
  it("returns own name when the span IS an agent", () => {
    const a = span({ type: "AGENT", name: "billing-agent" });
    expect(nearestAgentLabel(a, [a])).toBe("billing-agent");
  });
});
