"use client";

import clsx from "clsx";
import { useEffect, useMemo, useRef, useState, type ReactNode, type SVGProps } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import type { ConvNode, FullTurn, SpanOut, ThreadTurn } from "../lib/api";
import { convUsage, fmtUsd, spanUsage, turnUsage, usageSummary } from "../lib/usage";
import { mergeMeta } from "../lib/meta";
import { useWide, WideToggle, WIDE_STYLE } from "../lib/useWide";
import { HighlightedJson } from "./JsonView";
import { TypeChip } from "./ui";

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
const CopyIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><rect width="14" height="14" x="8" y="8" rx="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></svg>
);
const ImageIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><rect width="18" height="18" x="3" y="3" rx="2" ry="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" /></svg>
);
const FileIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
);

// ── columns ───────────────────────────────────────────────────────────────────
type Group = "C" | "M" | "S";
type Col = { key: string; label: string; group: Group; width: number };

const COLUMNS: Col[] = [
  { key: "conversation", label: "Conversation", group: "C", width: 260 },
  { key: "ctime",        label: "Time",         group: "C", width: 88 },
  { key: "cdur",         label: "Duration",     group: "C", width: 96 },
  { key: "summary", label: "Summary", group: "C", width: 320 },
  { key: "cmeta", label: "Metadata", group: "C", width: 200 },
  { key: "cusage", label: "Usage", group: "C", width: 180 },
  { key: "role", label: "Role", group: "M", width: 110 },
  { key: "mindex", label: "#", group: "M", width: 56 },
  { key: "mtime", label: "Time", group: "M", width: 96 },
  { key: "mdur",  label: "Duration", group: "M", width: 96 },
  { key: "content", label: "Content", group: "M", width: 420 },
  { key: "musage", label: "Usage", group: "M", width: 180 },
  { key: "sindex", label: "#", group: "S", width: 56 },
  { key: "type", label: "Type", group: "S", width: 120 },
  { key: "stime", label: "Time", group: "S", width: 96 },
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

// ── format helpers ──────────────────────────────────────────────────────────────
function fmtClock(ts?: string | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-US", { hour12: false });
}
function fmtMs(ms?: number | null): string {
  if (ms == null || ms <= 0) return "—";
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
    for (const item of v) {
      const t = firstText(item);
      if (t) return t;
    }
    return "";
  }
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (typeof o.text === "string") return o.text;
    if (typeof o.content === "string") return o.content;
    if (o.content != null) return firstText(o.content);
  }
  return "";
}

function deriveTitle(s: string | null): string {
  if (!s) return "Conversation";
  let text = s;
  const t = s.trim();
  if (t.startsWith("[") || t.startsWith("{")) {
    try {
      text = firstText(JSON.parse(t)) || s;
    } catch {
      /* not JSON — use raw */
    }
  }
  const line = text.split("\n")[0].trim();
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

type Accent = "cyan" | "fuchsia" | "amber" | "violet";
const ACCENT_BOX: Record<Accent, string> = {
  cyan: "bg-cyan-500/15 text-cyan-400",
  fuchsia: "bg-fuchsia-500/15 text-fuchsia-400",
  amber: "bg-amber-500/15 text-amber-400",
  violet: "bg-violet-500/15 text-violet-300",
};
function IconBox({ accent, children }: { accent: Accent; children: ReactNode }) {
  return <div className={clsx("flex h-5 w-5 shrink-0 items-center justify-center rounded", ACCENT_BOX[accent])}>{children}</div>;
}

// Floating detail panel (portal — escapes the table overflow): header + optional Copy + body.
function FloatingPanel({
  anchor,
  onClose,
  icon,
  title,
  subtitle,
  copyText,
  children,
}: {
  anchor: DOMRect;
  onClose: () => void;
  icon: ReactNode;
  title: string;
  subtitle: string;
  copyText?: string;
  children: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (typeof window === "undefined") return null;

  const W = 460;
  let left = anchor.left;
  if (left + W > window.innerWidth - 12) left = window.innerWidth - W - 12;
  if (left < 12) left = 12;
  const roomBelow = window.innerHeight - anchor.bottom - 12;
  const above = roomBelow < 240 && anchor.top > roomBelow;
  const maxHeight = Math.min(460, above ? anchor.top - 12 : roomBelow);
  const pos: React.CSSProperties = above
    ? { left, bottom: window.innerHeight - anchor.top + 6 }
    : { left, top: anchor.bottom + 6 };

  async function copy() {
    if (!copyText) return;
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* ignore */
    }
  }

  return createPortal(
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="fixed z-50 flex flex-col overflow-hidden rounded-lg border border-slate-700 bg-slate-900 shadow-2xl shadow-black/60" style={{ ...pos, width: W, maxHeight }}>
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-700 px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            {icon}
            <div className="min-w-0 leading-tight">
              <div className="truncate text-xs font-medium capitalize text-slate-200">{title}</div>
              <div className="text-[10px] text-slate-500">{subtitle}</div>
            </div>
          </div>
          {copyText && (
            <button onClick={copy} className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-300 transition-colors hover:bg-slate-800 hover:text-white">
              <CopyIcon className="h-3 w-3" />
              {copied ? "Copied" : "Copy"}
            </button>
          )}
        </div>
        <div className="overflow-auto">{children}</div>
      </div>
    </>,
    document.body,
  );
}

// Collapsed pill that opens a floating panel. `panel` renders the panel given the anchor + close.
function Pill({
  iconBox,
  summary,
  badge,
  panel,
}: {
  iconBox: ReactNode;
  summary: ReactNode;
  badge?: ReactNode;
  panel: (anchor: DOMRect, onClose: () => void) => ReactNode;
}) {
  const btnRef = useRef<HTMLButtonElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  return (
    <>
      <button
        ref={btnRef}
        onClick={() => setRect((r) => (r ? null : btnRef.current?.getBoundingClientRect() ?? null))}
        className="flex max-w-full items-center gap-2 rounded-md border border-slate-700/50 bg-slate-800/60 px-2.5 py-1.5 text-xs backdrop-blur-sm transition-all duration-200 hover:border-slate-600 hover:bg-slate-800/80 hover:shadow-lg hover:shadow-slate-900/50"
      >
        {iconBox}
        <span className="truncate font-mono text-slate-300/90">{summary}</span>
        {badge}
        <div className={clsx("transition-transform duration-200", rect && "rotate-90")}>
          <ChevronR className="h-3.5 w-3.5 text-slate-500" />
        </div>
      </button>
      {rect && panel(rect, () => setRect(null))}
    </>
  );
}

// A monospace JSON body for a floating panel.
function JsonPanelBody({ pretty }: { pretty: string }) {
  return (
    <pre className="whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-relaxed text-slate-300">
      <HJson text={pretty} />
    </pre>
  );
}

// ── leaf cell renderers ─────────────────────────────────────────────────────────
function Plain({ text }: { text: string }) {
  return (
    <span className="block max-w-full truncate text-sm text-slate-300" title={text}>
      {text || "—"}
    </span>
  );
}

function ExpandableText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <button onClick={() => setOpen((o) => !o)} className="flex w-full items-start gap-1.5 rounded px-1 py-0.5 text-left transition-colors hover:bg-slate-700/40">
      <ChevronR className={clsx("mt-0.5 h-3 w-3 shrink-0 text-slate-500 transition-transform", open && "rotate-90")} />
      <span className={clsx("text-sm text-slate-300", open ? "whitespace-pre-wrap" : "line-clamp-2")}>{text}</span>
    </button>
  );
}

