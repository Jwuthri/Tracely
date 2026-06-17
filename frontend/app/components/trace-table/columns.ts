// Column definitions + static visual tokens for the trace table. No React, no I/O — these are the
// stable shape of the table (the dynamic metric columns get appended at runtime from `evaluators`).
// Extracted from TraceTable.tsx so the static layout is one short, readable file.
import type { EvaluatorDef } from "../../lib/evaluators";

// ── shape ─────────────────────────────────────────────────────────────────────
export type Group = "C" | "M" | "S";

// `evaluator` marks a dynamic metric column (one per evaluator row, keyed by score_name);
// `tint` is its full-column color wash (header + body) so adjacent metrics read as
// distinct columns instead of one wide band.
export type MetricTint = { th: string; td: string };

export type Col = {
  key: string;
  label: string;
  group: Group;
  width: number;
  evaluator?: EvaluatorDef;
  tint?: MetricTint;
};

// ── tints + badges ────────────────────────────────────────────────────────────
// Cycled per metric column, TurnWise-style. Literal class strings (Tailwind JIT needs to see
// them in source); header gets the stronger wash, body cells a subtle one.
export const METRIC_TINTS: MetricTint[] = [
  { th: "bg-emerald-500/15", td: "bg-emerald-500/[0.06]" },
  { th: "bg-rose-500/15", td: "bg-rose-500/[0.06]" },
  { th: "bg-sky-500/15", td: "bg-sky-500/[0.06]" },
  { th: "bg-violet-500/15", td: "bg-violet-500/[0.06]" },
  { th: "bg-amber-500/15", td: "bg-amber-500/[0.06]" },
  { th: "bg-teal-500/15", td: "bg-teal-500/[0.06]" },
  { th: "bg-fuchsia-500/15", td: "bg-fuchsia-500/[0.06]" },
  { th: "bg-indigo-500/15", td: "bg-indigo-500/[0.06]" },
];

export const LEVEL_BADGE: Record<Group, string> = {
  C: "bg-blue-500/20 text-blue-400",
  M: "bg-green-500/20 text-green-400",
  S: "bg-purple-500/20 text-purple-400",
};

export const ROW_BG: Record<number, string> = {
  0: "bg-slate-800/50 border-l-blue-500",
  1: "bg-slate-800/30 border-l-green-500",
  2: "bg-slate-800/10 border-l-purple-500",
};

// ── static layout tokens ──────────────────────────────────────────────────────
export const CTRL = { width: 40, minWidth: 20 };
export const HEAD_TH =
  "text-left text-xs font-medium text-slate-400 uppercase tracking-wider px-2 sm:px-3 py-3 first:pl-2 sm:first:pl-4 whitespace-nowrap";

// Persisted view preferences (hidden columns). The full-width toggle lives in ../../lib/useWide so
// the Timeline + Evaluations tabs share one Enlarge/Concise control with the table.
export const PREFS_KEY = "tracely.traceTable.prefs";

// Canonical span types — mirrors backend/tracely/otel/mapping.py:_KNOWN_TYPES (+ SUBAGENT from the
// TypeChip map). The Types filter menu always lists these so the preference is truly global —
// otherwise the menu changes per trace and users can't pre-hide CHAIN/THINKING on traces that
// haven't been opened yet. Ordered most-useful-to-filter first; unknown types found in data are
// appended.
export const KNOWN_SPAN_TYPES = [
  "AGENT",
  "SUBAGENT",
  "GENERATION",
  "TOOL",
  "THINKING",
  "CHAIN",
  "RETRIEVER",
  "EMBEDDING",
  "GUARDRAIL",
  "EVALUATOR",
  "EVENT",
  "SPAN",
] as const;

// ── default column set ────────────────────────────────────────────────────────
// The static C/M/S columns; the runtime evaluator columns get appended in TraceTable's `allColumns`
// memo. Order matters — it's the left-to-right order in the rendered table.
export const COLUMNS: Col[] = [
  { key: "conversation", label: "Conversation", group: "C", width: 260 },
  { key: "ctime",        label: "Datetime",     group: "C", width: 160 },
  { key: "cdur",         label: "Duration",     group: "C", width: 96 },
  { key: "crsummary", label: "Rolling summary", group: "C", width: 280 },
  { key: "cmeta", label: "Metadata", group: "C", width: 200 },
  { key: "cusage", label: "Usage", group: "C", width: 180 },
  { key: "role", label: "Role", group: "M", width: 110 },
  { key: "mindex", label: "#", group: "M", width: 56 },
  { key: "mtime", label: "Datetime", group: "M", width: 160 },
  { key: "mdur",  label: "Duration", group: "M", width: 96 },
  { key: "content", label: "Content", group: "M", width: 420 },
  { key: "mrsummary", label: "Rolling summary", group: "M", width: 240 },
  { key: "musage", label: "Usage", group: "M", width: 180 },
  { key: "sindex", label: "#", group: "S", width: 56 },
  { key: "type", label: "Type", group: "S", width: 120 },
  { key: "stime", label: "Datetime", group: "S", width: 160 },
  { key: "sdur", label: "Duration", group: "S", width: 96 },
  { key: "agent", label: "Agent", group: "S", width: 120 },
  { key: "model", label: "Model", group: "S", width: 120 },
  { key: "name", label: "Name", group: "S", width: 170 },
  { key: "input", label: "Input", group: "S", width: 240 },
  { key: "output", label: "Output", group: "S", width: 240 },
  { key: "srsummary", label: "Rolling summary", group: "S", width: 240 },
  { key: "susage", label: "Usage", group: "S", width: 180 },
];
