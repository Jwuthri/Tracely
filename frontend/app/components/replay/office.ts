// Pure geometry + pose engine for the Fleet office (tested — no React, no fetch).
//
// The office is a 100×100 coordinate space (percent of the stage). layoutOffice seats every
// actor; poseAt answers, for one actor at play-time t: WHERE they stand, what they're DOING,
// and what floats above their head. The component only animates between poses.

import { isContainer, isCustomer, type PlayEvent, type ReplayActor } from "./timeline";

export type Pt = { x: number; y: number };

export type OfficeLayout = {
  desks: Record<string, Pt>;
  library: Pt; // stand point in front of the bookshelf
  tools: Pt;   // stand point at the tool wall
  door: Pt;    // where characters enter from
  customer: Pt; // where the customer stands, just inside the door
  coffee: Pt;
};

/** `faded`: a last word that has been up for a while — still readable, visually quieter.
 *  A chip's `sub` is what the tool returned, for a turn that ends on a tool run. */
export type Bubble = (
  | { type: "speech"; text: string }
  | { type: "thought"; text: string }
  | { type: "chip"; icon: "tool" | "skill" | "call"; text: string; sub?: string }
  | { type: "error"; text: string }
) & { faded?: boolean };

export type Pose = {
  x: number;
  y: number;
  at: "desk" | "library" | "tools" | "peer" | "door";
  action: PlayEvent | null;
  bubble: Bubble | null;
  facing: 1 | -1;
  entered: boolean;
  working: boolean;
};

/** Seat roots in a row across the floor, sub-agents on a lower row clustered near their
 *  parent. Fixed furniture hugs the walls. All positions are % of the stage. */
