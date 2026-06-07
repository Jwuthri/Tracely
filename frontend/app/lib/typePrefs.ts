"use client";

import { useCallback, useEffect, useState } from "react";

// Single source of truth for the "hidden span types" preference — shared between the trace table
// and the timeline so the same filter applies in both views and persists across reloads. Same
// storage key as the table's column-visibility prefs; this module only touches the hiddenTypes
// field via read-modify-write, so it composes safely with TraceTable's own prefs writer.
const PREFS_KEY = "tracely.traceTable.prefs";
const EVENT = "tracely:prefs";

function readHidden(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (!raw) return new Set();
    const p = JSON.parse(raw) as { hiddenTypes?: unknown };
    return new Set(Array.isArray(p.hiddenTypes) ? (p.hiddenTypes as string[]) : []);
  } catch {
    return new Set();
  }
}

function writeHidden(next: Set<string>) {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    const cur = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    localStorage.setItem(PREFS_KEY, JSON.stringify({ ...cur, hiddenTypes: [...next] }));
    window.dispatchEvent(new Event(EVENT));
  } catch {
    /* ignore */
  }
}

export function useHiddenTypes(): {
  hidden: Set<string>;
  toggle: (type: string) => void;
  reset: () => void;
} {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  useEffect(() => {
    setHidden(readHidden());
    const sync = () => setHidden(readHidden());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync); // cross-tab sync
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const toggle = useCallback((type: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      writeHidden(next);
      return next;
    });
  }, []);
  const reset = useCallback(() => {
    setHidden(new Set());
    writeHidden(new Set());
  }, []);
  return { hidden, toggle, reset };
}
