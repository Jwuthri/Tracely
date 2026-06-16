"use client";

import clsx from "clsx";
import { createContext, memo, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode, type SVGProps } from "react";
import { useRouter } from "next/navigation";
import type { ConvNode, EvalScore, FullTurn, SpanOut, ThreadTurn } from "../lib/api";
import { convUsage, fmtUsd, spanUsage, turnUsage, usageSummary } from "../lib/usage";
import {
  deleteEvaluator,
  levelGroup,
  listEvaluators,
  getEvaluatorCost,
  streamEvaluationRun,
  LEVEL_LABEL,
  type EvaluatorDef,
  type EvaluatorCost,
  type RunScope,
} from "../lib/evaluators";
import { mergeMeta } from "../lib/meta";
import { useHiddenTypes } from "../lib/typePrefs";
import { useWide, WideToggle, WIDE_STYLE } from "../lib/useWide";
import { AddColumnModal } from "./AddColumnModal";
import { ExpandableText, FloatingPanel, HighlightedJson, IconBox, JsonPill, Pill, Plain, prettyJson } from "./JsonView";
import {
  agentLabel,
  asRoleMessage,
  assistantText,
  type ChatMsg,
  deriveTitle,
  durationMs,
  firstText,
  fmtDateTime,
  fmtMs,
  fmtPanelOutput,
  fmtScoreValue,
  fmtTokens,
  jsonResultLabel,
  lastTurnMessage,
  messageList,
  modelColor,
  msgRole,
  nearestAgentLabel,
  parseMaybe,
  scoreKey,
  sortSpans,
  toMsg,
} from "./trace-table/format";
import { normalizeType, TypeChip } from "./ui";

// ── A TurnWise-style hierarchical spreadsheet over Tracely's real tree ─────────
//   Conversation (thread)  →  Message (turn, split user / assistant)  →  Step (span)
// A real <table> with C / M / S column groups, depth-coloured rows, inline JSON +
// usage pills (→ floating popover) and smart multimodal message content. Two modes:
//   • "list"   — conversation summaries; turns + spans lazy-load on expand.
//   • "detail" — full tree seeded (turnsData populated); everything pre-open.

// ── lucide-style icons ─────────────────────────────────────────────────────────
const svg = (p: SVGProps<SVGSVGElement>) => ({
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  ...p,
});
const ChevronR = (p: SVGProps<SVGSVGElement>) => <svg {...svg(p)}><path d="m9 18 6-6-6-6" /></svg>;
const Play = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z" /></svg>
);
const Bot = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}>
    <path d="M12 8V4H8" /><rect width="16" height="12" x="4" y="8" rx="2" />
    <path d="M2 14h2" /><path d="M20 14h2" /><path d="M15 13v2" /><path d="M9 13v2" />
  </svg>
);
const ChevronsUpDown = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="m7 15 5 5 5-5" /><path d="m7 9 5-5 5 5" /></svg>
);
const Eye = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}>
    <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);
const ImageIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><rect width="18" height="18" x="3" y="3" rx="2" ry="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" /></svg>
);
const FileIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
);
const FilterIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M22 3H2l8 9.46V19l4 2v-8.54z" /></svg>
);
const PlusIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M5 12h14" /><path d="M12 5v14" /></svg>
);
const DotsIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><circle cx="12" cy="12" r="1" /><circle cx="12" cy="5" r="1" /><circle cx="12" cy="19" r="1" /></svg>
);

// ── columns ───────────────────────────────────────────────────────────────────
type Group = "C" | "M" | "S";
// `evaluator` marks a dynamic metric column (one per evaluator row, keyed by score_name);
// `tint` is its full-column color wash (header + body) so adjacent metrics read as
// distinct columns instead of one wide band.
type MetricTint = { th: string; td: string };
type Col = {
  key: string;
  label: string;
  group: Group;
  width: number;
  evaluator?: EvaluatorDef;
  tint?: MetricTint;
};

// Cycled per metric column, TurnWise-style. Literal class strings (Tailwind JIT needs to see
// them in source); header gets the stronger wash, body cells a subtle one.
const METRIC_TINTS: MetricTint[] = [
  { th: "bg-emerald-500/15", td: "bg-emerald-500/[0.06]" },
  { th: "bg-rose-500/15", td: "bg-rose-500/[0.06]" },
  { th: "bg-sky-500/15", td: "bg-sky-500/[0.06]" },
  { th: "bg-violet-500/15", td: "bg-violet-500/[0.06]" },
  { th: "bg-amber-500/15", td: "bg-amber-500/[0.06]" },
  { th: "bg-teal-500/15", td: "bg-teal-500/[0.06]" },
  { th: "bg-fuchsia-500/15", td: "bg-fuchsia-500/[0.06]" },
  { th: "bg-indigo-500/15", td: "bg-indigo-500/[0.06]" },
];

const COLUMNS: Col[] = [
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

const LEVEL_BADGE: Record<Group, string> = {
  C: "bg-blue-500/20 text-blue-400",
  M: "bg-green-500/20 text-green-400",
  S: "bg-purple-500/20 text-purple-400",
};
const ROW_BG: Record<number, string> = {
  0: "bg-slate-800/50 border-l-blue-500",
  1: "bg-slate-800/30 border-l-green-500",
  2: "bg-slate-800/10 border-l-purple-500",
};

const CTRL = { width: 40, minWidth: 20 };
const HEAD_TH =
  "text-left text-xs font-medium text-slate-400 uppercase tracking-wider px-2 sm:px-3 py-3 first:pl-2 sm:first:pl-4 whitespace-nowrap";

// Persisted view preferences (hidden columns). The full-width toggle lives in ../lib/useWide so the
// Timeline + Evaluations tabs share one Enlarge/Concise control with the table.
const PREFS_KEY = "tracely.traceTable.prefs";

// Canonical span types — mirrors backend/tracely/otel/mapping.py:_KNOWN_TYPES (+ SUBAGENT from the
// TypeChip map). The Types filter menu always lists these so the preference is truly global —
// otherwise the menu changes per trace and users can't pre-hide CHAIN/THINKING on traces that
// haven't been opened yet. Ordered most-useful-to-filter first; unknown types found in data are
// appended.
const KNOWN_SPAN_TYPES = [
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

// ── format helpers ──────────────────────────────────────────────────────────────
// usage / cost derivation (spanUsage / turnUsage / convUsage / usageSummary / fmtUsd) lives in
// ../lib/usage so the detail-page headers can reuse the exact same logic.

// ── JSON detail popover (portal — escapes the table's overflow) ──────────────────
// Shared syntax highlighter (also used by the timeline span panel + attributes list).
const HJson = HighlightedJson;

const ChatGlyph = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
);

// Formatted Tokens / Cost breakdown for the usage popover (nicer than raw JSON).
function UsageBody({ usage }: { usage: Record<string, number> }) {
  const tokenRows = ([["Input", "input_tokens"], ["Output", "output_tokens"], ["Thinking", "thinking_tokens"], ["Total", "total_tokens"]] as Array<[string, string]>).filter(([, k]) => usage[k] != null);
  const costRows = ([["Input", "input_price"], ["Output", "output_price"], ["Total", "cost"]] as Array<[string, string]>).filter(([, k]) => usage[k] != null);
  const row = (label: string, k: string, fmt: (n: number) => string, cls: string) => (
    <div key={k} className={clsx("flex items-center justify-between gap-4", k === "total_tokens" || k === "cost" ? "mt-0.5 border-t border-slate-700/60 pt-1 font-medium" : "")}>
      <span className="text-slate-400">{label}</span>
      <span className={clsx("font-mono tabular-nums", cls)}>{fmt(usage[k])}</span>
    </div>
  );
  return (
    <div className="space-y-3 p-3 text-[12px]">
      {tokenRows.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Tokens</div>
          {tokenRows.map(([l, k]) => row(l, k, (n) => n.toLocaleString("en-US"), "text-slate-200"))}
        </div>
      )}
      {costRows.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Cost</div>
          {costRows.map(([l, k]) => row(l, k, fmtUsd, "text-amber-300"))}
        </div>
      )}
    </div>
  );
}

function UsageCell({ usage }: { usage: Record<string, number> }) {
  if (Object.keys(usage).length === 0) return <span className="text-slate-500">—</span>;
  const icon = <IconBox accent="amber"><span className="text-[10px] font-bold">Σ</span></IconBox>;
  return (
    <Pill
      iconBox={icon}
      summary={<span className="text-slate-300/90">{usageSummary(usage)}</span>}
      panel={(a, c) => (
        <FloatingPanel anchor={a} onClose={c} icon={icon} title="usage" subtitle={usageSummary(usage)} copyText={JSON.stringify(usage, null, 2)}>
          <UsageBody usage={usage} />
        </FloatingPanel>
      )}
    />
  );
}

// ── unified content rendering (chat transcripts, multimodal parts, data) ─────────
type Part =
  | { kind: "text"; text: string }
  | { kind: "image"; url?: string; label: string }
  | { kind: "file"; url?: string; label: string }
  | { kind: "json"; data: unknown };

