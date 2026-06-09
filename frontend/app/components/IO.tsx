"use client";

import clsx from "clsx";
import { useState, type ReactNode } from "react";
import { HighlightedJson } from "./JsonView";

// Smart input/output renderer for the timeline span panel. Turns a span's raw input/output — the
// OpenAI / Anthropic request & response envelopes, tool args/results, framework state, or plain
// text — into a *well-formatted, structured* view: chat turns render as role-tagged message cards,
// and data objects render as an indented key→value tree (never a raw JSON wall). A per-panel
// toggle flips to the exact raw JSON (with Copy) when that's what you actually want.

// ── parsing ──────────────────────────────────────────────────────────────────────
function parse(v: string | null): unknown {
  if (v == null || v === "") return null;
  try {
    return JSON.parse(v);
  } catch {
    return v;
  }
}

// JSON.parse, then a best-effort fallback for Python-repr strings (the OpenAI Agents SDK re-injects
// tool results as `{'status': 'out_for_delivery', ...}` with single quotes). null if neither works,
// so the caller keeps the original text.
function parseObjectish(s: string): unknown {
  const t = s.trim();
  if (!(t.startsWith("{") || t.startsWith("["))) return null;
  try {
    return JSON.parse(t);
  } catch {
    /* try python-repr */
  }
  const swapped = t
    .replace(/'/g, '"')
    .replace(/: None\b/g, ": null")
    .replace(/: True\b/g, ": true")
    .replace(/: False\b/g, ": false");
  try {
    return JSON.parse(swapped);
  } catch {
    return null;
  }
}

const isScalar = (v: unknown): boolean => v == null || (typeof v !== "object");

// ── message detection / normalization ────────────────────────────────────────────
type Msg = { role?: string; content?: unknown; tool_calls?: unknown; finish_reason?: unknown };

// OpenAI carries `role`; LangChain/LangGraph carry `type` ("human"/"ai"/…). Treat either as a turn.
const MSG_TYPES = new Set(["human", "ai", "system", "tool", "function", "user", "assistant", "developer"]);
function looksLikeMsg(m: unknown): m is Record<string, unknown> {
  if (!m || typeof m !== "object" || Array.isArray(m)) return false;
  const o = m as Record<string, unknown>;
  return "role" in o || MSG_TYPES.has(String(o.type ?? "").toLowerCase());
}
function isChatArray(x: unknown): x is Msg[] {
  return Array.isArray(x) && x.length > 0 && x.every(looksLikeMsg);
}
function msgRole(m: Msg): string {
  const r = String((m as Record<string, unknown>).role ?? (m as Record<string, unknown>).type ?? "").toLowerCase();
  if (r === "human") return "user";
  if (r === "ai") return "assistant";
  return r || "message";
}
// Normalize OpenAI `tool_calls:[{function:{name,arguments}}]` and Anthropic `tool_use` content
// blocks into a flat {name, args} list, with stringified JSON arguments parsed.
function collectToolCalls(m: Msg): Array<{ name: string; args: unknown }> {
  const out: Array<{ name: string; args: unknown }> = [];
  if (Array.isArray(m.tool_calls)) {
    for (const raw of m.tool_calls) {
      const c = (raw ?? {}) as Record<string, unknown>;
      const fn = (c.function ?? c) as Record<string, unknown>;
      let args: unknown = fn.arguments ?? c.arguments ?? c.args ?? c.input;
      if (typeof args === "string") {
        try {
          args = JSON.parse(args);
        } catch {
          /* keep string */
        }
      }
      out.push({ name: String(fn.name ?? c.name ?? "tool"), args });
    }
  }
  if (Array.isArray(m.content)) {
    for (const b of m.content as Record<string, unknown>[]) {
      if (b && typeof b === "object" && String(b.type).toLowerCase() === "tool_use") {
        out.push({ name: String(b.name ?? "tool"), args: b.input });
      }
    }
  }
  return out;
}

// ── primitives ───────────────────────────────────────────────────────────────────
const Chevron = ({ open }: { open: boolean }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={clsx("h-3 w-3 shrink-0 text-slate-500 transition-transform", open && "rotate-90")}
  >
    <path d="m9 18 6-6-6-6" />
  </svg>
);

const Key = ({ name, idx }: { name: string; idx?: boolean }) => (
  <span className={clsx("font-mono", idx ? "text-slate-500" : "text-fuchsia-400")}>{name}</span>
);

// A scalar leaf, colored to match the JSON highlighter (string=cyan, number=amber, bool/null=violet).
function Scalar({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="font-mono text-violet-400">null</span>;
  if (typeof value === "number") return <span className="font-mono text-amber-300">{String(value)}</span>;
  if (typeof value === "boolean") return <span className="font-mono text-violet-400">{String(value)}</span>;
  return <InlineStr text={String(value)} />;
}

// A data string value: quoted (JSON-like), with long/multiline values clamped behind a toggle.
function InlineStr({ text }: { text: string }) {
  const s = text.trim();
  if (/^https?:\/\/\S+$/.test(s)) {
    return (
      <a href={s} target="_blank" rel="noopener noreferrer" className="break-all font-mono text-cyan-400 underline decoration-cyan-400/40 underline-offset-2 hover:decoration-cyan-400">
        {s}
      </a>
    );
  }
  const long = text.length > 140 || text.includes("\n");
  const [open, setOpen] = useState(false);
  if (!long) return <span className="break-words font-mono text-cyan-300">&quot;{text}&quot;</span>;
  return (
    <button onClick={() => setOpen((o) => !o)} className="group inline-flex max-w-full items-start gap-1 text-left align-top">
      <Chevron open={open} />
      <span className={clsx("break-words font-mono text-cyan-300", open ? "whitespace-pre-wrap" : "line-clamp-2")}>&quot;{text}&quot;</span>
    </button>
  );
}

// Message text (prose, unquoted) — wraps; long text clamps behind a toggle. URLs become links.
function BlockStr({ text }: { text: string }) {
  const s = text.trim();
  if (/^https?:\/\/\S+$/.test(s)) {
    return (
      <a href={s} target="_blank" rel="noopener noreferrer" className="break-all text-[12.5px] text-cyan-400 underline decoration-cyan-400/40 underline-offset-2 hover:decoration-cyan-400">
        {s}
      </a>
    );
  }
  const long = text.length > 280 || text.split("\n").length > 6;
  const [open, setOpen] = useState(false);
  if (!long) return <div className="whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-fg-muted">{text}</div>;
  return (
    <div>
      <div className={clsx("whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-fg-muted", !open && "line-clamp-4")}>{text}</div>
      <button onClick={() => setOpen((o) => !o)} className="mt-0.5 font-mono text-[11px] text-signal hover:underline">
        {open ? "show less" : "show more"}
      </button>
    </div>
  );
}

// ── the object/array tree (the "well-formatted object") ──────────────────────────
function ObjectView({ data, depth = 0 }: { data: Record<string, unknown>; depth?: number }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <span className="font-mono text-slate-500">{"{ }"}</span>;
  return (
    <div className="space-y-1">
      {entries.map(([k, v]) => (
        <FieldRow key={k} name={k} value={v} depth={depth} />
      ))}
    </div>
  );
}

function ArrayView({ items, depth = 0 }: { items: unknown[]; depth?: number }) {
  if (items.length === 0) return <span className="font-mono text-slate-500">[ ]</span>;
  // an array of scalars renders as a compact inline list rather than one row per index
  if (items.every(isScalar)) {
    return (
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        {items.map((v, i) => (
          <span key={i} className="flex items-baseline">
            <Scalar value={v} />
            {i < items.length - 1 && <span className="text-slate-600">,</span>}
          </span>
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-1">
      {items.map((v, i) => (
        <FieldRow key={i} name={String(i)} value={v} depth={depth} idx />
      ))}
    </div>
  );
}

// One key→value row. Scalars render inline (`key: value`); containers get a collapse toggle and an
// indented nested block. A value that is itself a chat array renders as a conversation in place.
function FieldRow({ name, value, depth, idx }: { name: string; value: unknown; depth: number; idx?: boolean }) {
  if (isScalar(value)) {
    return (
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="shrink-0">
          <Key name={name} idx={idx} />
          <span className="text-slate-500">:</span>
        </span>
        <Scalar value={value} />
      </div>
    );
  }
  const isArr = Array.isArray(value);
  if (isArr && isChatArray(value)) {
    return (
      <div>
        <div className="mb-1">
          <Key name={name} idx={idx} />
          <span className="text-slate-500">:</span>
        </div>
        <div className="ml-1.5 border-l border-line/60 pl-3">
          <Conversation msgs={value as Msg[]} />
        </div>
      </div>
    );
  }
  const count = isArr ? (value as unknown[]).length : Object.keys(value as object).length;
  const heavy = count > 8 || JSON.stringify(value).length > 360;
  const [open, setOpen] = useState(!heavy && depth < 3);
  return (
    <div>
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 text-left">
        <Chevron open={open} />
        <Key name={name} idx={idx} />
        <span className="text-slate-500">:</span>
        <span className="font-mono text-[10px] text-slate-500">{isArr ? `[${count}]` : `{${count}}`}</span>
      </button>
      {open && (
        <div className="ml-1.5 mt-1 border-l border-line/60 pl-3">
          {isArr ? <ArrayView items={value as unknown[]} depth={depth + 1} /> : <ObjectView data={value as Record<string, unknown>} depth={depth + 1} />}
        </div>
      )}
    </div>
  );
}

// An object/array value wrapped in a subtle card — used for message content and tool args/results,
// so structured data reads as a formatted object rather than escaped braces.
function ValueBlock({ value }: { value: unknown }) {
  if (value && typeof value === "object") {
    return (
      <div className="mt-0.5 rounded-md border border-line/70 bg-ink-900/60 p-2 text-[11.5px]">
        {Array.isArray(value) ? <ArrayView items={value} /> : <ObjectView data={value as Record<string, unknown>} />}
      </div>
    );
  }
  return <Scalar value={value} />;
}

// ── chat / messages ──────────────────────────────────────────────────────────────
const ROLE: Record<string, string> = {
  user: "border-signal/30 bg-signal/[0.05] text-signal",
  assistant: "border-t_llm/30 bg-t_llm/[0.06] text-t_llm",
  system: "border-line bg-ink-900 text-fg-faint",
  tool: "border-t_tool/30 bg-t_tool/[0.06] text-t_tool",
  thinking: "border-violet-500/30 bg-violet-500/[0.06] text-violet-300",
};

function Conversation({ msgs }: { msgs: Msg[] }) {
  return (
    <div className="space-y-2">
      {msgs.map((m, i) => (
        <MessageCard key={i} m={m} />
      ))}
    </div>
  );
}

function MessageCard({ m }: { m: Msg }) {
  const role = msgRole(m);
  const calls = collectToolCalls(m);
  const finish = typeof m.finish_reason === "string" ? m.finish_reason : null;
  const hasContent = m.content != null && m.content !== "" && !(Array.isArray(m.content) && m.content.length === 0);
  return (
    <div className={clsx("rounded-lg border px-3 py-2", ROLE[role] ?? "border-line bg-ink-900")}>
      <div className="mb-1 flex items-center gap-2">
        <span className="font-mono text-[9.5px] uppercase tracking-wider opacity-80">{role}</span>
        {finish && <span className="rounded bg-slate-700/40 px-1 py-0.5 font-mono text-[8.5px] uppercase tracking-wider text-slate-400">{finish}</span>}
      </div>
      {hasContent && <MsgContent content={m.content} />}
      {calls.length > 0 && <ToolCalls calls={calls} />}
      {!hasContent && calls.length === 0 && <span className="text-[12.5px] text-fg-faint">—</span>}
    </div>
  );
}

// A message's content: plain text renders as prose; a JSON-encoded string or object renders as a
// formatted object; an array renders its multimodal parts (text + image/file/tool blocks).
function MsgContent({ content }: { content: unknown }) {
  if (content == null || content === "") return <span className="text-[12.5px] text-fg-faint">—</span>;
  if (typeof content === "string") {
    const obj = parseObjectish(content);
    if (obj !== null && typeof obj === "object") return <ValueBlock value={obj} />;
    return <BlockStr text={content} />;
  }
  if (Array.isArray(content)) return <ContentBlocks blocks={content} />;
  return <ValueBlock value={content} />;
}

function MediaChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-ink-900 px-2 py-1 text-[11px] text-fg-muted">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5 text-fuchsia-400">
        <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
        <circle cx="9" cy="9" r="2" />
        <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
      </svg>
      {label}
    </span>
  );
}

// Multimodal content parts: text blocks as prose, image blocks as a chip; tool_use blocks are
// surfaced by the card's ToolCalls (skipped here); anything else as a formatted object.
function ContentBlocks({ blocks }: { blocks: unknown[] }) {
  const out: ReactNode[] = [];
  blocks.forEach((b, i) => {
    if (typeof b === "string") {
      out.push(<BlockStr key={i} text={b} />);
      return;
    }
    if (b && typeof b === "object") {
      const o = b as Record<string, unknown>;
      const type = String(o.type ?? "").toLowerCase();
      if (type === "tool_use") return; // rendered as a tool call on the card
      if (type.includes("text") || typeof o.text === "string") {
        out.push(<BlockStr key={i} text={String(o.text ?? o.content ?? "")} />);
        return;
      }
      if (type.includes("image") || o.image_url || o.image || (o.source as Record<string, unknown> | undefined)?.media_type) {
        out.push(<MediaChip key={i} label={type.includes("image") ? "image" : "media"} />);
        return;
      }
      out.push(<ValueBlock key={i} value={o} />);
    }
  });
  if (out.length === 0) return null;
  return <div className="space-y-1.5">{out}</div>;
}

// A model's tool/function calls — name + parsed arguments as a formatted object.
function ToolCalls({ calls }: { calls: Array<{ name: string; args: unknown }> }) {
  return (
    <div className="mt-1.5 space-y-1.5">
      {calls.map((c, i) => (
        <div key={i} className="rounded-md border border-line/60 bg-ink-900 p-2">
          <div className="font-mono text-[10.5px] uppercase tracking-wider text-t_tool">
            <span className="opacity-70">→ </span>
            {c.name}
          </div>
          {c.args != null && c.args !== "" && <div className="mt-1"><ValueBlock value={c.args} /></div>}
        </div>
      ))}
    </div>
  );
}

// A collapsed footer for the secondary envelope fields (request params / response metadata) so the
// messages stay the focus but model/tools/usage/id remain one click away.
function Details({ title, rest }: { title: string; rest: Record<string, unknown> }) {
  const entries = Object.entries(rest).filter(([, v]) => v != null && !(Array.isArray(v) && v.length === 0));
  const [open, setOpen] = useState(false);
  if (entries.length === 0) return null;
  return (
    <div className="rounded-md border border-line/60 bg-ink-900/40">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-fg-faint hover:text-fg-muted">
        <Chevron open={open} />
        {title} details
        <span className="text-slate-600">{entries.length}</span>
      </button>
      {open && (
        <div className="border-t border-line/60 px-2.5 py-2">
          <ObjectView data={Object.fromEntries(entries)} />
        </div>
      )}
    </div>
  );
}

// ── top-level shape detection ─────────────────────────────────────────────────────
function TopLevel({ value }: { value: unknown }) {
  if (isChatArray(value)) return <Conversation msgs={value} />;
  if (Array.isArray(value)) return <ValueBlock value={value} />;
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    // OpenAI request envelope: {messages:[…], model?, tools?, temperature?, …}
    if (isChatArray(o.messages)) {
      const { messages, ...rest } = o;
      return (
        <div className="space-y-3">
          <Conversation msgs={messages as Msg[]} />
          <Details title="request" rest={rest} />
        </div>
      );
    }
    // OpenAI response envelope: {choices:[{message, finish_reason}], id, model, usage, …}
    if (Array.isArray(o.choices) && o.choices.some((c) => c && typeof c === "object" && "message" in (c as object))) {
      const msgs = (o.choices as Record<string, unknown>[]).map((c) => ({
        ...((c.message ?? {}) as Msg),
        finish_reason: c.finish_reason,
      }));
      const { choices, ...rest } = o;
      return (
        <div className="space-y-3">
          <Conversation msgs={msgs} />
          <Details title="response" rest={rest} />
        </div>
      );
    }
    // A single message object {role, content, …} (e.g. an Anthropic response) — show it as a turn,
    // with any envelope fields (model/usage/stop_reason) tucked into details.
    if ("role" in o) {
      const { role, content, tool_calls, finish_reason, ...rest } = o;
      return (
        <div className="space-y-3">
          <Conversation msgs={[{ role, content, tool_calls, finish_reason } as Msg]} />
          <Details title="message" rest={rest} />
        </div>
      );
    }
    // generic structured data (tool args/results, framework state)
    return <ValueBlock value={o} />;
  }
  return <BlockStr text={String(value)} />;
}

function RawJson({ value }: { value: unknown }) {
  return (
    <pre className="overflow-auto rounded-lg border border-line bg-ink-900 p-3 font-mono text-[11.5px] leading-relaxed text-slate-300">
      <HighlightedJson text={JSON.stringify(value, null, 2)} />
    </pre>
  );
}

function Toolbar({ raw, onToggle, copyText }: { raw: boolean; onToggle: () => void; copyText: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* ignore */
    }
  }
  const seg = (label: string, active: boolean) =>
    clsx("px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors", active ? "bg-signal/15 text-signal" : "text-fg-faint hover:text-fg-muted");
  return (
    <div className="flex items-center justify-between">
      <div className="inline-flex overflow-hidden rounded-md border border-line">
        <button onClick={() => raw && onToggle()} className={seg("formatted", !raw)}>formatted</button>
        <button onClick={() => !raw && onToggle()} className={clsx(seg("raw", raw), "border-l border-line")}>raw</button>
      </div>
      <button onClick={copy} className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-fg-faint transition-colors hover:text-fg-muted">
        {copied ? "copied" : "copy"}
      </button>
    </div>
  );
}

export function IO({ value }: { value: string | null; label?: string }) {
  const [raw, setRaw] = useState(false);
  const parsed = parse(value);
  if (parsed == null) {
    return <div className="px-4 py-6 text-center text-[12px] text-fg-faint">(empty)</div>;
  }
  const copyText = typeof value === "string" ? value : JSON.stringify(parsed, null, 2);
  return (
    <div className="px-4 py-3">
      <Toolbar raw={raw} onToggle={() => setRaw((r) => !r)} copyText={copyText} />
      <div className="mt-2 max-h-[30rem] overflow-auto">{raw ? <RawJson value={parsed} /> : <TopLevel value={parsed} />}</div>
    </div>
  );
}
