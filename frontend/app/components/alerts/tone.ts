import type { StepMeta } from "@/app/lib/ruleFlow";

/** Step-type colour, resolved to literal Tailwind classes.
 *
 *  Tailwind's JIT only sees class names that appear as literals in a file, so a template string
 *  built from a variable (`text-${tone}`) compiles to nothing. One table, four classes per tone,
 *  every surface that mentions a step type reads from it: the node card, the picker, the inspector
 *  header, the output panel, the run log. Add a tone, get consistency free. */
export type Tone = StepMeta["tone"];

type ToneClasses = {
  /** Left border + source handle. */
  accent: string;
  /** Header wash behind the icon and label. */
  tint: string;
  /** Icon square. */
  chip: string;
  /** Text/icon colour. */
  fg: string;
  /** Selection ring on the node card. */
  ring: string;
};

export const TONE: Record<Tone, ToneClasses> = {
  signal: {
    accent: "border-l-signal",
    tint: "bg-signal/[0.07]",
    chip: "bg-signal/15 text-signal",
    fg: "text-signal",
    ring: "ring-signal/25",
  },
  info: {
    accent: "border-l-info",
    tint: "bg-info/[0.07]",
    chip: "bg-info/15 text-info",
    fg: "text-info",
    ring: "ring-info/25",
  },
  ok: {
    accent: "border-l-ok",
    tint: "bg-ok/[0.07]",
    chip: "bg-ok/15 text-ok",
    fg: "text-ok",
    ring: "ring-ok/25",
  },
  warn: {
    accent: "border-l-warn",
    tint: "bg-warn/[0.07]",
    chip: "bg-warn/15 text-warn",
    fg: "text-warn",
    ring: "ring-warn/25",
  },
  fail: {
    accent: "border-l-fail",
    tint: "bg-fail/[0.07]",
    chip: "bg-fail/15 text-fail",
    fg: "text-fail",
    ring: "ring-fail/25",
  },
  tool: {
    accent: "border-l-t_tool",
    tint: "bg-t_tool/[0.07]",
    chip: "bg-t_tool/15 text-t_tool",
    fg: "text-t_tool",
    ring: "ring-t_tool/25",
  },
};

export const FIELD =
  "w-full rounded-lg border border-line bg-ink-700 px-2.5 py-2 font-mono text-[12px] text-fg placeholder:text-fg-faint transition-colors hover:border-line-bright focus:border-signal/50 focus:outline-none";
export const LABEL = "font-mono text-[10px] uppercase tracking-wider text-fg-faint";
export const ROW_FIELD =
  "rounded-md border border-line bg-ink-700 px-2 py-1 font-mono text-[11px] text-fg focus:border-signal/50 focus:outline-none";
