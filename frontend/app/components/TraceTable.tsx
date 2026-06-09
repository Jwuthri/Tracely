"use client";

import clsx from "clsx";
import { useEffect, useMemo, useState, type ReactNode, type SVGProps } from "react";
import { useRouter } from "next/navigation";
import type { ConvNode, FullTurn, SpanOut, ThreadTurn } from "../lib/api";
import { convUsage, fmtUsd, spanUsage, turnUsage, usageSummary } from "../lib/usage";
import { mergeMeta } from "../lib/meta";
import { useHiddenTypes } from "../lib/typePrefs";
import { useWide, WideToggle, WIDE_STYLE } from "../lib/useWide";
import { ExpandableText, FloatingPanel, HighlightedJson, IconBox, JsonPill, Pill, Plain, prettyJson } from "./JsonView";
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

// ── columns ───────────────────────────────────────────────────────────────────
type Group = "C" | "M" | "S";
type Col = { key: string; label: string; group: Group; width: number };

const COLUMNS: Col[] = [
  { key: "conversation", label: "Conversation", group: "C", width: 260 },
  { key: "ctime",        label: "Datetime",     group: "C", width: 160 },
  { key: "cdur",         label: "Duration",     group: "C", width: 96 },
  { key: "summary", label: "Summary", group: "C", width: 320 },
  { key: "cmeta", label: "Metadata", group: "C", width: 200 },
  { key: "cusage", label: "Usage", group: "C", width: 180 },
  { key: "role", label: "Role", group: "M", width: 110 },
  { key: "mindex", label: "#", group: "M", width: 56 },
  { key: "mtime", label: "Datetime", group: "M", width: 160 },
  { key: "mdur",  label: "Duration", group: "M", width: 96 },
  { key: "content", label: "Content", group: "M", width: 420 },
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
function fmtDateTime(ts?: string | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function fmtMs(ms?: number | null): string {
  if (ms == null || ms < 0) return "—";
  if (ms === 0) return "<1ms"; // sub-millisecond runs (synthetic demo spans) → don't show "—"
  if (ms < 1) return `${ms.toFixed(2)}ms`;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}
function durationMs(span: SpanOut): number | null {
  if (span.latency_ms != null && span.latency_ms > 0) return span.latency_ms;
  if (span.end_time && span.start_time) {
    const d = new Date(span.end_time).getTime() - new Date(span.start_time).getTime();
    return d > 0 ? d : null;
  }
  return null;
}
// Pull the first human-readable text out of a value that may be a string, a content-block
// array ([{type:"text",text}, {type:"image_url"}…]), a chat-message array, or a {content} object.
function firstText(v: unknown): string {
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    // A chat-message array ([{role|type, content}, …]) — prefer the first user/human turn over a
    // leading system prompt or tool message, so the conversation title is the actual user question.
    // Skip messages whose extracted content is empty (e.g. LangGraph's root captures the input as
    // [{role:"user", content:""}] when the real text is one level deeper).
    if (v.some((m) => m && typeof m === "object" && "content" in m && ("role" in m || "type" in m))) {
      const role = (m: Record<string, unknown>) => String(m.role ?? m.type ?? "");
      const msgs = v as Record<string, unknown>[];
      const withText = msgs
        .map((m) => ({ m, t: firstText(m.content ?? m.text ?? "") }))
        .filter((x) => x.t);
      const pick =
        withText.find((x) => /user|human/i.test(role(x.m))) ??
        withText.find((x) => !/system|tool/i.test(role(x.m))) ??
        withText[0];
      if (pick) return pick.t;
    }
    for (const item of v) {
      const t = firstText(item);
      if (t) return t;
    }
    return "";
  }
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (Array.isArray(o.messages)) return firstText(o.messages); // {messages:[…]} chat-input wrapper
    if (typeof o.text === "string") return o.text;
    if (typeof o.content === "string") return o.content;
    if (o.content != null) return firstText(o.content);
    // @observe captures fn args as {kwarg_name: value}. Probe common prompt-shaped keys first,
    // then fall back to the sole string value if the dict is single-shaped (e.g. {question:"…"}).
    for (const k of ["prompt", "input", "question", "query", "user_input", "msg", "message"]) {
      const t = firstText(o[k]);
      if (t) return t;
    }
    const stringVals = Object.values(o).filter((x) => typeof x === "string") as string[];
    if (stringVals.length === 1) return stringVals[0];
  }
  return "";
}

