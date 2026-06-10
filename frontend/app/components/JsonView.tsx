"use client";

import clsx from "clsx";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type SVGProps } from "react";
import { createPortal } from "react-dom";

// Lightweight JSON syntax highlighter (shared by the trace table, the timeline span panel, and the
// attributes list) — object keys, string values, numbers, and booleans/null each get a distinct
// color. Operates on already-pretty-printed text so whitespace/indentation is preserved verbatim.
export function HighlightedJson({ text }: { text: string }) {
  const out: ReactNode[] = [];
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] !== undefined && m[2] !== undefined) {
      // "key":  -> key (fuchsia) + colon (slate)
      out.push(<span key={i++} className="text-fuchsia-400">{m[1]}</span>);
      out.push(<span key={i++} className="text-slate-500">{m[2]}</span>);
    } else if (m[1] !== undefined) {
      out.push(<span key={i++} className="text-cyan-300">{m[1]}</span>); // string value
    } else if (m[3] !== undefined) {
      out.push(<span key={i++} className="text-violet-400">{m[3]}</span>); // true/false/null
    } else if (m[4] !== undefined) {
      out.push(<span key={i++} className="text-amber-300">{m[4]}</span>); // number
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

// Pretty-print any value to a highlighted string. Strings that are themselves JSON are parsed and
// re-indented; everything else is JSON.stringified. Returns null for empty/whitespace strings.
export function prettyJson(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string") {
    const t = value.trim();
    if (t === "") return null;
    if (t.startsWith("{") || t.startsWith("[")) {
      try {
        return JSON.stringify(JSON.parse(t), null, 2);
      } catch {
        return value; // not valid JSON — show as-is
      }
    }
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// ── interactive JSON viewer (pill → floating panel) ──────────────────────────────
// A collapsed pill that opens a portalled detail panel with syntax-highlighted JSON + Copy.
// Shared by the trace table cells, the timeline span panel, and the attributes list.
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
const CopyIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><rect width="14" height="14" x="8" y="8" rx="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></svg>
);

type Accent = "cyan" | "fuchsia" | "amber" | "violet";
const ACCENT_BOX: Record<Accent, string> = {
  cyan: "bg-cyan-500/15 text-cyan-400",
  fuchsia: "bg-fuchsia-500/15 text-fuchsia-400",
  amber: "bg-amber-500/15 text-amber-400",
  violet: "bg-violet-500/15 text-violet-300",
};
export function IconBox({ accent, children }: { accent: Accent; children: ReactNode }) {
  return <div className={clsx("flex h-5 w-5 shrink-0 items-center justify-center rounded", ACCENT_BOX[accent])}>{children}</div>;
}

// Floating detail panel (portal — escapes any overflow container): header + optional Copy + body.
export function FloatingPanel({
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
  const pos: CSSProperties = above
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
      <div className="fixed inset-0 z-40" onClick={(e) => { e.stopPropagation(); onClose(); }} />
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
export function Pill({
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
      <HighlightedJson text={pretty} />
    </pre>
  );
}

export function Plain({ text }: { text: string }) {
  return (
    <span className="block max-w-full truncate text-sm text-slate-300" title={text}>
      {text || "—"}
    </span>
  );
}

export function ExpandableText({ text }: { text: string }) {
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

export function JsonPill({ raw }: { raw: string }) {
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
