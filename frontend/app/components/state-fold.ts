// Shared-state reconstruction for a conversation. Agent harnesses (LangGraph's `State`, a
// hand-rolled scratchpad, a conversation-scoped store) thread one mutable object through the graph;
// what you debug is never the snapshot but the DELTA — "`plan` was emptied at step 4, in `replan`".
//
// Two sources of deltas, both already on the span, neither costing an extra fetch:
//   • EXPLICIT — `tracely.state.<key>` metadata written by the SDK's `set_state()`.
//   • OUTPUT   — a LangGraph node span, whose output IS the channel dict the node returned. The
//                ingest mapper marks those with `tracely.state_source=output` rather than copying
//                the (often large) body into metadata a second time.
// Folding the deltas in time order gives the state at any point, so nothing has to be stored.

import type { SpanOut } from "../lib/api";

const PREFIX = "tracely.state.";
const SOURCE = "tracely.state_source";

function parseJson(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return s; // a plain string channel the SDK stamped verbatim
  }
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** The state channels this span wrote, or null if it wrote none. */
export function spanStateWrites(span: SpanOut): Record<string, unknown> | null {
  const meta = span.metadata ?? {};
  const explicit: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(meta)) {
    if (k.startsWith(PREFIX)) explicit[k.slice(PREFIX.length)] = parseJson(v);
  }
  if (Object.keys(explicit).length > 0) return explicit;
  // A node can legitimately return a non-dict (a Command, a bare list) — that isn't a channel map.
  if (meta[SOURCE] === "output" && span.output) {
    const parsed = parseJson(span.output);
    if (isPlainObject(parsed) && Object.keys(parsed).length > 0) return parsed;
  }
  return null;
}

/** Does this span carry state at all? Parse-free, for gating UI that would otherwise render empty
 * on every project that sends none — cheap enough to run over every loaded span on each render. */
export function spanHasState(span: SpanOut): boolean {
  const meta = span.metadata ?? {};
  if (meta[SOURCE] === "output") return true;
  return Object.keys(meta).some((k) => k.startsWith(PREFIX));
}

export type StateChange = {
  key: string;
  value: unknown;
  // `same` = the step rewrote a channel with the value it already had. Noise, but worth keeping
  // distinguishable rather than dropped: a node that keeps re-writing an unchanged channel is
  // itself a finding.
  kind: "add" | "update" | "same";
};

export type StateStep = {
  span_id: string;
  at: string;
  label: string;
  agent_id: string;
  turn_id: string;
  changes: StateChange[];
};

/** Fold every span's writes, oldest first, into a step timeline + the resulting state. */
export function foldState(spans: SpanOut[]): { steps: StateStep[]; final: Record<string, unknown> } {
  const acc: Record<string, unknown> = {};
  const lastEncoded = new Map<string, string>();
  const steps: StateStep[] = [];

  const ordered = [...spans].sort(
    (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime(),
  );

  for (const span of ordered) {
    const writes = spanStateWrites(span);
    if (!writes) continue;
    const changes: StateChange[] = [];
    for (const [key, value] of Object.entries(writes)) {
      const encoded = JSON.stringify(value) ?? "";
      const kind = !lastEncoded.has(key)
        ? "add"
        : lastEncoded.get(key) === encoded
          ? "same"
          : "update";
      lastEncoded.set(key, encoded);
      acc[key] = value;
      changes.push({ key, value, kind });
    }
    steps.push({
      span_id: span.span_id,
      at: span.start_time,
      label: span.step_name || span.name || span.span_id,
      agent_id: span.agent_id ?? "",
      turn_id: span.turn_id ?? "",
      changes,
    });
  }
  return { steps, final: { ...acc } };
}