function deriveTitle(s: string | null): string {
  if (!s) return "Conversation";
  let text = s;
  const t = s.trim();
  if (t.startsWith("[") || t.startsWith("{")) {
    try {
      const parsed = JSON.parse(t);
      const found = firstText(parsed);
      if (found) text = found;
      // Parsed but no extractable text (e.g. LangGraph's [{role:"user",content:""}] at the root —
      // the actual message lives in a child span). Show a placeholder instead of the raw JSON.
      else return "Conversation";
    } catch {
      /* not JSON — use raw */
    }
  }
  // Find the first non-empty line (some frameworks prefix the content with `\n` — CrewAI's
  // `\nCurrent Task: …`, for instance — so a naive split-on-newline yields "").
  const line = text.split("\n").map((l) => l.trim()).find(Boolean) ?? "";
  const words = line.split(/\s+/).slice(0, 7).join(" ");
  return words.length < line.length ? `${words}…` : words || "Conversation";
}
function sortSpans(spans: SpanOut[]): SpanOut[] {
  return [...spans].sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime());
}
// agent_id is a resolved registry UUID; the human slug is kept in metadata.
function agentLabel(span: SpanOut): string {
  return span.metadata?.["tracely.agent.id"] || span.agent_id || "";
}

// The Agent column should reflect the nearest enclosing AGENT — so under "Agent workflow" (the
// OpenAI Agents SDK's outer wrapper) the column reads "Agent workflow", and only switches to
// "support-agent" once we enter that sub-agent's subtree. Falls back to the trace's agent_id when
// no AGENT ancestor exists.
function nearestAgentLabel(span: SpanOut, allSpans: SpanOut[]): string {
  if (span.type === "AGENT") return span.name || agentLabel(span);
  const byId = new Map(allSpans.map((s) => [s.span_id, s]));
  let cur: SpanOut | undefined = span;
  // safety: cap the walk at the tree's depth
  for (let i = 0; i < 64 && cur; i++) {
    const parent: SpanOut | undefined = cur.parent_span_id ? byId.get(cur.parent_span_id) : undefined;
    if (!parent) break;
    if (parent.type === "AGENT") return parent.name || agentLabel(parent);
    cur = parent;
  }
  return agentLabel(span);
}
function modelColor(m: string): string {
  const s = m.toLowerCase();
  if (s.includes("gpt-4o") || s.includes("gpt-4-turbo")) return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
  if (s.includes("gpt-4")) return "bg-green-500/10 text-green-400 border-green-500/30";
  if (s.includes("gpt-3.5")) return "bg-teal-500/10 text-teal-400 border-teal-500/30";
  if (s.includes("opus")) return "bg-orange-600/10 text-orange-400 border-orange-600/30";
  if (s.includes("sonnet") || s.includes("haiku") || s.includes("claude")) return "bg-orange-500/10 text-orange-400 border-orange-500/30";
  return "bg-slate-700/40 text-slate-300 border-slate-600/40";
}

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

type ChatMsg = { role?: string; content?: unknown; tool_calls?: unknown; finish_reason?: unknown };

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
const MESSAGE_TYPES = new Set(["human", "ai", "system", "tool", "function", "user", "assistant", "developer"]);

