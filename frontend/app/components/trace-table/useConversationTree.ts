"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { ConvNode, FullTurn, SpanOut, ThreadTurn } from "../../lib/api";

/* The Conversation → Turn → Step tree behind the table: what is open, what has been fetched,
   and what a click on a chevron sets in motion.

   Two shapes of data arrive here. Detail mode seeds the whole tree up front (`conv.turnsData`)
   and everything starts expanded; list mode gets conversation summaries only and fetches turns
   on the first expand, steps on the one after that. Both end up in the same caches, where
   `undefined` means "never asked", `"loading"` means "asked, still waiting", and an array is
   the answer — including `[]` for a failed fetch, so a broken row settles as empty instead of
   retrying forever. */

export type Cache<T> = Record<string, T | "loading" | undefined>;

export type ConversationTree = {
  turns: Cache<FullTurn[]>;
  spans: Cache<SpanOut[]>;
  openConv: Set<string>;
  openTurn: Set<string>;
  toggleConv: (thread: string) => void;
  toggleTurn: (trace: string) => void;
  /** Expand everything to the step level, or collapse it all when it already is. */
  toggleAll: () => void;
  allOpen: boolean;
};

export function useConversationTree(conversations: ConvNode[]): ConversationTree {
  const seed = useMemo(() => {
    const turns: Cache<FullTurn[]> = {};
    const spans: Cache<SpanOut[]> = {};
    const openC = new Set<string>();
    const openT = new Set<string>();
    for (const c of conversations) {
      if (c.turnsData) {
        turns[c.thread] = c.turnsData;
        openC.add(c.thread);
        for (const t of c.turnsData) {
          spans[t.trace_id] = t.spans;
          openT.add(t.trace_id);
        }
      }
    }
    return { turns, spans, openC, openT };
  }, [conversations]);

  const [turns, setTurns] = useState<Cache<FullTurn[]>>(seed.turns);
  const [spans, setSpans] = useState<Cache<SpanOut[]>>(seed.spans);
  const [openConv, setOpenConv] = useState<Set<string>>(seed.openC);
  const [openTurn, setOpenTurn] = useState<Set<string>>(seed.openT);

  // Reads of the caches happen inside callbacks that must not re-create on every fetch (they are
  // handed to memoized rows), and "is this already in flight?" has to be answered against the
  // CURRENT value, not the one closed over when the callback was built.
  const turnsRef = useRef(turns);
  turnsRef.current = turns;
  const spansRef = useRef(spans);
  spansRef.current = spans;

  const loadTurns = useCallback(async (thread: string): Promise<FullTurn[]> => {
    setTurns((p) => ({ ...p, [thread]: "loading" }));
    try {
      const r = await fetch(`/api/session?thread=${encodeURIComponent(thread)}`);
      const j = await r.json();
      const ft: FullTurn[] = (j.turns ?? []).map((t: ThreadTurn) => ({ ...t, spans: [] }));
      setTurns((p) => ({ ...p, [thread]: ft }));
      return ft;
    } catch {
      setTurns((p) => ({ ...p, [thread]: [] }));
      return [];
    }
  }, []);

  const loadSpans = useCallback(async (trace: string): Promise<SpanOut[]> => {
    setSpans((p) => ({ ...p, [trace]: "loading" }));
    try {
      const r = await fetch(`/api/trace?id=${encodeURIComponent(trace)}`);
      const j = await r.json();
      const sp: SpanOut[] = j.spans ?? [];
      setSpans((p) => ({ ...p, [trace]: sp }));
      return sp;
    } catch {
      setSpans((p) => ({ ...p, [trace]: [] }));
      return [];
    }
  }, []);

  // The fetch is decided BEFORE the set-state, never inside the updater: React may run an updater
  // more than once (StrictMode does exactly that in dev), and a fetch in there fires twice.
  const toggleConv = useCallback(
    (thread: string) => {
      const opening = !openConv.has(thread);
      if (opening && turnsRef.current[thread] === undefined) void loadTurns(thread);
      setOpenConv((prev) => {
        const next = new Set(prev);
        if (!next.delete(thread)) next.add(thread);
        return next;
      });
    },
    [openConv, loadTurns],
  );

  const toggleTurn = useCallback(
    (trace: string) => {
      const opening = !openTurn.has(trace);
      if (opening && spansRef.current[trace] === undefined) void loadSpans(trace);
      setOpenTurn((prev) => {
        const next = new Set(prev);
        if (!next.delete(trace)) next.add(trace);
        return next;
      });
    },
    [openTurn, loadSpans],
  );

  const allOpen = conversations.length > 0 && conversations.every((c) => openConv.has(c.thread));

  // Expand all: open every conversation, load + open their turns, then load every turn's steps.
  // One async cascade, because each level's ids only exist once the level above has landed.
  const expandAll = useCallback(async () => {
    setOpenConv(new Set(conversations.map((c) => c.thread)));
    const perConv = await Promise.all(
      conversations.map((c) => {
        const existing = turnsRef.current[c.thread];
        return Array.isArray(existing) ? Promise.resolve(existing) : loadTurns(c.thread);
      }),
    );
    const traceIds = perConv.flat().map((t) => t.trace_id);
    setOpenTurn(new Set(traceIds));
    await Promise.all(
      traceIds.map((id) => (spansRef.current[id] === undefined ? loadSpans(id) : Promise.resolve([]))),
    );
  }, [conversations, loadTurns, loadSpans]);

  const toggleAll = useCallback(() => {
    if (allOpen) {
      setOpenConv(new Set());
      setOpenTurn(new Set());
      return;
    }
    void expandAll();
  }, [allOpen, expandAll]);

  return { turns, spans, openConv, openTurn, toggleConv, toggleTurn, toggleAll, allOpen };
}