export function layoutOffice(all: ReplayActor[]): OfficeLayout {
  const actors = all.filter((a) => !isCustomer(a)); // the customer has no desk — they stand by the door
  const roots = actors.filter((a) => !a.parent);
  const desks: Record<string, Pt> = {};
  const rootY = 40;
  const subY = 66;
  // Roots stop short of the right corner: that is the customer's spot, and their question
  // hangs leftward from it in the same band a root's bubble rises into.
  roots.forEach((r, i) => {
    const x = roots.length === 1 ? 46 : 20 + (i * 48) / Math.max(1, roots.length - 1);
    desks[r.id] = { x, y: rootY };
  });
  // subs cluster under their parent; siblings fan out around the parent's x
  const byParent = new Map<string, ReplayActor[]>();
  for (const a of actors) {
    if (a.parent) byParent.set(a.parent, [...(byParent.get(a.parent) ?? []), a]);
  }
  for (const [pid, kids] of byParent) {
    const px = desks[pid]?.x ?? 50;
    // step shrinks with the sibling count so a big team fans out instead of clamping into a
    // pile at the floor's edge; deeper generations drop a row.
    const step = Math.min(18, 60 / Math.max(1, kids.length - 1));
    kids.forEach((k, i) => {
      const spread = kids.length === 1 ? 0 : (i - (kids.length - 1) / 2) * step;
      desks[k.id] = { x: clamp(px + spread, 14, 86), y: Math.min(subY + (k.depth - 1) * 11, 84) };
    });
  }
  // orphans (parent outside the window) get root seating at the end, wrapping to new rows
  let extra = 0;
  for (const a of actors) {
    if (!desks[a.id]) {
      desks[a.id] = { x: 22 + (extra % 4) * 18, y: rootY + Math.floor(extra / 4) * 13 };
      extra++;
    }
  }
  return {
    desks,
    library: { x: 8.5, y: 52 },
    tools: { x: 91.5, y: 52 },
    door: { x: 88, y: 22 },
    customer: { x: 87, y: 31 },
    coffee: { x: 8, y: 84 },
  };
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** How long a finished event reads as FRESH (ms of play time). A last word stays up until the
 *  actor acts again — it just fades after this. */
const LINGER = 1600;

/** What an actor shows for ONE beat — in flight or finished, the same rendering either way.
 *  An llm is the interesting case: a model that answered with a tool call has no words, and
 *  showing "…" for it (the old behaviour) meant a supervisor stood there saying nothing for
 *  most of the conversation. Order: failure, handoff, words, the tools it called, the model. */
export function wordOf(e: PlayEvent, events: PlayEvent[] = []): Bubble | null {
  if (e.status === "error") return { type: "error", text: e.name };
  if (e.delegate_to || e.kind === "delegate") return { type: "speech", text: e.say || `→ ${e.name}` };
  if (e.kind === "ask") return { type: "speech", text: e.detail || "…" };
  if (e.kind === "tool" || e.kind === "skill")
    return { type: "chip", icon: e.kind === "skill" ? "skill" : "tool", text: e.name, sub: e.detail };
  if (e.kind === "think") return e.detail ? { type: "thought", text: e.detail } : null;
  if (e.kind !== "llm") return null;
  const calls = e.calls ?? [];
  // `detail` is "→ a, b" when the model only called tools — the chip says that better.
  const spoke = e.detail && !(calls.length && e.detail.startsWith("→")) ? e.detail : "";
  if (spoke) return { type: "speech", text: spoke };
  if (calls.length) return { type: "chip", icon: "call", text: calls.join(", ") };
  // Nothing recorded on the span itself. ONLY the actor's last beat of the turn may borrow the
  // turn envelope's answer (frameworks record the final reply on the graph root): letting every
  // silent llm borrow it made each of them repeat the conversation's last message.
  const isLastOfTurn = !events.some(
    (o) => !isContainer(o) && o.actor === e.actor && o.trace_id === e.trace_id && o.pt > e.pt,
  );
  const owned = isLastOfTurn
    ? events.find((c) => isContainer(c) && c.actor === e.actor && c.trace_id === e.trace_id && c.detail)?.detail
    : "";
  if (owned) return { type: "speech", text: owned };
  return e.model ? { type: "chip", icon: "call", text: `✎ ${e.model}` } : null;
}

/** Play-time each of an actor's beats OWNS the bubble. Beats are laid end to end in order,
 *  each holding the head for at least MIN_DWELL: prod traces fire an llm and the tool it just
 *  asked for ~1ms apart, and since the newer beat masks the older one, the supervisor's
 *  decision flashed for a millisecond and was gone. A beat may lag its own start by at most
 *  MAX_LAG so a burst of spans can't drift the bubble far from what the character is doing;
 *  the last beat holds indefinitely (that is the "last word stays up" rule). */
const MIN_DWELL = 650;
const MAX_LAG = 1300;

export function bubbleWindows(actorId: string, events: PlayEvent[]): { e: PlayEvent; from: number }[] {
  const out: { e: PlayEvent; from: number }[] = [];
  for (const e of events) {
    if (e.actor !== actorId || isContainer(e)) continue;
    const prev = out[out.length - 1];
    const from = prev ? Math.min(Math.max(e.pt, prev.from + MIN_DWELL), e.pt + MAX_LAG) : e.pt;
    out.push({ e, from });
  }
  return out;
}

/** The beat whose bubble is on screen at t (see `bubbleWindows`). */
export function bubbleAt(actorId: string, events: PlayEvent[], t: number): PlayEvent | null {
  const windows = bubbleWindows(actorId, events);
  let found: PlayEvent | null = null;
  for (const w of windows) {
    if (w.from > t) break;
    found = w.e;
  }
  return found;
}

/** An actor's last beat at or before t, optionally within one turn. Ordered by START, like the
 *  bubble queue and like the conversation itself: the message an agent produced last is the one
 *  it began last, even when an earlier, longer call finished after it. */
export function lastEventOf(actorId: string, events: PlayEvent[], t: number, traceId?: string): PlayEvent | null {
  let last: PlayEvent | null = null;
  for (const e of events) {
    if (e.pt > t) break;
    if (e.actor !== actorId || isContainer(e) || (traceId !== undefined && e.trace_id !== traceId)) continue;
    last = e;
  }
  return last;
}

/** One row per turn: what the customer asked and every agent's last word IN that turn — the
 *  transcript strip. A sub-agent invoked in a turn shows its last word for that invocation. */
export type TurnDigest = {
  trace_id: string; pt: number; ask: string; words: { actor: string; bubble: Bubble }[];
};
export function turnDigest(events: PlayEvent[], actors: ReplayActor[]): TurnDigest[] {
  const turns: TurnDigest[] = [];
  const byTrace = new Map<string, TurnDigest>();
  for (const e of events) {
    let turn = byTrace.get(e.trace_id);
    if (!turn) {
      turn = { trace_id: e.trace_id, pt: e.pt, ask: "", words: [] };
      byTrace.set(e.trace_id, turn);
      turns.push(turn);
    }
    if (e.kind === "ask") turn.ask = e.detail;
  }
  for (const turn of turns) {
    for (const a of actors) {
      if (isCustomer(a)) continue;
      const last = lastEventOf(a.id, events, Infinity, turn.trace_id);
      const bubble = last && wordOf(last, events);
      if (bubble) turn.words.push({ actor: a.id, bubble });
    }
  }
  return turns;
}

/** The most interesting in-flight, non-container event for an actor at t (latest started). */
function inflightOf(actorId: string, events: PlayEvent[], t: number): PlayEvent | null {
  let found: PlayEvent | null = null;
  for (const e of events) {
    if (e.pt > t) break;
    if (e.actor !== actorId || isContainer(e)) continue;
    if (t < e.pt + e.pdur) found = e;
  }
  return found;
}

/** An active handoff FROM this actor: an in-flight llm/tool event with delegate_to, or a
 *  DELEGATE container while the actor has nothing of their own in flight. */
function delegationOf(actorId: string, events: PlayEvent[], t: number): PlayEvent | null {
  let found: PlayEvent | null = null;
  for (const e of events) {
    if (e.pt > t) break;
    if (e.actor !== actorId || !e.delegate_to) continue;
    if (t < e.pt + e.pdur) found = e;
  }
  return found;
}

export function poseAt(
  actor: ReplayActor,
  events: PlayEvent[],
  t: number,
  layout: OfficeLayout,
  slot = 0,
): Pose {
  if (isCustomer(actor)) {
    // The customer is there the whole time, just inside the door, and holds this turn's
    // question up until the next one — the office works for THEM.
    let ask: PlayEvent | null = null;
    for (const e of events) { if (e.pt > t) break; if (e.actor === actor.id) ask = e; }
    const live = ask !== null && t < ask.pt + ask.pdur;
    return {
      x: layout.customer.x, y: layout.customer.y, at: "door", action: live ? ask : null,
      bubble: ask ? { ...(wordOf(ask) as Bubble), faded: !live } : null,
      facing: -1, entered: true, working: live,
    };
  }
  const desk = layout.desks[actor.id] ?? { x: 50, y: 50 };
  // The whole team is seated from t=0 — a sub-agent idles at its desk until the main agent
  // brings it work, rather than popping into existence at its first span.

  const inflight = inflightOf(actor.id, events, t);
  const delegation = delegationOf(actor.id, events, t);
  const jitter = (slot % 3) * 4 - 4; // stand-point offset so two actors never fully overlap

  // where — a station beats the desk; an explicit handoff walks to the callee's desk
  let x = desk.x;
  let y = desk.y;
  let at: Pose["at"] = "desk";
  const station = inflight?.station ?? (delegation ? "peer" : "desk");
  if (station === "library") {
    x = layout.library.x + 3;
    y = layout.library.y + jitter;
    at = "library";
  } else if (station === "computer") {
    x = layout.tools.x - 3;
    y = layout.tools.y + jitter;
    at = "tools";
  } else if (station === "peer" && (inflight?.delegate_to || delegation)) {
    const target = layout.desks[(inflight?.delegate_to || delegation?.delegate_to) ?? ""];
    if (target) {
      x = target.x + 8;
      y = target.y + 2;
      at = "peer";
    }
  }

  // What floats above their head: ONE rule for the whole conversation. `bubbleAt` picks the
  // beat that owns the head right now — in flight or long finished, each beat guaranteed its
  // turn on screen — and `wordOf` renders it. The last beat holds until the actor acts again,
  // fading once it is no longer fresh, so nobody ever stands there with an empty head.
  let bubble: Bubble | null = null;
  const held = delegation ?? bubbleAt(actor.id, events, t);
  const word = held && wordOf(held, events);
  if (held && word) {
    const ended = held.pt + held.pdur;
    bubble = { ...word, faded: t > ended && t - ended > LINGER };
  }

  return {
    x,
    y,
    at,
    action: inflight,
    bubble,
    facing: x < desk.x - 1 ? -1 : 1,
    entered: true,
    working: inflight !== null || delegation !== null,
  };
}

/** Skills on the shelf: every distinct thing performed at the library. */
export function librarySkills(events: PlayEvent[]): string[] {
  return [...new Set(events.filter((e) => e.station === "library").map((e) => e.name))];
}

/** Tools on the wall: everything actually RUN at the computer first (lit), then the declared
 *  catalog that never ran (dim) — so a big catalog can't evict the tools that did the work. */
export function wallTools(
  events: PlayEvent[],
  declared: DeclaredTool[],
): { name: string; used: boolean }[] {
  const used = [...new Set(events.filter((e) => e.station === "computer").map((e) => e.name))];
  const usedSet = new Set(used);
  const seen = new Set(used);
  return [
    ...used.map((name) => ({ name, used: true })),
    ...declared
      .filter((d) => !usedSet.has(d.name) && !seen.has(d.name) && seen.add(d.name))
      .map((d) => ({ name: d.name, used: false })),
  ];
}

/** A tool as the caller declared it in the agent catalog. */
export type DeclaredTool = { name: string; description: string };

/** Everything the side panel shows for one shelf item — a book at the library, a tool on the
 *  wall. Same idea as the personnel file, for the things instead of the people. */
export type StationInfo = {
  name: string;
  kind: "skill" | "tool";
  description: string;
  runs: number;
  failures: number;
  by: string[];          // actor ids that used it, first use first
  lastResult: string;    // what it returned the last time it ran
  used: boolean;
};

/** Build that card. `description` prefers what the catalog declares; a skill (never declared)
 *  falls back to what it actually returned, so the card is never blank for something that ran. */
export function stationInfo(
  name: string,
  kind: "skill" | "tool",
  events: PlayEvent[],
  declared: DeclaredTool[] = [],
): StationInfo {
  const station = kind === "skill" ? "library" : "computer";
  const runs = events.filter((e) => e.name === name && e.station === station);
  const by: string[] = [];
  for (const e of runs) if (!by.includes(e.actor)) by.push(e.actor);
  const lastResult = [...runs].reverse().find((e) => e.detail)?.detail ?? "";
  const declaredDesc = declared.find((d) => d.name === name)?.description ?? "";
  return {
    name,
    kind,
    description: declaredDesc || lastResult,
    runs: runs.length,
    failures: runs.filter((e) => e.status === "error").length,
    by,
    lastResult,
    used: runs.length > 0,
  };
}

/** The narration line for the LED sign: the latest started event, described. */
export function narrate(
  events: PlayEvent[],
  t: number,
  nameOf: (id: string) => string,
): string {
  // Prefer what is IN FLIGHT right now; once nothing is, speak of the last beat in the past
  // tense — a sign stuck on "X runs Y" seconds after Y finished is lying.
  let current: PlayEvent | null = null;
  let askLeads = false;
  let lastEnded: PlayEvent | null = null;
  let lastEnd = -1;
  for (const e of events) {
    if (e.pt > t) break;
    if (isContainer(e) && !e.delegate_to) continue;
    if (t < e.pt + e.pdur) {
      // the customer's question leads the sign for as long as it is fresh — the agents start
      // working the same instant, and "sup drafts a reply" before anyone heard the ask is odd
      if (!askLeads) current = e;
      askLeads ||= e.kind === "ask";
    } else if (e.pt + e.pdur > lastEnd) {
      lastEnded = e;
      lastEnd = e.pt + e.pdur;
    }
  }
  if (current) {
    const who = nameOf(current.actor);
    if (current.delegate_to) return `${who} → ${nameOf(current.delegate_to)}: ${current.say || "handoff"}`;
    switch (current.kind) {
      case "ask":
        return `customer asks: ${current.detail || "…"}`;
      case "think":
        return `${who} is thinking…`;
      case "skill":
        return `${who} reads «${current.name}»`;
      case "tool":
        return `${who} runs ${current.name}`;
      case "llm":
        // a model turn that answered with a tool call is not "drafting a reply" — say what it
        // actually asked for, the same thing its bubble shows
        return current.calls?.length
          ? `${who} calls ${current.calls.join(", ")}`
          : `${who} drafts a reply (${current.model || "llm"})`;
      default:
        return `${who} · ${current.name}`;
    }
  }
  if (lastEnded) {
    const who = nameOf(lastEnded.actor);
    if (lastEnded.delegate_to) return `${who} → ${nameOf(lastEnded.delegate_to)} · handed off`;
    if (lastEnded.kind === "ask") return "customer is waiting…";
    return `${who} · ${lastEnded.name} ✓`;
  }
  return "office opens…";
}
