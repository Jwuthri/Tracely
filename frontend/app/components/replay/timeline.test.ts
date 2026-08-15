import { describe, expect, it } from "vitest";
import { activeAt, currentByActor, findSpan, isContainer, onStage, orderActors, payloadText, toPlayEvents, type ReplayActor, type ReplayEvent } from "./timeline";

const ev = (t: number, dur: number, actor: string, kind: string, name: string): ReplayEvent => ({
  t_ms: t, dur_ms: dur, actor, kind, name, status: "ok", model: "", detail: "",
  span_id: name, trace_id: "t", turn_id: "",
});

describe("toPlayEvents", () => {
  it("squeezes dead air between turns", () => {
    const { events, total } = toPlayEvents([ev(0, 100, "a", "tool", "x"), ev(20000, 100, "b", "tool", "y")]);
    expect(events[0].pt).toBe(0);
    expect(events[1].pt).toBe(400);   // 20s gap collapsed to the cap
    expect(total).toBe(540);  // 400 + the 140ms visibility floor
  });
  it("keeps short spans visible and preserves order", () => {
    const { events } = toPlayEvents([ev(10, 2, "a", "tool", "fast"), ev(5, 50, "a", "llm", "first")]);
    expect(events.map((e) => e.name)).toEqual(["first", "fast"]);
    expect(events[1].pdur).toBe(140);  // floor applied
  });
});

it("activeAt returns only in-flight events", () => {
  const { events } = toPlayEvents([ev(0, 300, "a", "tool", "x"), ev(500, 300, "a", "tool", "y")]);
  expect(activeAt(events, 100).map((e) => e.name)).toEqual(["x"]);
  expect(activeAt(events, 600).map((e) => e.name)).toEqual(["y"]);
});

it("currentByActor ignores container spans", () => {
  const { events } = toPlayEvents([ev(0, 900, "a", "turn", "run"), ev(50, 100, "a", "tool", "search")]);
  expect(currentByActor(events, 100).a.name).toBe("search");
});

it("onStage: actors arrive and then stay", () => {
  // the play clock starts at the FIRST event, so "a" is on stage from 0 and "b" arrives later
  const { events } = toPlayEvents([ev(0, 100, "a", "tool", "x"), ev(300, 100, "b", "tool", "y")]);
  const a = { id: "a" } as ReplayActor;
  const b = { id: "b" } as ReplayActor;
  expect(onStage(b, events, 100)).toBe(false);   // hasn't appeared yet
  expect(onStage(b, events, 320)).toBe(true);
  expect(onStage(a, events, 5000)).toBe(true);   // stays after finishing
});

it("orderActors nests sub-agents under their parent", () => {
  const as = [
    { id: "billing", parent: "" }, { id: "support", parent: "" },
    { id: "audit", parent: "billing" },
  ] as ReplayActor[];
  expect(orderActors(as).map((a) => a.id)).toEqual(["billing", "audit", "support"]);
});

it("isContainer keeps turn wrappers out of 'what is this agent doing'", () => {
  const wrapper: ReplayEvent = { ...ev(0, 6000, "team", "turn", "agent_teams.turn"), container: true };
  const work: ReplayEvent = ev(100, 400, "sup", "llm", "chat");
  const { events } = toPlayEvents([wrapper, work]);
  expect(isContainer(events[0])).toBe(true);
  expect(isContainer(events[1])).toBe(false);
  expect(currentByActor(events, 200).team).toBeUndefined();  // the wrapper is not an action
  expect(currentByActor(events, 200).sup.name).toBe("chat");
});

describe("step detail helpers", () => {
  it("findSpan matches within the given trace only", () => {
    const spans = [{ span_id: "1" }, { span_id: "2", output: "x" }];
    expect(findSpan(spans, "2")?.output).toBe("x");
    expect(findSpan(spans, "9")).toBeNull();
    expect(findSpan(undefined, "1")).toBeNull();
  });

  it("payloadText pretty-prints JSON and passes plain text through", () => {
    expect(payloadText('{"a":1}')).toBe('{\n  "a": 1\n}');
    expect(payloadText({ b: 2 })).toBe('{\n  "b": 2\n}');
    expect(payloadText("hello")).toBe("hello");
    expect(payloadText("{not json")).toBe("{not json");
    expect(payloadText(null)).toBe("");
  });
});
