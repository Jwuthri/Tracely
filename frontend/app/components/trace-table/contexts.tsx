"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useSyncExternalStore } from "react";
import type { EvalScore } from "../../lib/api";
import type { EvaluatorDef } from "../../lib/evaluators";

// The contexts the table's cells read instead of taking props. Rows nest four deep
// (conversation → turn → span → cell), so threading run state and live scores down by hand meant
// every intermediate row re-rendering on any change — and every new control touching four
// signatures. They live here, apart from the components that consume them, because the row and
// cell modules both need them and importing either from the other would be a cycle.

// ── conversation multi-select (its own leading column, like the chevron/run controls) ───────────
export type SelectView = {
  enabled: boolean;
  selected: Set<string>;
  toggle: (thread: string) => void;
  toggleAll: () => void;
  allSelected: boolean;
  someSelected: boolean;
};
export const SelectContext = createContext<SelectView>({
  enabled: false, selected: new Set(), toggle: () => {}, toggleAll: () => {}, allSelected: false, someSelected: false,
});

// Control cells the table always renders, in order: chevron · run · copy · agents. The header, the
// body rows and every colSpan all count off this ONE constant — they used to be three independent
// hardcoded lists, so adding a control rendered a 4th body cell against a 3-cell header and shifted
// every data column one to the left.
export const CTRL_CELLS = 4;

export function useCtrlCount(): number {
  return CTRL_CELLS + (useContext(SelectContext).enabled ? 1 : 0);
}

// Tracely's own runs, listed alongside real ones while the Evals toggle is on. They get a tag
// rather than a colour-only hint: "this row is the product grading something" is not something a
// reader should have to infer, and eval must never be mistaken for sim (one is how a run was
// judged, the other is how a conversation was driven).

// ── evaluation columns (dynamic metric columns + live run state) ─────────────────
// Live results and run actions reach the deeply nested cells via context, so the
// row/cell component tree stays prop-free. Keys:
//   live score   →  `th:<thread>|<name>` | `tr:<trace>|<name>` | `span:<span>|<name>`
//   busy row     →  `th:<thread>` | `tr:<trace>`     busy column → score_name
export type EvalView = {
  busyCols: Set<string>;
  busyRows: Set<string>;
  hasEvaluators: boolean;
  runThread: (thread: string) => void;
  runTrace: (trace: string) => void;
  runColumn: (ev: EvaluatorDef) => void;
  editColumn: (ev: EvaluatorDef) => void;
  removeColumn: (ev: EvaluatorDef) => void;
};
export const EvalViewContext = createContext<EvalView>({
  busyCols: new Set(), busyRows: new Set(), hasEvaluators: false,
  runThread: () => {}, runTrace: () => {}, runColumn: () => {}, editColumn: () => {}, removeColumn: () => {},
});

// Live eval-run scores ride a SEPARATE, reference-stable store (not the EvalView context value) so a
// streamed result re-renders ONLY the cell whose score arrived — not the whole grid. Each cell
// subscribes to its own key via useSyncExternalStore; the store object's identity never changes, so
// providing it through context never triggers a re-render.
export type LiveScoreStore = {
  get: (key: string) => EvalScore | undefined;
  set: (key: string, score: EvalScore) => void;
  subscribe: (key: string, cb: () => void) => () => void;
};
export const LiveScoreContext = createContext<LiveScoreStore>({
  get: () => undefined, set: () => {}, subscribe: () => () => {},
});

export function useLiveScoreStore(): LiveScoreStore {
  const scores = useRef(new Map<string, EvalScore>());
  const listeners = useRef(new Map<string, Set<() => void>>());
  return useMemo(
    () => ({
      get: (key) => scores.current.get(key),
      set: (key, score) => {
        scores.current.set(key, score);
        listeners.current.get(key)?.forEach((cb) => cb());
      },
      subscribe: (key, cb) => {
        let set = listeners.current.get(key);
        if (!set) {
          set = new Set();
          listeners.current.set(key, set);
        }
        set.add(cb);
        return () => {
          set!.delete(cb);
        };
      },
    }),
    [],
  );
}

// Subscribe a cell to just its own score key (empty key = N/A cell → never subscribes/re-renders).
export function useLiveScore(key: string): EvalScore | undefined {
  const store = useContext(LiveScoreContext);
  return useSyncExternalStore(
    useCallback((cb) => (key ? store.subscribe(key, cb) : () => {}), [store, key]),
    () => (key ? store.get(key) : undefined),
    () => undefined,
  );
}

// ── rolling summary (the per-row accumulated summary at C/M/S levels) ─────────────
// Fetched once per thread (the conversation row triggers it) and merged into id-keyed maps, so the
// turn / step cells just read by trace_id / span_id. `undefined` = not loaded yet, "" = no summary.
// The rolling summary is a flat JSON list of items: [{role, type, content, …}]. The compacted
// older history is one item with role "prev_summary".
export type SummaryItems = Array<{ role: string; type: string; content: string; [k: string]: unknown }>;
export type RollingSummaryView = {
  conversations: Record<string, SummaryItems | null>;
  traces: Record<string, SummaryItems | null>;
  spans: Record<string, SummaryItems | null>;
  ensure: (thread: string) => void;
  generate: (thread: string) => void;
  generating: Set<string>;
};
export const RollingSummaryContext = createContext<RollingSummaryView>({
  conversations: {}, traces: {}, spans: {}, ensure: () => {}, generate: () => {}, generating: new Set(),
});

