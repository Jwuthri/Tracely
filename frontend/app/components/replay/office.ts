// Pure geometry + pose engine for the Fleet office (tested — no React, no fetch).
//
// The office is a 100×100 coordinate space (percent of the stage). layoutOffice seats every
// actor; poseAt answers, for one actor at play-time t: WHERE they stand, what they're DOING,
// and what floats above their head. The component only animates between poses.

import { isContainer, type PlayEvent, type ReplayActor } from "./timeline";

export type Pt = { x: number; y: number };

export type OfficeLayout = {
  desks: Record<string, Pt>;
  library: Pt; // stand point in front of the bookshelf
  tools: Pt;   // stand point at the tool wall
  door: Pt;    // where characters enter from
  coffee: Pt;
};

export type Bubble =
  | { type: "speech"; text: string }
  | { type: "thought"; text: string }
  | { type: "chip"; icon: "tool" | "skill"; text: string }
  | { type: "error"; text: string };

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
export function layoutOffice(actors: ReplayActor[]): OfficeLayout {
  const roots = actors.filter((a) => !a.parent);
  const desks: Record<string, Pt> = {};
  const rootY = 40;
  const subY = 66;
  roots.forEach((r, i) => {
    const x = roots.length === 1 ? 50 : 22 + (i * 56) / Math.max(1, roots.length - 1);
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
    coffee: { x: 8, y: 84 },
  };
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** How long a finished event keeps its bubble up (ms of play time). */
const LINGER = 1600;

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
  const desk = layout.desks[actor.id] ?? { x: 50, y: 50 };
  const mine = events.filter((e) => e.actor === actor.id);
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

  // what floats above their head
  let bubble: Bubble | null = null;
  const active = inflight ?? delegation;
  if (active) {
    if (active.status === "error") {
      bubble = { type: "error", text: active.name };
    } else if (active.delegate_to) {
      bubble = { type: "speech", text: active.say || `→ ${active.name}` };
    } else if (active.kind === "think") {
      bubble = { type: "thought", text: active.detail || "…" };
    } else if (active.kind === "skill") {
      bubble = { type: "chip", icon: "skill", text: active.name };
    } else if (active.kind === "tool") {
      bubble = { type: "chip", icon: "tool", text: active.name };
    } else if (active.kind === "delegate" && active.say) {
      // explicit handoff whose callee exported no spans: the walk has nowhere to go, but the
      // task itself is real — say it from the desk instead of vanishing.
      bubble = { type: "speech", text: active.say };
    } else if (active.kind === "llm") {
      bubble = { type: "thought", text: "…" };
    }
  } else {
    // afterglow: the MOST RECENTLY FINISHED reply or failure lingers so it can be read —
    // picking by start time let a long-running early event mask the actual last word.
    let last: PlayEvent | null = null;
    let lastEnd = -1;
    for (const e of mine) {
      if (e.pt > t) break;
      if (isContainer(e)) continue;
      const end = e.pt + e.pdur;
      if (end <= t && t - end < LINGER && end > lastEnd) {
        last = e;
        lastEnd = end;
      }
    }
    if (last?.status === "error") bubble = { type: "error", text: last.name };
    else if (last?.kind === "llm" && last.detail) bubble = { type: "speech", text: last.detail };
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
  declared: string[],
): { name: string; used: boolean }[] {
  const used = [...new Set(events.filter((e) => e.station === "computer").map((e) => e.name))];
  const usedSet = new Set(used);
  return [
    ...used.map((name) => ({ name, used: true })),
    ...[...new Set(declared)].filter((n) => !usedSet.has(n)).map((name) => ({ name, used: false })),
  ];
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
  let lastEnded: PlayEvent | null = null;
  let lastEnd = -1;
  for (const e of events) {
    if (e.pt > t) break;
    if (isContainer(e) && !e.delegate_to) continue;
    if (t < e.pt + e.pdur) current = e;
    else if (e.pt + e.pdur > lastEnd) {
      lastEnded = e;
      lastEnd = e.pt + e.pdur;
    }
  }
  if (current) {
    const who = nameOf(current.actor);
    if (current.delegate_to) return `${who} → ${nameOf(current.delegate_to)}: ${current.say || "handoff"}`;
    switch (current.kind) {
      case "think":
        return `${who} is thinking…`;
      case "skill":
        return `${who} reads «${current.name}»`;
      case "tool":
        return `${who} runs ${current.name}`;
      case "llm":
        return `${who} drafts a reply (${current.model || "llm"})`;
      default:
        return `${who} · ${current.name}`;
    }
  }
  if (lastEnded) {
    const who = nameOf(lastEnded.actor);
    if (lastEnded.delegate_to) return `${who} → ${nameOf(lastEnded.delegate_to)} · handed off`;
    return `${who} · ${lastEnded.name} ✓`;
  }
  return "office opens…";
}