// OpenAI messages carry `role`; LangChain/LangGraph carry `type` ("human"/"ai"/…). Normalize both.
function msgRole(m: Record<string, unknown>): string {
  const r = String(m.role ?? m.type ?? "").toLowerCase();
  if (r === "human") return "user";
  if (r === "ai") return "assistant";
  return r;
}
function looksLikeMessage(m: unknown): m is Record<string, unknown> {
  if (!m || typeof m !== "object") return false;
  const o = m as Record<string, unknown>;
  return "role" in o || MESSAGE_TYPES.has(String(o.type ?? "").toLowerCase());
}
// The messages inside a turn payload: the {messages:[…]} state wrapper, or a bare chat array. Returns
// null for anything else (a single message, multimodal content blocks, plain text, data) so the
// caller renders it verbatim.
function messageList(parsed: unknown): Record<string, unknown>[] | null {
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const msgs = (parsed as Record<string, unknown>).messages;
    if (Array.isArray(msgs)) return msgs.filter((m): m is Record<string, unknown> => !!m && typeof m === "object");
  }
  if (Array.isArray(parsed) && parsed.length > 0 && parsed.every(looksLikeMessage)) return parsed as Record<string, unknown>[];
  return null;
}
// The last message of `role`, normalized to {role, content, …} with content kept structured (so
// multimodal parts/attachments still render). `undefined` ⇒ not a message-list shape (render
// verbatim); `null` ⇒ a list with nothing from this side.
function lastTurnMessage(raw: string | null, role: "user" | "assistant"): ChatMsg | null | undefined {
  const list = messageList(parseMaybe(raw));
  if (!list) return undefined;
  let found: Record<string, unknown> | undefined;
  for (const m of list) if (msgRole(m) === role) found = m;
  if (!found) return null;
  const kwargs = (found.kwargs ?? {}) as Record<string, unknown>; // LangChain "serialized" message form
  return {
    role,
    content: found.content ?? kwargs.content,
    tool_calls: found.tool_calls ?? kwargs.tool_calls,
    finish_reason: found.finish_reason,
  };
}
// Wrap raw single-side I/O (a plain string, a kwargs dict like `{question: "…"}`, or a multimodal
// content-blocks array) into a chat-message JSON `{role, content}` so MessageContent renders it as
// a ChatPill with role badge — matching how the assistant side already displays. Pass-through if it
// already looks like a message / message list (avoid double-wrapping).
function asRoleMessage(role: "user" | "assistant", raw: string | null): string | null {
  if (raw == null || raw === "") return raw;
  const parsed = parseMaybe(raw);
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed) && "role" in (parsed as object)) return raw;
  if (Array.isArray(parsed) && parsed.some((m) => m && typeof m === "object" && "role" in m)) return raw;
  if (messageList(parsed)) return raw;
  // {question/prompt/input/…: "<text>"} → pluck the text into content
  let content: unknown = parsed ?? raw;
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const o = parsed as Record<string, unknown>;
    const promptish = ["prompt", "input", "question", "query", "user_input", "msg", "message", "text"];
    const k = Object.keys(o).find((x) => promptish.includes(x) && typeof o[x] === "string");
    if (k) content = o[k];
  }
  return JSON.stringify({ role, content });
}

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

function parseMaybe(s: string | null): unknown {
  if (s == null) return null;
  const t = s.trim();
  if (t.startsWith("[") || t.startsWith("{")) {
    try {
      return JSON.parse(t);
    } catch {
      /* not json */
    }
  }
  return s;
}

// The assistant's reply text out of a value that may be a plain string, a chat-message array (take
// the last assistant/ai turn), or a {role:"assistant", content} object — the output-side mirror of
// firstText (which prefers the user turn).
function assistantText(v: unknown): string {
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    const asst = [...v].reverse().find(
      (m) => m && typeof m === "object" && /assistant|ai/i.test(String((m as Record<string, unknown>).role ?? (m as Record<string, unknown>).type ?? "")),
    );
    if (asst) return firstText((asst as Record<string, unknown>).content ?? asst);
    return firstText(v);
  }
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (typeof o.content === "string") return o.content;
    if (o.content != null) return firstText(o.content);
  }
  return firstText(v);
}

// Turn I/O may already be a message object ({role, content}); if so use it directly, else wrap the
// raw value with the given role — so the summary never double-nests a message inside a message.
function toMsg(role: string, raw: string | null): { role: string; content: unknown } | null {
  if (!raw) return null;
  const v = parseMaybe(raw);
  if (v && typeof v === "object" && !Array.isArray(v) && "role" in (v as object)) {
    const m = v as { role?: string; content?: unknown };
    return { role: m.role ?? role, content: m.content };
  }
  // Many provider outputs JSON-stringify as a single-element chat-message array (e.g. OpenInference
  // captures `[{"role":"assistant","content":"…"}]`). Unwrap that so the pill shows the text.
  if (Array.isArray(v) && v.length === 1 && v[0] && typeof v[0] === "object" && "role" in (v[0] as object)) {
    const m = v[0] as { role?: string; content?: unknown };
    return { role: m.role ?? role, content: m.content };
  }
  // A full prompt history ([system, user, …]) or a kwarg dict ({question: "…"}) — NOT a single
  // message. Pull out this side's readable text so the summary reads as a clean USER question /
  // ASSISTANT answer identically in every view (the single-trace turns AND the list's
  // first_input/last_output), instead of dumping the raw messages array as {role:…} JSON pills.
  if (v && typeof v === "object") {
    const text = role === "assistant" ? assistantText(v) : firstText(v);
    if (text) return { role, content: text };
  }
  return { role, content: v };
}

