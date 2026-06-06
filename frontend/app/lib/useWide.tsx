"use client";

import { useEffect, useState, type CSSProperties } from "react";

// Full-width breakout, derived from the app shell (244px sidebar, main max-w 1240 + px-8, 24px
// gutter). Shared by the trace Table / Timeline / Evaluations so "Enlarge" widens every tab alike.
export const WIDE_STYLE: CSSProperties = {
  marginLeft: "calc(734px - 50vw)",
  width: "calc(100vw - 292px)",
  maxWidth: "none",
};

const KEY = "tracely.traceView.wide";

// One persisted preference for the whole trace view (concise vs full-width). Re-read on mount, so
// the choice carries across tabs and pages.
export function useWide(): [boolean, (v: boolean) => void] {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    try {
      setWide(localStorage.getItem(KEY) === "1");
    } catch {
      /* ignore */
    }
  }, []);
  const update = (v: boolean) => {
    setWide(v);
    try {
      localStorage.setItem(KEY, v ? "1" : "0");
    } catch {
      /* ignore */
    }
  };
  return [wide, update];
}

const ICON = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className: "h-3.5 w-3.5",
};

// Enlarge / Concise toggle button — matches the trace table's toolbar control.
export function WideToggle({ wide, onToggle }: { wide: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
      title={wide ? "Fit to content" : "Expand to full width"}
    >
      {wide ? (
        <svg {...ICON}>
          <path d="M4 14h6v6" />
          <path d="M20 10h-6V4" />
          <path d="M14 10l7-7" />
          <path d="M3 21l7-7" />
        </svg>
      ) : (
        <svg {...ICON}>
          <path d="M15 3h6v6" />
          <path d="M9 21H3v-6" />
          <path d="M21 3l-7 7" />
          <path d="M3 21l7-7" />
        </svg>
      )}
      <span>{wide ? "Concise" : "Enlarge"}</span>
    </button>
  );
}