function isChatMsg(x: unknown): boolean {
  return !!x && typeof x === "object" && "role" in (x as object);
}
function isContentBlock(x: unknown): boolean {
  if (typeof x === "string") return true;
  if (!x || typeof x !== "object" || "role" in (x as object)) return false;
  const o = x as Record<string, unknown>;
  return "type" in o || "text" in o || "image_url" in o || "source" in o;
}
function classifyBlock(b: unknown): Part {
  if (typeof b === "string") return { kind: "text", text: b };
  if (b && typeof b === "object") {
    const o = b as Record<string, unknown>;
    const type = String(o.type ?? "").toLowerCase();
    const src = (o.source ?? {}) as Record<string, unknown>;
    if (type.includes("image") || o.image_url || o.image || src.media_type || (src.type === "base64")) {
      const iu = o.image_url as Record<string, unknown> | string | undefined;
      const url = (typeof iu === "object" ? (iu?.url as string) : iu) ?? (o.url as string) ?? (src.url as string);
      const media = (src.media_type as string) ?? (o.mime_type as string) ?? "image";
      return { kind: "image", url: typeof url === "string" ? url : undefined, label: media };
    }
    if (type.includes("file") || type.includes("document") || o.file || o.filename || o.file_id) {
      const file = (o.file ?? {}) as Record<string, unknown>;
      const name = (o.filename as string) ?? (file.filename as string) ?? (o.name as string) ?? (o.file_id as string) ?? "file";
      const furl = (o.url as string) ?? (o.file_url as string) ?? (file.url as string) ?? (src.url as string);
      return { kind: "file", url: typeof furl === "string" ? furl : undefined, label: String(name) };
    }
    if (type.includes("text") || typeof o.text === "string") return { kind: "text", text: String(o.text ?? o.content ?? "") };
  }
  return { kind: "json", data: b };
}

const ExternalLink = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></svg>
);

// A compact attachment chip. Deliberately lightweight — it shows an icon + name and NEVER loads
// the full image inline (a table can hold many of these). When the block carries a url/path the
// chip is a link that opens the image/document in a new tab.
function Attachment({ part }: { part: Exclude<Part, { kind: "text" }> }) {
  if (part.kind === "json") return <JsonPill raw={JSON.stringify(part.data)} />;
  const isImg = part.kind === "image";
  const url = part.url;
  const icon = isImg ? (
    <ImageIcon className="h-3.5 w-3.5 shrink-0 text-fuchsia-400" />
  ) : (
    <FileIcon className="h-3.5 w-3.5 shrink-0 text-sky-400" />
  );
  const base =
    "inline-flex max-w-[200px] items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800/60 px-2 py-1 text-[11px] text-slate-300";
  if (url && /^(https?:|data:)/.test(url)) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        title={`Open ${part.label}`}
        className={clsx(base, "transition-colors hover:border-slate-500 hover:bg-slate-700/70 hover:text-white")}
      >
        {icon}
        <span className="truncate">{part.label}</span>
        <ExternalLink className="h-3 w-3 shrink-0 text-slate-500" />
      </a>
    );
  }
  return (
    <span className={base}>
      {icon}
      <span className="truncate">{part.label}</span>
    </span>
  );
}

// One message's content value: plain text, multimodal parts (text + image/file chips), or data.
function ContentParts({ value }: { value: unknown }) {
  if (value == null || value === "") return <span className="text-slate-500">—</span>;
  if (typeof value === "string") return <ExpandableText text={value} />;
  if (Array.isArray(value)) {
    const parts = value.map(classifyBlock);
    const text = parts
      .filter((p): p is Extract<Part, { kind: "text" }> => p.kind === "text")
      .map((p) => p.text)
      .join("\n")
      .trim();
    const media = parts.filter((p): p is Exclude<Part, { kind: "text" }> => p.kind !== "text");
    return (
      <div className="space-y-1.5">
        {text && <ExpandableText text={text} />}
        {media.length > 0 && <div className="flex flex-wrap gap-1.5">{media.map((m, i) => <Attachment key={i} part={m} />)}</div>}
      </div>
    );
  }
  return <JsonPill raw={JSON.stringify(value)} />;
}

const ROLE_CHIP: Record<string, string> = {
  user: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  assistant: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  system: "bg-slate-600/25 text-slate-300 border-slate-600/40",
  tool: "bg-orange-500/10 text-orange-300 border-orange-500/30",
  thinking: "bg-violet-500/10 text-violet-300 border-violet-500/30",
};
function RoleTag({ role }: { role?: string }) {
  const r = (role || "msg").toLowerCase();
  return (
    <span className={clsx("inline-block shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider", ROLE_CHIP[r] ?? "bg-slate-600/25 text-slate-300 border-slate-600/40")}>
      {r}
    </span>
  );
}
// Full (un-clamped) content for the conversation popover: text wraps, attachments as chips, data as JSON.
function ContentBody({ value }: { value: unknown }) {
  if (value == null || value === "") return <span className="text-slate-500">—</span>;
  if (typeof value === "string") {
    const s = value.trim();
    if (/^https?:\/\/\S+$/.test(s)) {
      return (
        <a href={s} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="break-all text-[12px] leading-relaxed text-cyan-400 underline decoration-cyan-400/40 underline-offset-2 hover:decoration-cyan-400">
          {s}
        </a>
      );
    }
    // Tool messages (and the occasional structured assistant return) often arrive as a JSON-encoded
    // string. Render them with the same pretty-printed, syntax-highlighted treatment we use for
    // tool-call arguments so the popover doesn't show a wall of escaped braces.
    if (s.startsWith("{") || s.startsWith("[")) {
      const pretty = prettyJson(s);
      if (pretty && pretty !== s) {
        return (
          <pre className="whitespace-pre-wrap break-words rounded-md border border-slate-700/60 bg-slate-900/50 p-2 font-mono text-[11px] leading-relaxed text-slate-300">
            <HJson text={pretty} />
          </pre>
        );
      }
    }
    return <div className="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-slate-300">{value}</div>;
  }
  if (Array.isArray(value)) {
    const parts = value.map(classifyBlock);
    const text = parts
      .filter((p): p is Extract<Part, { kind: "text" }> => p.kind === "text")
      .map((p) => p.text)
      .join("\n")
      .trim();
    const media = parts.filter((p): p is Exclude<Part, { kind: "text" }> => p.kind !== "text");
    return (
      <div className="space-y-2">
        {text && <div className="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-slate-300">{text}</div>}
        {media.length > 0 && <div className="flex flex-wrap gap-1.5">{media.map((m, i) => <Attachment key={i} part={m} />)}</div>}
      </div>
    );
  }
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-slate-300">
      <HJson text={JSON.stringify(value, null, 2)} />
    </pre>
  );
}


// A model's tool/function calls (function calling) — name + parsed arguments.
function ToolCalls({ calls }: { calls: unknown[] }) {
  return (
    <div className="mt-2 space-y-1.5">
      <div className="text-[9.5px] uppercase tracking-wider text-slate-500">Tool calls</div>
      {calls.map((raw, i) => {
        const c = (raw ?? {}) as Record<string, unknown>;
        const fn = (c.function ?? c) as Record<string, unknown>;
        const name = String(fn.name ?? c.name ?? "tool");
        let args: unknown = fn.arguments ?? c.arguments ?? c.args;
        if (typeof args === "string") {
          try { args = JSON.parse(args); } catch { /* keep string */ }
        }
        return (
          <div key={i} className="rounded-md border border-slate-700/60 bg-slate-900/50 p-2">
            <div className="flex items-center gap-1.5 font-mono text-[11.5px] font-medium text-violet-300">
              <span className="text-[10px]">⛭</span>
              {name}
            </div>
            {args != null && args !== "" && (
              <pre className="mt-1 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-slate-300">
                <HJson text={typeof args === "string" ? args : JSON.stringify(args, null, 2)} />
              </pre>
            )}
          </div>
        );
      })}
    </div>
  );
}

// One message card: role chip (+ finish_reason), content rendered by type, then any tool calls.
function MessageCard({ m }: { m: ChatMsg }) {
  const calls = Array.isArray(m.tool_calls) ? m.tool_calls : [];
  const finish = typeof m.finish_reason === "string" ? m.finish_reason : null;
  const hasContent = m.content != null && m.content !== "";
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 p-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <RoleTag role={m.role} />
        {finish && (
          <span className="rounded bg-slate-700/50 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-slate-400">{finish}</span>
        )}
      </div>
      {hasContent && <ContentBody value={m.content} />}
      {calls.length > 0 && <ToolCalls calls={calls} />}
      {!hasContent && calls.length === 0 && <span className="text-slate-500">—</span>}
    </div>
  );
}

// The conversation popover body: one card per message.
function ChatBody({ msgs }: { msgs: ChatMsg[] }) {
  return <div className="space-y-2 p-3">{msgs.map((m, i) => <MessageCard key={i} m={m} />)}</div>;
}