function ObjPreview({ obj }: { obj: Record<string, unknown> }) {
  const keys = Object.keys(obj);
  if (keys.length === 0) return <span className="text-slate-500">{"{}"}</span>;
  const k = keys[0];
  const v = obj[k];
  const vs = typeof v === "string" ? v : JSON.stringify(v);
  const short = vs.length > 16 ? `${vs.slice(0, 16)}…` : vs;
  return (
    <span className="flex items-center gap-1">
      <span className="text-fuchsia-400">{k}:</span>
      <span className="text-cyan-300/80">&quot;{short}&quot;</span>
      {keys.length > 1 && <span className="text-slate-500">+{keys.length - 1}</span>}
    </span>
  );
}

function JsonPill({ raw }: { raw: string }) {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return <ExpandableText text={raw} />;
  }
  const isArr = Array.isArray(data);
  const isObj = data !== null && typeof data === "object" && !isArr;
  if (!isArr && !isObj) {
    const s = String(data);
    return s.length > 56 ? <ExpandableText text={s} /> : <Plain text={s} />;
  }
  const count = isArr ? (data as unknown[]).length : Object.keys(data as object).length;
  const pretty = JSON.stringify(data, null, 2);
  const accent: Accent = isArr ? "cyan" : "fuchsia";
  const glyph = isArr ? "[ ]" : "{ }";
  const icon = <IconBox accent={accent}><span className="text-[10px] font-bold">{glyph}</span></IconBox>;
  const summary = isArr ? (
    <span className="flex items-center gap-0.5">
      <span className="text-violet-400">[</span>
      <span className="text-[10px] font-medium text-violet-300/80">{count}</span>
      <span className="text-violet-400">]</span>
    </span>
  ) : (
    <ObjPreview obj={data as Record<string, unknown>} />
  );
  return (
    <Pill
      iconBox={icon}
      summary={summary}
      badge={<span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-slate-400">{count}</span>}
      panel={(a, c) => (
        <FloatingPanel anchor={a} onClose={c} icon={icon} title={isArr ? "array" : "object"} subtitle={`${count} ${isArr ? (count === 1 ? "item" : "items") : count === 1 ? "key" : "keys"}`} copyText={pretty}>
          <JsonPanelBody pretty={pretty} />
        </FloatingPanel>
      )}
    />
  );
}

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
  const last = msgs[n - 1] ?? {};
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
  if (parsed === null) return <ExpandableText text={raw} />;
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
  // one message's multimodal parts (no roles) -> text + image/file chips
  if (Array.isArray(parsed) && parsed.length > 0 && parsed.every(isContentBlock)) {
    return <ContentParts value={parsed} />;
  }
  if (parsed && typeof parsed === "object" && Array.isArray((parsed as Record<string, unknown>).content)) {
    return <ContentParts value={(parsed as Record<string, unknown>).content} />;
  }
  // structured data (tool args/results, output schema) -> JSON pill
  if (typeof parsed === "object") return <JsonPill raw={t} />;
  const s = String(parsed);
  return s.length > 56 ? <ExpandableText text={s} /> : <Plain text={s} />;
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