function ConvSummaryCell({ conv }: { conv: ConvNode }) {
  const msgs: Array<{ role: string; content: unknown }> = [];
  if (conv.turnsData) {
    for (const t of conv.turnsData) {
      const u = toMsg("user", t.input);
      const a = toMsg("assistant", t.output);
      if (u) msgs.push(u);
      if (a) msgs.push(a);
    }
  } else {
    const u = toMsg("user", conv.first_input);
    const a = toMsg("assistant", conv.last_output);
    if (u) msgs.push(u);
    if (a) msgs.push(a);
  }
  if (msgs.length === 0) return <span className="text-slate-500">—</span>;
  return <ChatPill msgs={msgs} />;
}

// ── row context + per-column dispatch ───────────────────────────────────────────
type RowCtx =
  | { level: "C"; conv: ConvNode; agentCount: number }
  | { level: "M"; role: "user" | "assistant"; conv: ConvNode; turn: FullTurn; index: number }
  | { level: "S"; span: SpanOut; index: number; turn: FullTurn };

function renderCell(col: Col, ctx: RowCtx): ReactNode {
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
    case "summary":
      return ctx.level === "C" ? <ConvSummaryCell conv={ctx.conv} /> : null;
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
    case "susage":
      return ctx.level === "S" ? <UsageCell usage={spanUsage(ctx.span)} /> : null;
    default:
      return null;
  }
}

// ── rows ────────────────────────────────────────────────────────────────────────
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
        <button tabIndex={-1} className="inline-flex h-6 w-6 items-center justify-center rounded-lg opacity-0 transition-opacity hover:bg-slate-700 group-hover:opacity-100" title="Run evaluations for this row">
          <Play className="h-3 w-3 text-slate-400" />
        </button>
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
          className={clsx("px-2 py-2 align-top text-sm text-slate-300 sm:px-3", i > 0 && cols[i - 1].group !== col.group && "border-l border-slate-700/70")}
        >
          {renderCell(col, ctx)}
        </td>
      ))}
    </tr>
  );
}

function SpanRows({ turn, spans, cols, hiddenTypes }: { turn: FullTurn; spans: SpanOut[]; cols: Col[]; hiddenTypes: Set<string> }) {
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
}

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
function ColumnsMenu({ hidden, onToggle, onClose }: { hidden: Set<string>; onToggle: (k: string) => void; onClose: () => void }) {
  return (
    <>
      <div className="fixed inset-0 z-20" onClick={onClose} />
      <div className="absolute right-0 top-full z-30 mt-1 w-60 rounded-lg border border-slate-700 bg-slate-900 p-2 shadow-xl shadow-slate-900/50">
        <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-slate-500">Toggle columns</div>
        <div className="max-h-72 overflow-auto">
          {COLUMNS.map((col) => (
            <label key={col.key} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-slate-300 hover:bg-slate-800">
              <input type="checkbox" checked={!hidden.has(col.key)} onChange={() => onToggle(col.key)} className="accent-cyan-500" />
              <span className="truncate">{col.label}</span>
              <span className={clsx("ml-auto rounded px-1 text-[10px] font-medium", LEVEL_BADGE[col.group])}>{col.group}</span>
            </label>
          ))}
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
          className={clsx(HEAD_TH, i > 0 && cols[i - 1].group !== col.group && "border-l border-slate-700")}
        >
          <div className="flex items-center gap-1">
            <span>{col.label}</span>
            <span className={clsx("rounded px-1.5 py-0.5 text-[10px] font-medium", LEVEL_BADGE[col.group])}>{col.group}</span>
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

  const cols = useMemo(() => COLUMNS.filter((c) => !hidden.has(c.key)), [hidden]);
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
    <div
      style={!embedded && wide ? WIDE_STYLE : undefined}
      className="overflow-hidden rounded-lg border border-slate-700 transition-[width,margin] duration-200"
    >
      <div className="flex items-center justify-between border-b border-slate-700 bg-slate-800/50 px-4 py-2">
        <button onClick={toggleAll} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-slate-400 transition-colors hover:bg-slate-800 hover:text-white">
          <ChevronsUpDown className="h-3.5 w-3.5" />
          <span>{allOpen ? "Collapse All" : "Expand All"}</span>
        </button>
        <div className="flex items-center gap-1">
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
            {colMenu && <ColumnsMenu hidden={hidden} onToggle={toggleCol} onClose={() => setColMenu(false)} />}
          </div>
        </div>
      </div>

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
  );
}