// A chat transcript shown as a compact pill (role + last message preview) → conversation popover.
function ChatPill({ msgs }: { msgs: ChatMsg[] }) {
  const n = msgs.length;
  // Prefer the last *conversational* turn for the collapsed preview: a prompt history that ends in a
  // tool result should still headline with the user/assistant turn, not a raw tool-result dump.
  const last =
    [...msgs].reverse().find((m) => /^(user|assistant|human|ai)$/i.test(String(m.role ?? ""))) ?? msgs[n - 1] ?? {};
  const lastText =
    typeof last.content === "string"
      ? last.content
      : Array.isArray(last.content)
        ? (last.content.map(classifyBlock).find((p) => p.kind === "text") as Extract<Part, { kind: "text" }> | undefined)?.text ?? ""
        : "";
  // No text (e.g. a tool-calling completion)? preview the called tool names instead.
  const toolNames = Array.isArray(last.tool_calls)
    ? (last.tool_calls as Record<string, unknown>[])
        .map((c) => ((c?.function as Record<string, unknown>)?.name ?? c?.name) as string | undefined)
        .filter(Boolean)
    : [];
  const base = lastText || (toolNames.length ? `→ ${toolNames.join(", ")}` : "");
  // Keep the collapsed baseline short — it's a teaser; the full content lives in the popover.
  const preview = base.length > 42 ? `${base.slice(0, 42).trimEnd()}…` : base;
  const icon = (
    <IconBox accent="violet">
      <ChatGlyph className="h-3 w-3" />
    </IconBox>
  );
  return (
    <Pill
      iconBox={icon}
      summary={
        <span className="flex items-center gap-1.5 truncate">
          <span className="uppercase text-slate-400">{(last.role || "msg").toString()}</span>
          {preview && <span className="truncate text-slate-500">{preview}</span>}
        </span>
      }
      badge={<span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-slate-400">{n}</span>}
      panel={(a, c) => (
        <FloatingPanel anchor={a} onClose={c} icon={icon} title="conversation" subtitle={`${n} message${n === 1 ? "" : "s"}`} copyText={JSON.stringify(msgs, null, 2)}>
          <ChatBody msgs={msgs} />
        </FloatingPanel>
      )}
    />
  );
}

// A small "lines of text" glyph for the plain-text pill.
const TextGlyph = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M4 6h16M4 12h16M4 18h10" /></svg>
);

// Plain step content that's neither chat nor structured JSON — e.g. an @observe THINKING step whose
// I/O is a bare string or a {question}/{prompt} dict. Rendered as a compact pill (matching the chat
// & JSON pills) that opens the full text in a floating panel, so the row stays single-line and reads
// consistently instead of as bare, wrapping text.
function TextPill({ text }: { text: string }) {
  const preview = text.length > 48 ? `${text.slice(0, 48).trimEnd()}…` : text;
  const icon = (
    <IconBox accent="violet">
      <TextGlyph className="h-3 w-3" />
    </IconBox>
  );
  return (
    <Pill
      iconBox={icon}
      summary={<span className="truncate text-slate-300/90">{preview}</span>}
      panel={(a, c) => (
        <FloatingPanel anchor={a} onClose={c} icon={icon} title="text" subtitle={`${text.length} chars`} copyText={text}>
          <div className="max-w-full whitespace-pre-wrap break-words p-3 text-[12px] leading-relaxed text-slate-300">{text}</div>
        </FloatingPanel>
      )}
    />
  );
}

// The universal renderer used for every message/step input & output, so the same
// content reads the same way at any level (and attachments/multi-part work everywhere).
function MessageContent({ raw }: { raw: string | null }) {
  if (raw == null || raw === "") return <span className="text-slate-500">—</span>;
  const t = raw.trim();
  let parsed: unknown = null;
  if (t.startsWith("[") || t.startsWith("{")) {
    try {
      parsed = JSON.parse(t);
    } catch {
      /* plain text */
    }
  }
  if (parsed === null) return raw.length > 56 ? <TextPill text={raw} /> : <Plain text={raw} />;
  // chat transcript -> compact pill that opens a clean conversation view
  if (Array.isArray(parsed) && parsed.length > 0 && parsed.every(isChatMsg)) {
    return <ChatPill msgs={parsed as Array<{ role?: string; content?: unknown }>} />;
  }
  // a single chat / completion message object {role, …} -> compact message pill (click to expand).
  // Assistant completions are included: content renders by type and tool_calls / finish_reason are
  // surfaced. Raw structured data with no `role` (tool args/results, output-schema) stays JSON below.
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed) && "role" in (parsed as object)) {
    return <ChatPill msgs={[parsed as ChatMsg]} />;
  }
  // a {messages:[…]} wrapper (a LangGraph state object / an OpenAI-style request) -> conversation
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const inner = (parsed as Record<string, unknown>).messages;
    if (Array.isArray(inner) && inner.length > 0 && inner.every(isChatMsg)) {
      return <ChatPill msgs={inner as ChatMsg[]} />;
    }
  }
  // one message's multimodal parts (no roles) -> text + image/file chips
  if (Array.isArray(parsed) && parsed.length > 0 && parsed.every(isContentBlock)) {
    return <ContentParts value={parsed} />;
  }
  if (parsed && typeof parsed === "object" && Array.isArray((parsed as Record<string, unknown>).content)) {
    return <ContentParts value={(parsed as Record<string, unknown>).content} />;
  }
  // @observe captures fn args as {kwarg_name: value}. Only unwrap when the key is unambiguously a
  // prompt (so {question:"…"} reads as the question text). Tool args like {order_id:"ORD-4471"} or
  // {sku:"…"} stay as a JsonPill below — they're structured data the user wants to see as objects.
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const o = parsed as Record<string, unknown>;
    const promptish = ["prompt", "input", "question", "query", "user_input", "msg", "message", "text"];
    const k = Object.keys(o).find((x) => promptish.includes(x) && typeof o[x] === "string");
    if (k) {
      const s = o[k] as string;
      return s.length > 56 ? <TextPill text={s} /> : <Plain text={s} />;
    }
  }
  // structured data (tool args/results, output schema) -> JSON pill
  if (typeof parsed === "object") return <JsonPill raw={t} />;
  const s = String(parsed);
  return s.length > 56 ? <TextPill text={s} /> : <Plain text={s} />;
}

// ── message-level content (this side's last message only) ────────────────────────
// A turn's input/output is frequently the agent's whole state — the entire {messages:[…]} history
// (LangGraph) or a full chat array — not just this turn's one message. At the message (M) level we
// show only THIS side: the last user message on the user row, the last assistant message on the
// assistant row. (Steps keep their full raw I/O.)
function TurnMessage({ raw, role }: { raw: string | null; role: "user" | "assistant" }) {
  const msg = useMemo(() => lastTurnMessage(raw, role), [raw, role]);
  if (msg === undefined) return <MessageContent raw={asRoleMessage(role, raw)} />;
  if (msg === null) return <span className="text-slate-500">—</span>;
  const calls = Array.isArray(msg.tool_calls) ? msg.tool_calls : [];
  if (calls.length > 0) return <ChatPill msgs={[msg]} />; // assistant tool call(s) → keep them visible
  const c = msg.content;
  if (c == null || c === "" || (Array.isArray(c) && c.length === 0)) return <span className="text-slate-500">—</span>;
  // Render as a chat pill with the role badge — symmetric across user/assistant. Multimodal content
  // (URLs/base64 attachments) survives as the pill's content array and renders in the popover.
  return <ChatPill msgs={[msg]} />;
}

// ── badges ──────────────────────────────────────────────────────────────────────
function RoleBadge({ role }: { role: "user" | "assistant" }) {
  const cls = role === "user" ? "bg-sky-500/10 text-sky-400 border-sky-500/30" : "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
  const dot = role === "user" ? "bg-sky-400" : "bg-emerald-400";
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-semibold uppercase", cls)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", dot)} />
      {role}
    </span>
  );
}

function AgentBadge({ agent }: { agent: string }) {
  return (
    <span className="inline-flex max-w-full items-center truncate rounded border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] font-medium text-indigo-300" title={agent}>
      {agent}
    </span>
  );
}

function ModelBadge({ model }: { model: string }) {
  return (
    <span className={clsx("inline-flex max-w-full items-center truncate rounded border px-2 py-0.5 text-[11px] font-medium", modelColor(model))} title={model}>
      {model}
    </span>
  );
}

function ConvTitleCell({ conv }: { conv: ConvNode }) {
  const href = conv.turns > 1 ? `/sessions/${conv.thread}` : `/traces/${conv.last_trace_id}`;
  return (
    <a href={href} className="flex max-w-full items-center gap-2 text-sm font-medium text-slate-200 transition-colors hover:text-white" title={conv.thread}>
      <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", conv.failing ? "bg-rose-500" : "bg-emerald-500/70")} />
      <span className="truncate hover:underline">{deriveTitle(conv.first_input)}</span>
    </a>
  );
}

// ── evaluation columns (dynamic metric columns + live run state) ─────────────────
// Live results and run actions reach the deeply nested cells via context, so the
// row/cell component tree stays prop-free. Keys:
//   live score   →  `th:<thread>|<name>` | `tr:<trace>|<name>` | `span:<span>|<name>`
//   busy row     →  `th:<thread>` | `tr:<trace>`     busy column → score_name
type EvalView = {
  busyCols: Set<string>;
  busyRows: Set<string>;
  hasEvaluators: boolean;
  runThread: (thread: string) => void;
  runTrace: (trace: string) => void;
  runColumn: (ev: EvaluatorDef) => void;
  editColumn: (ev: EvaluatorDef) => void;
  removeColumn: (ev: EvaluatorDef) => void;
};
const EvalViewContext = createContext<EvalView>({
  busyCols: new Set(), busyRows: new Set(), hasEvaluators: false,
  runThread: () => {}, runTrace: () => {}, runColumn: () => {}, editColumn: () => {}, removeColumn: () => {},
});