// Turn I/O may already be a message object ({role, content}); if so use it directly, else wrap the
// raw value with the given role — so the summary never double-nests a message inside a message.
function toMsg(role: string, raw: string | null): { role: string; content: unknown } | null {
  if (!raw) return null;
  const v = parseMaybe(raw);
  if (v && typeof v === "object" && !Array.isArray(v) && "role" in (v as object)) {
    const m = v as { role?: string; content?: unknown };
    return { role: m.role ?? role, content: m.content };
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
        ? <span className="font-mono text-xs text-slate-400">{fmtClock(ctx.conv.first_ts)}</span>
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
      return ctx.level === "M" ? <span className="font-mono text-xs text-slate-400">{fmtClock(ctx.turn.ts)}</span> : null;
    case "mdur":
      return ctx.level === "M" && ctx.role === "assistant"
        ? <span className="font-mono text-xs tabular-nums text-slate-400">{fmtMs(ctx.turn.latency_ms)}</span>
        : null;
    case "content":
      return ctx.level === "M" ? <MessageContent raw={ctx.role === "user" ? ctx.turn.input : ctx.turn.output} /> : null;
    case "musage":
      return ctx.level === "M" && ctx.role === "assistant" ? <UsageCell usage={turnUsage(ctx.turn)} /> : null;
    // S group
    case "sindex":
      return ctx.level === "S" ? <span className="font-mono text-xs tabular-nums text-slate-500">{ctx.index}</span> : null;
    case "type":
      return ctx.level === "S" ? <TypeChip type={ctx.span.type} /> : null;
    case "stime":
      return ctx.level === "S" ? <span className="font-mono text-xs text-slate-400">{fmtClock(ctx.span.start_time)}</span> : null;
    case "sdur":
      return ctx.level === "S" ? <span className="font-mono text-xs tabular-nums text-slate-400">{fmtMs(durationMs(ctx.span))}</span> : null;
    case "agent": {
      if (ctx.level !== "S") return null;
      const label = agentLabel(ctx.span);
      return label ? <AgentBadge agent={label} /> : null;
    }
    case "model":
      return ctx.level === "S" && ctx.span.model_id ? <ModelBadge model={ctx.span.model_id} /> : null;
    case "name":
      return ctx.level === "S" ? <Plain text={ctx.span.step_name || ctx.span.name || ""} /> : null;
    case "input":
      return ctx.level === "S" ? <MessageContent raw={ctx.span.input} /> : null;
    case "output":
      // THINKING is its own Type — its reasoning text lives in the span's output, shown here.
      return ctx.level === "S" ? <MessageContent raw={ctx.span.output} /> : null;
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
  // Whole-row click opens the trace (conversation → its session/trace); clicks on interactive
  // elements (chevron, pills, links, expandable text) are left alone.
  const href =
    ctx.level === "C"
      ? ctx.conv.turns > 1
        ? `/sessions/${ctx.conv.thread}`
        : `/traces/${ctx.conv.last_trace_id}`
      : `/traces/${ctx.turn.trace_id}`;
  return (
    <tr
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("button, a, input, label")) return;
        router.push(href);
      }}
      className={clsx("group cursor-pointer border-b border-l-2 border-slate-800 transition-colors hover:bg-slate-800/80", ROW_BG[depth])}
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

function SpanRows({ turn, spans, cols }: { turn: FullTurn; spans: SpanOut[]; cols: Col[] }) {
  return (
    <>
      {sortSpans(spans).map((span, i) => (
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
  open,
  onToggleTurn,
}: {
  conv: ConvNode;
  turn: FullTurn;
  turnPos: number;
  spans: SpanOut[] | "loading" | undefined;
  cols: Col[];
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
          <SpanRows turn={turn} spans={spans} cols={cols} />
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
  onToggleConv,
  onToggleTurn,
}: {
  conv: ConvNode;
  turns: FullTurn[] | "loading" | undefined;
  spansCache: Cache<SpanOut[]>;
  open: boolean;
  openTurn: Set<string>;
  cols: Col[];
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
            <TurnRows key={turn.trace_id} conv={conv} turn={turn} turnPos={i} spans={spansCache[turn.trace_id]} cols={cols} open={openTurn.has(turn.trace_id)} onToggleTurn={onToggleTurn} />
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
  const [colMenu, setColMenu] = useState(false);
  const [wide, setWide] = useWide();

  const cols = useMemo(() => COLUMNS.filter((c) => !hidden.has(c.key)), [hidden]);

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
      localStorage.setItem(PREFS_KEY, JSON.stringify({ hidden: [...hidden] }));
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
