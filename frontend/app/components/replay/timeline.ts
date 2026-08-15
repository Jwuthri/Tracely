// Pure helpers for the conversation replay stage (tested — no React, no fetch).

export type ReplayActor = {
  id: string; name: string; kind: "agent" | "subagent"; parent: string;
  depth: number; first_ms: number; last_ms: number; events: number; errors: number;
};

export type ReplayEvent = {
  t_ms: number; dur_ms: number; actor: string; kind: string; name: string;
  status: "ok" | "error"; model: string; detail: string; span_id: string;
  trace_id: string; turn_id: string;
};

/** An event placed on the PLAY clock (gaps squeezed), keeping its real timestamp. */
export type PlayEvent = ReplayEvent & { pt: number; pdur: number; index: number };

export const KIND_STYLE: Record<string, { label: string; color: string; icon: string }> = {
  turn: { label: "turn", color: "#7aa2ff", icon: "▶" },
  spawn: { label: "sub-agent", color: "#c084fc", icon: "✦" },
  llm: { label: "llm", color: "#34d399", icon: "✎" },
  tool: { label: "tool", color: "#fb923c", icon: "⚙" },
  guard: { label: "guard", color: "#fbbf24", icon: "⛨" },
  step: { label: "step", color: "#8b94a7", icon: "·" },
};

export const kindStyle = (k: string) => KIND_STYLE[k] ?? KIND_STYLE.step;

const MAX_GAP_MS = 400;  // dead air between turns is squeezed to this
const MIN_DUR_MS = 140;  // a 3ms tool call still needs to be seeable

/**
 * Lay events on a play clock: real gaps longer than MAX_GAP_MS collapse (a conversation with a
 * 20s pause between turns would otherwise be 20s of an empty stage), every event gets a floor
 * duration so instant spans are still visible, and ordering is preserved.
 */
export function toPlayEvents(events: ReplayEvent[]): { events: PlayEvent[]; total: number } {
  const sorted = [...events].sort((a, b) => a.t_ms - b.t_ms);
  const out: PlayEvent[] = [];
  let clock = 0;
  let prevReal = sorted.length ? sorted[0].t_ms : 0;
  sorted.forEach((e, index) => {
    clock += Math.min(Math.max(0, e.t_ms - prevReal), MAX_GAP_MS);
    prevReal = e.t_ms;
    out.push({ ...e, index, pt: clock, pdur: Math.max(e.dur_ms, MIN_DUR_MS) });
  });
  const total = out.reduce((m, e) => Math.max(m, e.pt + e.pdur), 0);
  return { events: out, total };
}

/** Events in flight at play-time `t`. */
export function activeAt(events: PlayEvent[], t: number): PlayEvent[] {
  return events.filter((e) => t >= e.pt && t < e.pt + e.pdur);
}

/** The most recent event at or before `t` for each actor — what that character is "doing". */
export function currentByActor(events: PlayEvent[], t: number): Record<string, PlayEvent> {
  const out: Record<string, PlayEvent> = {};
  for (const e of events) {
    if (e.pt > t) break;
    if (e.kind === "turn" || e.kind === "spawn") continue; // containers, not actions
    out[e.actor] = e;
  }
  return out;
}

/** An actor is on stage from its first span onward. They ARRIVE during the replay (dimmed
 *  until then) and stay — dimming everyone again at the end just looked like a bug. */
export function onStage(actor: ReplayActor, events: PlayEvent[], t: number): boolean {
  const first = events.find((e) => e.actor === actor.id);
  return first !== undefined && t >= first.pt;
}

/** Actors ordered so each sub-agent sits directly under its parent. */
export function orderActors(actors: ReplayActor[]): ReplayActor[] {
  const roots = actors.filter((a) => !a.parent);
  const kids = (id: string) => actors.filter((a) => a.parent === id);
  const out: ReplayActor[] = [];
  const walk = (a: ReplayActor) => { out.push(a); kids(a.id).forEach(walk); };
  roots.forEach(walk);
  // orphans (parent outside the window) keep their original position at the end
  for (const a of actors) if (!out.includes(a)) out.push(a);
  return out;
}

export const fmtMs = (ms: number) => (ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`);
