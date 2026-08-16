import { describe, expect, it } from "vitest";
import { layoutOffice, librarySkills, narrate, poseAt, wallTools } from "./office";
import { toPlayEvents, type ReplayActor, type ReplayEvent } from "./timeline";

const actor = (id: string, parent = "", depth = 0): ReplayActor =>
  ({ id, name: id, kind: depth ? "subagent" : "agent", parent, depth, first_ms: 0, last_ms: 0, events: 0, errors: 0 }) as ReplayActor;

const ev = (t: number, dur: number, a: string, kind: string, name: string, extra: Partial<ReplayEvent> = {}): ReplayEvent => ({
  t_ms: t, dur_ms: dur, actor: a, kind, name, status: "ok", model: "", detail: "",
  span_id: `${a}-${name}-${t}`, trace_id: "t", turn_id: "", station: "desk", delegate_to: "", say: "", ...extra,
});

describe("layoutOffice", () => {
  const actors = [actor("sup"), actor("faq", "sup", 1), actor("audit", "sup", 1)];
  const l = layoutOffice(actors);
  it("keeps every desk on the floor", () => {
    for (const p of Object.values(l.desks)) {
      expect(p.x).toBeGreaterThan(10); expect(p.x).toBeLessThan(90);
      expect(p.y).toBeGreaterThan(20); expect(p.y).toBeLessThan(90);
    }
  });
  it("seats sub-agents on a lower row near their parent", () => {
    expect(l.desks.faq.y).toBeGreaterThan(l.desks.sup.y);
    expect(Math.abs(l.desks.faq.x - l.desks.sup.x)).toBeLessThan(25);
  });
  it("orphan parents don't crash and get a desk", () => {
    const o = layoutOffice([actor("ghost-child", "missing", 1)]);
    expect(o.desks["ghost-child"]).toBeDefined();
  });
});

describe("poseAt", () => {
  const actors = [actor("sup"), actor("faq", "sup", 1)];
  const layout = layoutOffice(actors);
  const script = toPlayEvents([
    ev(0, 400, "sup", "llm", "chat"),
    ev(500, 600, "sup", "llm", "chat2", { delegate_to: "faq", say: "check the warranty", station: "peer" }),
    ev(1200, 300, "faq", "tool", "lookup_kb", { station: "library" }),
    ev(1600, 300, "faq", "tool", "charge", { station: "computer" }),
    ev(2000, 200, "sup", "think", "thinking", { detail: "hmm" }),
  ]).events;

  it("everyone is seated idle at their desk from t=0", () => {
    const p = poseAt(actors[1], script, 100, layout);
    expect(p.entered).toBe(true);
    expect(p.at).toBe("desk");
    expect(p.working).toBe(false);
    expect(p.bubble).toBeNull();
  });
  it("walks to the callee's desk on a handoff and says the task", () => {
    const p = poseAt(actors[0], script, 700, layout);
    expect(p.at).toBe("peer");
    expect(Math.abs(p.x - layout.desks.faq.x)).toBeLessThan(12);
    expect(p.bubble).toEqual({ type: "speech", text: "check the warranty" });
  });
  it("reads knowledge at the library, runs actions at the tool wall", () => {
    // play clock: gaps over 400ms are squeezed — library is in flight at pt 800..1100,
    // the computer tool at 1200..1500, thinking at 1600..1800
    expect(poseAt(actors[1], script, 900, layout).at).toBe("library");
    expect(poseAt(actors[1], script, 1300, layout).at).toBe("tools");
  });
  it("thinks in a thought cloud at the desk", () => {
    const p = poseAt(actors[0], script, 1700, layout);
    expect(p.at).toBe("desk");
    expect(p.bubble?.type).toBe("thought");
  });
  it("idle actors sit at their desk with no bubble (after linger)", () => {
    const p = poseAt(actors[1], script, 9000, layout);
    expect(p.at).toBe("desk");
    expect(p.bubble).toBeNull();
    expect(p.working).toBe(false);
  });
});

it("librarySkills and wallTools collect the right furniture", () => {
  const script = toPlayEvents([
    ev(0, 100, "a", "skill", "refund-flow", { station: "library" }),
    ev(200, 100, "a", "tool", "lookup_kb", { station: "library" }),
    ev(400, 100, "a", "tool", "charge_card", { station: "computer" }),
  ]).events;
  expect(librarySkills(script)).toEqual(["refund-flow", "lookup_kb"]);
  // executed tools come first (lit); declared-but-never-run follow (dim) — a big catalog
  // can never evict the tools that actually ran
  expect(wallTools(script, ["send_reply", "charge_card"])).toEqual([
    { name: "charge_card", used: true },
    { name: "send_reply", used: false },
  ]);
});

it("narrate describes the current beat", () => {
  const script = toPlayEvents([
    ev(0, 300, "sup", "llm", "chat", { delegate_to: "faq", say: "go", station: "peer" }),
    ev(400, 300, "faq", "tool", "lookup_kb", { station: "library" }),
  ]).events;
  const name = (id: string) => id.toUpperCase();
  expect(narrate(script, 100, name)).toBe("SUP → FAQ: go");
  expect(narrate(script, 500, name)).toBe("FAQ runs lookup_kb");
  expect(narrate(script, 5000, name)).toBe("FAQ · lookup_kb ✓"); // past tense once it ended
});

it("afterglow shows the most recently FINISHED word, not the longest-running one", () => {
  const actors = [actor("a")];
  const layout = layoutOffice(actors);
  const script = toPlayEvents([
    ev(0, 2000, "a", "llm", "long-early", { detail: "early words" }),
    ev(500, 300, "a", "llm", "short-late", { detail: "the last word" }),
  ]).events;
  // both ended by 2100; long-early ended LAST (pt0+2000) so its words linger
  const p = poseAt(actors[0], script, 2100, layout);
  expect(p.bubble).toEqual({ type: "speech", text: "early words" });
});