// Live eval-run scores ride a SEPARATE, reference-stable store (not the EvalView context value) so a
// streamed result re-renders ONLY the cell whose score arrived — not the whole grid. Each cell
// subscribes to its own key via useSyncExternalStore; the store object's identity never changes, so
// providing it through context never triggers a re-render.
type LiveScoreStore = {
  get: (key: string) => EvalScore | undefined;
  set: (key: string, score: EvalScore) => void;
  subscribe: (key: string, cb: () => void) => () => void;
};
const LiveScoreContext = createContext<LiveScoreStore>({
  get: () => undefined, set: () => {}, subscribe: () => () => {},
});

function useLiveScoreStore(): LiveScoreStore {
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
function useLiveScore(key: string): EvalScore | undefined {
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
type SummaryItems = Array<{ role: string; type: string; content: string; [k: string]: unknown }>;
type RollingSummaryView = {
  conversations: Record<string, SummaryItems | null>;
  traces: Record<string, SummaryItems | null>;
  spans: Record<string, SummaryItems | null>;
  ensure: (thread: string) => void;
  generate: (thread: string) => void;
  generating: Set<string>;
};
const RollingSummaryContext = createContext<RollingSummaryView>({
  conversations: {}, traces: {}, spans: {}, ensure: () => {}, generate: () => {}, generating: new Set(),
});

function RollingSummaryCell({
  thread, kind, id,
}: { thread?: string; kind: "conversation" | "trace" | "span"; id?: string }) {
  const rs = useContext(RollingSummaryContext);
  useEffect(() => {
    if (thread) rs.ensure(thread);
  }, [thread, rs]);
  const val =
    kind === "conversation" ? (thread ? rs.conversations[thread] : undefined)
    : kind === "trace" ? (id ? rs.traces[id] : undefined)
    : id ? rs.spans[id] : undefined;
  if (val === undefined) return <span className="text-slate-600">…</span>; // not generated/loaded yet
  const hasContent = Array.isArray(val) && val.length > 0;
  if (!hasContent) {
    // Loaded but empty. At conversation level offer an inline generate (summaries are thread-scoped,
    // so turn/step cells can't generate on their own — they fill in once the thread is built).
    if (kind === "conversation" && thread) {
      const busy = rs.generating.has(thread);
      return (
        <button
          onClick={() => rs.generate(thread)}
          disabled={busy}
          className="font-mono text-[11px] text-slate-500 transition-colors hover:text-cyan-400 disabled:opacity-50"
        >
          {busy ? "generating…" : "generate"}
        </button>
      );
    }
    return <span className="text-slate-500">—</span>;
  }
  // The full accumulated summary object, as JSON — no truncation (JsonPill previews + expands).
  return <JsonPill raw={JSON.stringify(val)} />;
}

// Where a streamed score lands in `live` (mirrors the per-cell lookup keys).
function VerdictChip({ verdict }: { verdict: string }) {
  if (verdict !== "PASS" && verdict !== "FAIL") return null;
  const ok = verdict === "PASS";
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider",
        ok ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" : "border-rose-500/30 bg-rose-500/10 text-rose-400",
      )}
    >
      {verdict}
    </span>
  );
}

const EvalSpinner = () => (
  <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
    <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />
    evaluating
  </span>
);

// One metric result in a cell: verdict chip + value (or reason teaser), click → floating
// detail panel with the judge's full reasoning.
function EvalScorePill({ score, evaluator, busy }: { score: EvalScore; evaluator: EvaluatorDef; busy: boolean }) {
  const val = fmtScoreValue(score) || score.comment || "";
  const icon = (
    <IconBox accent={score.verdict === "FAIL" ? "fuchsia" : "cyan"}>
      <span className="text-[10px] font-bold">✓</span>
    </IconBox>
  );
  const rows: Array<[string, string]> = [];
  if (score.verdict) rows.push(["Verdict", score.verdict]);
  if (score.value != null) rows.push(["Value", String(score.value)]);
  if (score.string_value) {
    rows.push([
      score.data_type === "CATEGORICAL" ? "Category" : "Output",
      fmtPanelOutput(score.string_value),
    ]);
  }
  if (score.comment) rows.push(["Reason", score.comment]);
  return (
    // max-w-full + overflow-hidden: the pill can NEVER bleed into the neighboring column —
    // the teaser text is hard-trimmed to fit and the full reason lives in the click panel.
    <span className={clsx("inline-flex max-w-full items-center gap-1.5 overflow-hidden", busy && "opacity-50")}>
      {score.verdict ? <VerdictChip verdict={score.verdict} /> : null}
      {val ? (
        <Pill
          iconBox={icon}
          summary={<span className="text-slate-300/90">{val.length > 16 ? `${val.slice(0, 16).trimEnd()}…` : val}</span>}
          panel={(a, c) => (
            <FloatingPanel
              anchor={a}
              onClose={c}
              icon={icon}
              title={evaluator.name}
              subtitle={LEVEL_LABEL[score.evaluation_level] ?? score.evaluation_level.toLowerCase()}
              copyText={JSON.stringify(score, null, 2)}
            >
              <div className="space-y-2 p-3 text-[12px]">
                {evaluator.description && <p className="text-slate-500">{evaluator.description}</p>}
                {rows.map(([k, v]) => (
                  <div key={k} className="flex items-start justify-between gap-4">
                    <span className="shrink-0 text-slate-400">{k}</span>
                    <span
                      className={clsx(
                        "whitespace-pre-wrap break-words font-mono text-[11.5px]",
                        k === "Output" ? "text-left" : "text-right",
                        k === "Verdict" ? (v === "FAIL" ? "text-rose-400" : "text-emerald-400") : "text-slate-200",
                      )}
                    >
                      {v}
                    </span>
                  </div>
                ))}
              </div>
            </FloatingPanel>
          )}
        />
      ) : null}
    </span>
  );
}

// Span types a step-level evaluator grades — used to blank non-target step rows.
function evaluatorSpanTypes(ev: EvaluatorDef): string[] | null {
  if (ev.level === "SPAN") return (ev.config?.span_types as string[] | undefined) ?? ["TOOL", "GENERATION"];
  if (ev.level === "TOOL" || ev.level === "GENERATION" || ev.level === "CHAIN") return [ev.level];
  return null;
}

// The live-store key for this (evaluator, row) cell — "" when the cell isn't applicable, so the
// useLiveScore hook stays unconditional (hooks rule) without subscribing.
function liveKeyFor(evaluator: EvaluatorDef, ctx: RowCtx): string {
  if (levelGroup(evaluator.level) !== ctx.level) return "";
  const name = evaluator.score_name;
  if (ctx.level === "C") return `th:${ctx.conv.thread}|${name}`;
  if (ctx.level === "M") return ctx.role === "assistant" ? `tr:${ctx.turn.trace_id}|${name}` : "";
  const types = evaluatorSpanTypes(evaluator);
  if (types && !types.includes(ctx.span.type)) return "";
  return `span:${ctx.span.span_id}|${name}`;
}

function EvalColumnCell({ evaluator, ctx }: { evaluator: EvaluatorDef; ctx: RowCtx }) {
  const view = useContext(EvalViewContext);
  const live = useLiveScore(liveKeyFor(evaluator, ctx)); // subscribes to just this cell's score
  if (levelGroup(evaluator.level) !== ctx.level) return null;
  const name = evaluator.score_name;
  let score: EvalScore | undefined;
  let busy = view.busyCols.has(name);
  if (ctx.level === "C") {
    score = live ?? ctx.conv.scores?.find((s) => s.name === name && s.evaluation_level === "CONVERSATION");
    busy = busy || view.busyRows.has(`th:${ctx.conv.thread}`);
  } else if (ctx.level === "M") {
    if (ctx.role !== "assistant") return null; // run-level grades attach to the agent's reply
    score =
      live ?? ctx.turn.scores?.find((s) => s.name === name && !s.observation_id && s.evaluation_level !== "CONVERSATION");
    busy = busy || view.busyRows.has(`tr:${ctx.turn.trace_id}`) || view.busyRows.has(`th:${ctx.conv.thread}`);
  } else {
    const types = evaluatorSpanTypes(evaluator);
    if (types && !types.includes(ctx.span.type)) return null;
    score = live ?? ctx.turn.scores?.find((s) => s.name === name && s.observation_id === ctx.span.span_id);
    busy = busy || view.busyRows.has(`tr:${ctx.turn.trace_id}`);
  }
  if (!score) return busy ? <EvalSpinner /> : <span className="text-slate-500">—</span>;
  return <EvalScorePill score={score} evaluator={evaluator} busy={busy} />;
}

// ── row context + per-column dispatch ───────────────────────────────────────────
type RowCtx =
  | { level: "C"; conv: ConvNode; agentCount: number }
  | { level: "M"; role: "user" | "assistant"; conv: ConvNode; turn: FullTurn; index: number }
  | { level: "S"; span: SpanOut; index: number; turn: FullTurn };

function renderCell(col: Col, ctx: RowCtx): ReactNode {
  if (col.evaluator) return <EvalColumnCell evaluator={col.evaluator} ctx={ctx} />;
  switch (col.key) {
    // C group
    case "conversation":
      return ctx.level === "C" ? <ConvTitleCell conv={ctx.conv} /> : null;
    case "ctime":
      return ctx.level === "C"
        ? <span className="font-mono text-xs text-slate-400">{fmtDateTime(ctx.conv.first_ts)}</span>
        : null;
    case "cdur": {
      if (ctx.level !== "C") return null;
      const durMs = ctx.conv.first_ts
        ? new Date(ctx.conv.last_ts).getTime() - new Date(ctx.conv.first_ts).getTime()
        : null;
      return <span className="font-mono text-xs tabular-nums text-slate-400">{fmtMs(durMs)}</span>;
    }
    case "crsummary":
      return ctx.level === "C" ? <RollingSummaryCell thread={ctx.conv.thread} kind="conversation" /> : null;
    case "cmeta": {
      if (ctx.level !== "C") return null;
      // backend-aggregated thread metadata (available in the list); else union from loaded spans.
      const m =
        ctx.conv.metadata && Object.keys(ctx.conv.metadata).length
          ? ctx.conv.metadata
          : mergeMeta((ctx.conv.turnsData ?? []).flatMap((t) => t.spans));
      return Object.keys(m).length ? <JsonPill raw={JSON.stringify(m)} /> : <span className="text-slate-500">—</span>;
    }
    case "cusage":
      return ctx.level === "C" ? <UsageCell usage={convUsage(ctx.conv)} /> : null;
    // M group
    case "role": {
      if (ctx.level !== "M") return null;
      const failed = ctx.role === "assistant" && (ctx.turn.verdict === "FAIL" || ctx.turn.failing === 1);
      return (
        <span className="flex items-center gap-1.5">
          {failed && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500" title="failing" />}
          <RoleBadge role={ctx.role} />
        </span>
      );
    }
    case "mindex":
      return ctx.level === "M" ? <span className="font-mono text-xs tabular-nums text-slate-500">{ctx.index}</span> : null;
    case "mtime":
      return ctx.level === "M" ? <span className="font-mono text-xs text-slate-400">{fmtDateTime(ctx.turn.ts)}</span> : null;
    case "mdur":
      return ctx.level === "M" && ctx.role === "assistant"
        ? <span className="font-mono text-xs tabular-nums text-slate-400">{fmtMs(ctx.turn.latency_ms)}</span>
        : null;
    case "content":
      return ctx.level === "M" ? <TurnMessage raw={ctx.role === "user" ? ctx.turn.input : ctx.turn.output} role={ctx.role} /> : null;
    case "mrsummary":
      return ctx.level === "M" ? <RollingSummaryCell thread={ctx.conv.thread} kind="trace" id={ctx.turn.trace_id} /> : null;
    case "musage":
      return ctx.level === "M" && ctx.role === "assistant" ? <UsageCell usage={turnUsage(ctx.turn)} /> : null;
    // S group
    case "sindex":
      return ctx.level === "S" ? <span className="font-mono text-xs tabular-nums text-slate-500">{ctx.index}</span> : null;
    case "type":
      return ctx.level === "S" ? <TypeChip type={ctx.span.type} /> : null;
    case "stime":
      return ctx.level === "S" ? <span className="font-mono text-xs text-slate-400">{fmtDateTime(ctx.span.start_time)}</span> : null;
    case "sdur":
      return ctx.level === "S" ? <span className="font-mono text-xs tabular-nums text-slate-400">{fmtMs(durationMs(ctx.span))}</span> : null;
    case "agent": {
      if (ctx.level !== "S") return null;
      const label = nearestAgentLabel(ctx.span, ctx.turn.spans ?? []);
      return label ? <AgentBadge agent={label} /> : null;
    }
    case "model":
      return ctx.level === "S" && ctx.span.model_id ? <ModelBadge model={ctx.span.model_id} /> : null;
    case "name":
      if (ctx.level !== "S") return null;
      // For TOOL spans the framework `step_name` is usually the dispatching node ("tools" in
      // LangGraph), not the tool itself — prefer the actual tool name so the column shows
      // `get_order_status` instead of `tools`.
      return (
        <Plain
          text={ctx.span.type === "TOOL"
            ? (ctx.span.name || ctx.span.step_name || "")
            : (ctx.span.step_name || ctx.span.name || "")}
        />
      );
    case "input": {
      if (ctx.level !== "S") return null;
      // AGENT spans represent the run as a whole — wrap their I/O as a chat message so it reads as
      // a USER pill (matches the M-row layout). TOOL/GENERATION/CHAIN keep their raw shape: tools
      // carry structured args dicts, generations carry full message lists, chains carry framework
      // state.
      const raw = ctx.span.input;
      return ctx.span.type === "AGENT"
        ? <MessageContent raw={asRoleMessage("user", raw)} />
        : <MessageContent raw={raw} />;
    }
    case "output": {
      if (ctx.level !== "S") return null;
      // THINKING is its own Type — its reasoning text lives in the span's output, shown here.
      // AGENT outputs render as an ASSISTANT pill, again matching the M-row.
      const raw = ctx.span.output;
      return ctx.span.type === "AGENT"
        ? <MessageContent raw={asRoleMessage("assistant", raw)} />
        : <MessageContent raw={raw} />;
    }
    case "srsummary":
      return ctx.level === "S" ? <RollingSummaryCell kind="span" id={ctx.span.span_id} /> : null;
    case "susage":
      return ctx.level === "S" ? <UsageCell usage={spanUsage(ctx.span)} /> : null;
    default:
      return null;
  }
}

// ── rows ────────────────────────────────────────────────────────────────────────
// The per-row Play button: C rows evaluate the whole thread (turns + conversation metrics),
// M/S rows re-evaluate their turn. Spins while that scope is running.
function RowRunButton({ ctx }: { ctx: RowCtx }) {
  const view = useContext(EvalViewContext);
  if (!view.hasEvaluators) return null;
  const busy =
    ctx.level === "C"
      ? view.busyRows.has(`th:${ctx.conv.thread}`)
      : view.busyRows.has(`tr:${ctx.turn.trace_id}`) ||
        (ctx.level === "M" && view.busyRows.has(`th:${ctx.conv.thread}`));
  if (busy) {
    return (
      <span className="inline-flex h-6 w-6 items-center justify-center" title="Evaluating…">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />
      </span>
    );
  }
  return (
    <button
      tabIndex={-1}
      onClick={(e) => {
        e.stopPropagation();
        if (ctx.level === "C") view.runThread(ctx.conv.thread);
        else view.runTrace(ctx.turn.trace_id);
      }}
      className="inline-flex h-6 w-6 items-center justify-center rounded-lg opacity-0 transition-opacity hover:bg-slate-700 group-hover:opacity-100"
      title={ctx.level === "C" ? "Run all evaluations for this conversation" : "Run all evaluations for this turn"}
    >
      <Play className="h-3 w-3 text-slate-400" />
    </button>
  );
}

function DataRow({
  depth,
  ctx,
  cols,
  canExpand,
  open,
  onToggle,
  agentCount,
}: {
  depth: 0 | 1 | 2;
  ctx: RowCtx;
  cols: Col[];
  canExpand?: boolean;
  open?: boolean;
  onToggle?: () => void;
  agentCount?: number;
}) {
  const router = useRouter();
  // Whole-row click zooms in — but only at the conversation and message levels. Step (S) rows are
  // NOT row-clickable (too easy to mis-click while reading); their expandable objects/pills still
  // work on their own. Clicks on interactive elements (chevron, pills, links) are always left alone.
  const isStep = ctx.level === "S";
  const href =
    ctx.level === "C"
      ? ctx.conv.turns > 1
        ? `/sessions/${ctx.conv.thread}`
        : `/traces/${ctx.conv.last_trace_id}`
      : `/traces/${ctx.turn.trace_id}`;
  return (
    <tr
      onClick={
        isStep
          ? undefined
          : (e) => {
              if ((e.target as HTMLElement).closest("button, a, input, label")) return;
              router.push(href);
            }
      }
      className={clsx(
        "group border-b border-l-2 border-slate-800 transition-colors hover:bg-slate-800/80",
        !isStep && "cursor-pointer",
        ROW_BG[depth],
      )}
    >
      <td style={CTRL} className="px-2 py-2 align-top first:pl-2 sm:px-3 sm:first:pl-4">
        {canExpand ? (
          <button onClick={onToggle} className="rounded p-1 transition-colors hover:bg-slate-700" aria-label={open ? "Collapse" : "Expand"}>
            <ChevronR className={clsx("h-4 w-4 text-slate-400 transition-transform", open && "rotate-90")} />
          </button>
        ) : (
          <div className="w-4" />
        )}
      </td>
      <td style={CTRL} className="px-2 py-2 align-top sm:px-3">
        <RowRunButton ctx={ctx} />
      </td>
      <td style={CTRL} className="px-2 py-2 align-top sm:px-3">
        {ctx.level === "C" ? (
          <button tabIndex={-1} className="inline-flex h-6 w-6 items-center justify-center rounded-lg opacity-0 transition-opacity hover:bg-slate-700 group-hover:opacity-100" title={`View ${agentCount ?? 1} agent${(agentCount ?? 1) === 1 ? "" : "s"}`}>
            <Bot className="h-3 w-3 text-slate-400" />
          </button>
        ) : null}
      </td>
      {cols.map((col, i) => (
        <td
          key={col.key}
          style={{ width: col.width, minWidth: 80 }}
          className={clsx(
            "px-2 py-2 align-top text-sm text-slate-300 sm:px-3",
            (col.evaluator || (i > 0 && cols[i - 1].group !== col.group)) && "border-l border-slate-600/50",
            col.tint?.td,
          )}
        >
          {renderCell(col, ctx)}
        </td>
      ))}
    </tr>
  );
}

// memo: a turn's step rows depend only on (turn, spans, cols, hiddenTypes) — all referentially stable
// across unrelated parent re-renders (busy/prefs/another thread expanding), so they skip re-rendering.
const SpanRows = memo(function SpanRows({ turn, spans, cols, hiddenTypes }: { turn: FullTurn; spans: SpanOut[]; cols: Col[]; hiddenTypes: Set<string> }) {
  const visible = sortSpans(spans).filter((s) => !hiddenTypes.has(normalizeType(s.type)));
  if (visible.length === 0) {
    return <EmptyTr cols={cols} text={spans.length ? "All step types hidden." : "No steps."} />;
  }
  return (
    <>
      {visible.map((span, i) => (
        <DataRow key={span.span_id} depth={2} cols={cols} ctx={{ level: "S", span, index: i + 1, turn }} />
      ))}
    </>
  );
});

function TurnRows({
  conv,
  turn,
  turnPos,
  spans,
  cols,
  hiddenTypes,
  open,
  onToggleTurn,
}: {
  conv: ConvNode;
  turn: FullTurn;
  turnPos: number;
  spans: SpanOut[] | "loading" | undefined;
  cols: Col[];
  hiddenTypes: Set<string>;
  open: boolean;
  onToggleTurn: (t: string) => void;
}) {
  return (
    <>
      {turn.input && <DataRow depth={1} cols={cols} ctx={{ level: "M", role: "user", conv, turn, index: turnPos * 2 + 1 }} />}
      <DataRow depth={1} cols={cols} ctx={{ level: "M", role: "assistant", conv, turn, index: turnPos * 2 + 2 }} canExpand open={open} onToggle={() => onToggleTurn(turn.trace_id)} />
      {open &&
        (spans === "loading" || spans === undefined ? (
          <LoadingTr cols={cols} />
        ) : spans.length === 0 ? (
          <EmptyTr cols={cols} text="No steps." />
        ) : (
          <SpanRows turn={turn} spans={spans} cols={cols} hiddenTypes={hiddenTypes} />
        ))}
    </>
  );
}

function ConvRows({
  conv,
  turns,
  spansCache,
  open,
  openTurn,
  cols,
  hiddenTypes,
  onToggleConv,
  onToggleTurn,
}: {
  conv: ConvNode;
  turns: FullTurn[] | "loading" | undefined;
  spansCache: Cache<SpanOut[]>;
  open: boolean;
  openTurn: Set<string>;
  cols: Col[];
  hiddenTypes: Set<string>;
  onToggleConv: (t: string) => void;
  onToggleTurn: (t: string) => void;
}) {
  const agentCount = useMemo(() => {
    if (!conv.turnsData) return 1;
    const set = new Set<string>();
    for (const t of conv.turnsData) for (const s of t.spans) {
      const a = agentLabel(s);
      if (a) set.add(a);
    }
    return set.size || 1;
  }, [conv]);

  return (
    <>
      <DataRow depth={0} cols={cols} ctx={{ level: "C", conv, agentCount }} canExpand open={open} onToggle={() => onToggleConv(conv.thread)} agentCount={agentCount} />
      {open &&
        (turns === "loading" || turns === undefined ? (
          <LoadingTr cols={cols} />
        ) : turns.length === 0 ? (
          <EmptyTr cols={cols} text="No messages." />
        ) : (
          turns.map((turn, i) => (
            <TurnRows key={turn.trace_id} conv={conv} turn={turn} turnPos={i} spans={spansCache[turn.trace_id]} cols={cols} hiddenTypes={hiddenTypes} open={openTurn.has(turn.trace_id)} onToggleTurn={onToggleTurn} />
          ))
        ))}
    </>
  );
}

function LoadingTr({ cols }: { cols: Col[] }) {
  return (
    <tr className="border-b border-slate-800 bg-slate-800/20">
      <td colSpan={3 + cols.length} className="px-6 py-3 text-sm text-slate-500">
        <span className="inline-flex items-center gap-2">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-700 border-t-slate-400" />
          loading…
        </span>
      </td>
    </tr>
  );
}

function EmptyTr({ cols, text }: { cols: Col[]; text: string }) {
  return (
    <tr className="border-b border-slate-800 bg-slate-800/20">
      <td colSpan={3 + cols.length} className="px-6 py-3 text-sm text-slate-500">
        {text}
      </td>
    </tr>
  );
}

// ── column-visibility menu ──────────────────────────────────────────────────────
function fmtCostCents(cents: number): string {
  // Show "<¢" for sub-cent totals so a real $0.003/30d isn't displayed as a fake $0.00.
  if (cents <= 0) return "<¢";
  if (cents < 100) return `${cents}¢`;
  return `$${(cents / 100).toFixed(cents < 10_000 ? 2 : 0)}`;
}

function ColumnsMenu({ all, hidden, cost, onToggle, onClose }: { all: Col[]; hidden: Set<string>; cost: Record<string, EvaluatorCost>; onToggle: (k: string) => void; onClose: () => void }) {
  return (
    <>
      <div className="fixed inset-0 z-20" onClick={onClose} />
      <div className="absolute right-0 top-full z-30 mt-1 w-64 rounded-lg border border-slate-700 bg-slate-900 p-2 shadow-xl shadow-slate-900/50">
        <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-slate-500">Toggle columns · judge cost (30d)</div>
        <div className="max-h-72 overflow-auto">
          {all.map((col) => {
            const c = col.evaluator ? cost[col.evaluator.score_name] : undefined;
            return (
              <label key={col.key} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-slate-300 hover:bg-slate-800">
                <input type="checkbox" checked={!hidden.has(col.key)} onChange={() => onToggle(col.key)} className="accent-cyan-500" />
                <span className="truncate">{col.label}</span>
                {col.evaluator && <span className="rounded bg-cyan-500/15 px-1 text-[9px] font-medium uppercase text-cyan-300">eval</span>}
                {c && (
                  <span
                    className="rounded bg-slate-700/60 px-1 font-mono text-[9px] text-slate-400"
                    title={`${c.runs} run(s) · ${c.total_tokens.toLocaleString()} tokens · ${fmtCostCents(c.cost_usd_cents)} over 30d${c.model ? ` · ${c.model}` : ""}`}
                  >
                    {fmtCostCents(c.cost_usd_cents)} · {fmtTokens(c.total_tokens)}
                  </span>
                )}
                <span className={clsx("ml-auto rounded px-1 text-[10px] font-medium", LEVEL_BADGE[col.group])}>{col.group}</span>
              </label>
            );
          })}
        </div>
      </div>
    </>
  );
}

// ── step-type filter menu ────────────────────────────────────────────────────────
// Hide noisy span types (e.g. the many CHAIN spans some frameworks emit) from the step rows.
function TypesMenu({ types, hidden, onToggle, onReset, onClose }: { types: string[]; hidden: Set<string>; onToggle: (t: string) => void; onReset: () => void; onClose: () => void }) {
  return (
    <>
      <div className="fixed inset-0 z-20" onClick={onClose} />
      <div className="absolute right-0 top-full z-30 mt-1 w-56 rounded-lg border border-slate-700 bg-slate-900 p-2 shadow-xl shadow-slate-900/50">
        <div className="flex items-center justify-between px-2 py-1 text-[10px] uppercase tracking-wider text-slate-500">
          <span>Filter step types</span>
          {hidden.size > 0 && (
            <button onClick={onReset} className="rounded px-1.5 py-0.5 text-[10px] normal-case tracking-normal text-cyan-400 hover:bg-slate-800 hover:text-cyan-300" title="Show all types">
              Reset
            </button>
          )}
        </div>
        <div className="max-h-72 overflow-auto">
          {types.map((t) => (
            <label key={t} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-slate-300 hover:bg-slate-800">
              <input type="checkbox" checked={!hidden.has(t)} onChange={() => onToggle(t)} className="accent-cyan-500" />
              <TypeChip type={t} />
            </label>
          ))}
        </div>
      </div>
    </>
  );
}

// ── header ──────────────────────────────────────────────────────────────────────
// Metric-column header controls: a Run button (whole column across the loaded rows) and a
// ⋯ menu with Edit / Delete.
function HeaderEvalControls({ evaluator }: { evaluator: EvaluatorDef }) {
  const view = useContext(EvalViewContext);
  const [menu, setMenu] = useState(false);
  const busy = view.busyCols.has(evaluator.score_name);
  return (
    <span className="ml-0.5 inline-flex items-center">
      {busy ? (
        <span className="inline-flex h-5 w-5 items-center justify-center" title="Evaluating…">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />
        </span>
      ) : (
        <button
          onClick={() => view.runColumn(evaluator)}
          className="inline-flex h-5 w-5 items-center justify-center rounded text-emerald-400 transition-colors hover:bg-slate-700 hover:text-emerald-300"
          title={`Run "${evaluator.name}" on all loaded rows`}
        >
          <Play className="h-3 w-3" />
        </button>
      )}
      <span className="relative">
        <button
          onClick={() => setMenu((o) => !o)}
          className="inline-flex h-5 w-5 items-center justify-center rounded text-slate-500 transition-colors hover:bg-slate-700 hover:text-slate-300"
          title="Column options"
        >
          <DotsIcon className="h-3 w-3" />
        </button>
        {menu && (
          <>
            <span className="fixed inset-0 z-20" onClick={() => setMenu(false)} />
            <span className="absolute right-0 top-full z-30 mt-1 block w-36 overflow-hidden rounded-lg border border-slate-700 bg-slate-900 py-1 shadow-xl shadow-slate-900/50">
              {!evaluator.enabled && (
                <span className="block px-3 py-1 text-[10px] font-medium uppercase tracking-wider text-amber-400/80">auto-run off</span>
              )}
              <button
                onClick={() => { setMenu(false); view.editColumn(evaluator); }}
                className="block w-full px-3 py-1.5 text-left text-xs font-normal normal-case tracking-normal text-slate-300 hover:bg-slate-800"
              >
                Edit column
              </button>
              <button
                onClick={() => { setMenu(false); view.removeColumn(evaluator); }}
                className="block w-full px-3 py-1.5 text-left text-xs font-normal normal-case tracking-normal text-rose-400 hover:bg-slate-800"
              >
                Delete column
              </button>
            </span>
          </>
        )}
      </span>
    </span>
  );
}

function HeaderRow({ cols }: { cols: Col[] }) {
  return (
    <tr className="border-b border-slate-700 bg-slate-800">
      <th style={CTRL} className={HEAD_TH} />
      <th style={CTRL} className={HEAD_TH} />
      <th style={CTRL} className={HEAD_TH} />
      {cols.map((col, i) => (
        <th
          key={col.key}
          style={{ width: col.width, minWidth: 80 }}
          className={clsx(
            HEAD_TH,
            (col.evaluator || (i > 0 && cols[i - 1].group !== col.group)) && "border-l border-slate-600/60",
            col.tint?.th,
          )}
        >
          <div className="flex items-center gap-1">
            <span className={clsx(col.evaluator && "max-w-[150px] truncate")} title={col.evaluator ? `${col.label} — ${col.evaluator.description || "evaluation column"}` : undefined}>
              {col.label}
            </span>
            <span className={clsx("rounded px-1.5 py-0.5 text-[10px] font-medium", LEVEL_BADGE[col.group])}>{col.group}</span>
            {col.evaluator && <HeaderEvalControls evaluator={col.evaluator} />}
          </div>
        </th>
      ))}
    </tr>
  );
}

// ── root ────────────────────────────────────────────────────────────────────────
type Cache<T> = Record<string, T | "loading" | undefined>;

export function TraceTable({
  conversations,
  embedded = false,
}: {
  conversations: ConvNode[];
  // When embedded in a tabbed trace view, the parent owns the Enlarge/Concise control + the
  // full-width breakout (so it applies across Table/Timeline/Evaluations), so we suppress ours.
  embedded?: boolean;
}) {
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
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const { hidden: hiddenTypes, toggle: toggleType, reset: resetTypes } = useHiddenTypes();
  const [colMenu, setColMenu] = useState(false);
  const [typeMenu, setTypeMenu] = useState(false);
  const [wide, setWide] = useWide();

  // ── evaluation columns: definitions + live run state ──────────────────────────
  const [evaluators, setEvaluators] = useState<EvaluatorDef[]>([]);
  const [evalCost, setEvalCost] = useState<Record<string, EvaluatorCost>>({});
  const liveStore = useLiveScoreStore();
  const [busyCols, setBusyCols] = useState<Set<string>>(new Set());
  const [busyRows, setBusyRows] = useState<Set<string>>(new Set());
  const [runError, setRunError] = useState("");
  const [columnModal, setColumnModal] = useState<{ open: boolean; editing: EvaluatorDef | null }>({
    open: false,
    editing: null,
  });
  useEffect(() => {
    void listEvaluators().then(setEvaluators).catch(() => {});
    void getEvaluatorCost(30).then((c) => setEvalCost(c.evaluators)).catch(() => {});
  }, []);

  // ── rolling summary: fetch a thread's by-level summaries once (the conversation row triggers
  // it), merged into id-keyed maps so the turn/step cells read by trace_id / span_id. ──
  const [rsum, setRsum] = useState<{
    conversations: Record<string, SummaryItems | null>;
    traces: Record<string, SummaryItems | null>;
    spans: Record<string, SummaryItems | null>;
  }>({ conversations: {}, traces: {}, spans: {} });
  const [rsumGenerating, setRsumGenerating] = useState<Set<string>>(new Set());
  const rsumInflight = useRef<Set<string>>(new Set());

  const loadRsum = useCallback((thread: string) => {
    rsumInflight.current.add(thread);
    return fetch(`/api/sessions/${encodeURIComponent(thread)}/rolling-summary/by-level`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        setRsum((p) => ({
          conversations: { ...p.conversations, [thread]: d.conversation ?? null },
          traces: { ...p.traces, ...(d.traces ?? {}) },
          spans: { ...p.spans, ...(d.spans ?? {}) },
        }));
      })
      .catch(() => {})
      .finally(() => rsumInflight.current.delete(thread));
  }, []);

  const ensureRsum = useCallback(
    (thread: string) => {
      if (!thread || rsumInflight.current.has(thread) || rsum.conversations[thread] !== undefined) return;
      void loadRsum(thread);
    },
    [loadRsum, rsum.conversations],
  );

  const generateRsum = useCallback(
    (thread: string) => {
      if (!thread || rsumGenerating.has(thread)) return;
      setRsumGenerating((p) => new Set(p).add(thread));
      void fetch(`/api/sessions/${encodeURIComponent(thread)}/rolling-summary/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      })
        .then(() => loadRsum(thread))
        .catch(() => {})
        .finally(() => setRsumGenerating((p) => { const n = new Set(p); n.delete(thread); return n; }));
    },
    [loadRsum, rsumGenerating],
  );

  const rsumView = useMemo<RollingSummaryView>(
    () => ({
      conversations: rsum.conversations,
      traces: rsum.traces,
      spans: rsum.spans,
      ensure: ensureRsum,
      generate: generateRsum,
      generating: rsumGenerating,
    }),
    [rsum, ensureRsum, generateRsum, rsumGenerating],
  );

  // Fixed columns first, then EVERY metric column at the right end of the table (ordered
  // C-metrics → M-metrics → S-metrics, creation order within a level), each with its own
  // cycled column tint — the TurnWise layout.
  const allColumns = useMemo<Col[]>(() => {
    const groupOrder: Record<Group, number> = { C: 0, M: 1, S: 2 };
    const metric: Col[] = [...evaluators]
      .sort((a, b) => groupOrder[levelGroup(a.level)] - groupOrder[levelGroup(b.level)])
      .map((ev, i) => ({
        key: `eval:${ev.score_name}`,
        label: ev.name,
        group: levelGroup(ev.level),
        // sized so chip + 16-char teaser pill fit without spilling into the next column
        width: 230,
        evaluator: ev,
        tint: METRIC_TINTS[i % METRIC_TINTS.length],
      }));
    return [...COLUMNS, ...metric];
  }, [evaluators]);
  const cols = useMemo(() => allColumns.filter((c) => !hidden.has(c.key)), [allColumns, hidden]);

  async function runScope(scope: RunScope, busy: { cols?: string[]; rows?: string[] }) {
    setRunError("");
    if (busy.cols?.length) setBusyCols((p) => new Set([...p, ...busy.cols!]));
    if (busy.rows?.length) setBusyRows((p) => new Set([...p, ...busy.rows!]));
    try {
      await streamEvaluationRun(scope, (e) => {
        if (e.type === "result") {
          const key = scoreKey(e.score);
          if (key) liveStore.set(key, e.score);
        } else if (e.type === "target_error") {
          setRunError(`${e.target}: ${e.detail}`);
        } else if (e.type === "error") {
          setRunError(e.detail);
        }
      });
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "evaluation run failed");
    } finally {
      if (busy.cols?.length) setBusyCols((p) => { const n = new Set(p); busy.cols!.forEach((c) => n.delete(c)); return n; });
      if (busy.rows?.length) setBusyRows((p) => { const n = new Set(p); busy.rows!.forEach((r) => n.delete(r)); return n; });
    }
  }

  function threadBusyKeys(thread: string): string[] {
    const t = turns[thread];
    return [`th:${thread}`, ...(Array.isArray(t) ? t.map((x) => `tr:${x.trace_id}`) : [])];
  }

  const evalView = useMemo<EvalView>(() => ({
    busyCols,
    busyRows,
    hasEvaluators: evaluators.length > 0,
    runThread: (thread) => void runScope({ thread_ids: [thread] }, { rows: threadBusyKeys(thread) }),
    runTrace: (trace) => void runScope({ trace_ids: [trace] }, { rows: [`tr:${trace}`] }),
    runColumn: (ev) =>
      void runScope(
        { evaluator_ids: [ev.id], thread_ids: conversations.map((c) => c.thread) },
        { cols: [ev.score_name] },
      ),
    editColumn: (ev) => setColumnModal({ open: true, editing: ev }),
    removeColumn: (ev) => {
      if (!window.confirm(`Delete the "${ev.name}" column? Past results stay in the score history.`)) return;
      void deleteEvaluator(ev.id)
        .then(() => listEvaluators().then(setEvaluators))
        .catch((e) => setRunError(e instanceof Error ? e.message : "delete failed"));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [busyCols, busyRows, evaluators, conversations, turns]);

  function runAllEvals() {
    void runScope(
      { thread_ids: conversations.map((c) => c.thread) },
      { cols: evaluators.map((e) => e.score_name) },
    );
  }
  const anyRunning = busyCols.size > 0 || busyRows.size > 0;
  // Types listed in the filter menu: the canonical set (always) plus any extra types the current
  // data emits (so SDK additions show up automatically). Canonical order first, extras alphabetical.
  const spanTypes = useMemo(() => {
    const present = new Set<string>();
    const add = (arr?: SpanOut[]) => arr?.forEach((s) => s.type && present.add(normalizeType(s.type)));
    Object.values(spans).forEach((v) => Array.isArray(v) && add(v));
    conversations.forEach((c) => c.turnsData?.forEach((t) => add(t.spans)));
    const canonical = new Set<string>(KNOWN_SPAN_TYPES);
    const extras = [...present].filter((t) => !canonical.has(t)).sort();
    return [...KNOWN_SPAN_TYPES, ...extras];
  }, [spans, conversations]);

  // Restore saved view prefs on mount, then persist on change (skip writes until loaded so the
  // initial defaults don't clobber what's stored).
  const [prefsLoaded, setPrefsLoaded] = useState(false);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(PREFS_KEY);
      if (raw) {
        const p = JSON.parse(raw) as { hidden?: unknown };
        if (Array.isArray(p.hidden)) setHidden(new Set(p.hidden as string[]));
      }
    } catch {
      /* ignore */
    }
    setPrefsLoaded(true);
  }, []);
  useEffect(() => {
    if (!prefsLoaded) return;
    try {
      // Read-modify-write so we don't clobber the hiddenTypes field owned by useHiddenTypes().
      const raw = localStorage.getItem(PREFS_KEY);
      const cur = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
      localStorage.setItem(PREFS_KEY, JSON.stringify({ ...cur, hidden: [...hidden] }));
    } catch {
      /* ignore */
    }
  }, [prefsLoaded, hidden]);

  async function loadTurns(thread: string): Promise<FullTurn[]> {
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
  }

  async function loadSpans(trace: string): Promise<SpanOut[]> {
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
  }

  function toggleConv(thread: string) {
    setOpenConv((prev) => {
      const next = new Set(prev);
      if (next.has(thread)) next.delete(thread);
      else {
        next.add(thread);
        if (turns[thread] === undefined) void loadTurns(thread);
      }
      return next;
    });
  }

  function toggleTurn(trace: string) {
    setOpenTurn((prev) => {
      const next = new Set(prev);
      if (next.has(trace)) next.delete(trace);
      else {
        next.add(trace);
        if (spans[trace] === undefined) void loadSpans(trace);
      }
      return next;
    });
  }

  const allOpen = conversations.length > 0 && conversations.every((c) => openConv.has(c.thread));

  // Expand everything to the step level: open all conversations, load + open their turns, then
  // load every turn's steps (lazy data is fetched as needed). Runs as one async cascade.
  async function expandAll() {
    setOpenConv(new Set(conversations.map((c) => c.thread)));
    const perConv = await Promise.all(
      conversations.map((c) => {
        const existing = turns[c.thread];
        return Array.isArray(existing) ? Promise.resolve(existing) : loadTurns(c.thread);
      }),
    );
    const traceIds = perConv.flat().map((t) => t.trace_id);
    setOpenTurn(new Set(traceIds));
    await Promise.all(traceIds.map((id) => (spans[id] === undefined ? loadSpans(id) : Promise.resolve([]))));
  }

  function toggleAll() {
    if (allOpen) {
      setOpenConv(new Set());
      setOpenTurn(new Set());
      return;
    }
    void expandAll();
  }

  function toggleCol(key: string) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <EvalViewContext.Provider value={evalView}>
      <LiveScoreContext.Provider value={liveStore}>
      <RollingSummaryContext.Provider value={rsumView}>
      <div
        style={!embedded && wide ? WIDE_STYLE : undefined}
        className="overflow-hidden rounded-lg border border-slate-700 transition-[width,margin] duration-200"
      >
        <div className="flex items-center justify-between border-b border-slate-700 bg-slate-800/50 px-4 py-2">
          <div className="flex items-center gap-1">
            <button onClick={toggleAll} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-white">
              <ChevronsUpDown className="h-3.5 w-3.5" />
              <span>{allOpen ? "Collapse All" : "Expand All"}</span>
            </button>
            {evaluators.length > 0 && conversations.length > 0 && (
              <button
                onClick={runAllEvals}
                disabled={anyRunning}
                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-emerald-300 disabled:opacity-50"
                title="Run every evaluation column on all loaded rows"
              >
                {anyRunning ? (
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-700 border-t-emerald-400" />
                ) : (
                  <Play className="h-3.5 w-3.5 text-emerald-400" />
                )}
                <span>Run evals</span>
              </button>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setColumnModal({ open: true, editing: null })}
              className="inline-flex items-center gap-1.5 rounded-lg border border-signal/40 bg-signal/15 px-3 py-1.5 text-xs font-medium text-signal transition-all hover:bg-signal/25 hover:shadow-glow"
              title="Add an evaluation column"
            >
              <PlusIcon className="h-3.5 w-3.5" />
              <span>Add Column</span>
            </button>
            {!embedded && <WideToggle wide={wide} onToggle={() => setWide(!wide)} />}
            <div className="relative">
              <button onClick={() => setTypeMenu((o) => !o)} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-white" title="Filter step types">
                <FilterIcon className="h-3.5 w-3.5" />
                <span>Types</span>
                {hiddenTypes.size > 0 && <span className="rounded bg-cyan-500/20 px-1.5 text-[10px] font-medium text-cyan-300">{hiddenTypes.size}</span>}
              </button>
              {typeMenu && <TypesMenu types={spanTypes} hidden={hiddenTypes} onToggle={toggleType} onReset={resetTypes} onClose={() => setTypeMenu(false)} />}
            </div>
            <div className="relative">
              <button onClick={() => setColMenu((o) => !o)} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-white" title="Manage Column Visibility">
                <Eye className="h-3.5 w-3.5" />
                <span>Columns</span>
              </button>
              {colMenu && <ColumnsMenu all={allColumns} hidden={hidden} cost={evalCost} onToggle={toggleCol} onClose={() => setColMenu(false)} />}
            </div>
          </div>
        </div>

        {runError && (
          <div className="flex items-center justify-between gap-3 border-b border-rose-500/20 bg-rose-500/[0.06] px-4 py-2 text-[12px] text-rose-300">
            <span className="truncate">{runError}</span>
            <button onClick={() => setRunError("")} className="shrink-0 rounded px-1.5 text-rose-400 hover:bg-rose-500/10" aria-label="Dismiss">
              ✕
            </button>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] border-collapse">
            <thead>
              <HeaderRow cols={cols} />
            </thead>
            <tbody>
              {conversations.length === 0 ? (
                <tr>
                  <td colSpan={3 + cols.length} className="px-6 py-14 text-center text-sm text-slate-500">
                    No conversations.
                  </td>
                </tr>
              ) : (
                conversations.map((c) => (
                  <ConvRows
                    key={c.thread}
                    conv={c}
                    turns={turns[c.thread]}
                    spansCache={spans}
                    open={openConv.has(c.thread)}
                    openTurn={openTurn}
                    cols={cols}
                    hiddenTypes={hiddenTypes}
                    onToggleConv={toggleConv}
                    onToggleTurn={toggleTurn}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <AddColumnModal
        open={columnModal.open}
        editing={columnModal.editing}
        previewThread={[...openConv][0] ?? conversations[0]?.thread}
        onClose={() => setColumnModal({ open: false, editing: null })}
        onSaved={() => void listEvaluators().then(setEvaluators)}
      />
      </RollingSummaryContext.Provider>
      </LiveScoreContext.Provider>
    </EvalViewContext.Provider>
  );
}
