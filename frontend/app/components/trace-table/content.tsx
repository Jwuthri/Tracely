"use client";

/* How a payload becomes something readable: chat transcripts, multimodal blocks, tool calls,
   state writes, and the badges that label them.

   This is the part of the trace table that knows about PROVIDER SHAPES rather than about tables —
   an Anthropic content block, an OpenAI `tool_calls` array and an OpenLLMetry legacy string all
   arrive here and have to come out looking like the same conversation. It touches none of the
   table's state (no contexts, no fetching), which is why it lives on its own: the shapes are
   where the bugs are, and here they can be tested without mounting a grid.

   Extracted verbatim from TraceTable.tsx — behaviour unchanged. */

import clsx from "clsx";
import { useMemo, useState } from "react";
import type { SpanOut } from "../../lib/api";
import { ExpandableText, FloatingPanel, HighlightedJson, IconBox, JsonPill, Pill, Plain, prettyJson } from "../JsonView";
import { ChatGlyph, ExternalLink, FileIcon, ImageIcon, TextGlyph } from "./icons";
import { spanStateWrites } from "../state-fold";
import {
  asRoleMessage,
  assistantText,
  type ChatMsg,
  firstText,
  fmtPanelOutput,
  imageSrc,
  jsonResultLabel,
  lastTurnMessage,
  messageList,
  modelColor,
  msgRole,
  parseMaybe,
  toMsg,
} from "./format";

const HJson = HighlightedJson;

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
export function classifyBlock(b: unknown): Part {
  if (typeof b === "string") return { kind: "text", text: b };
  if (b && typeof b === "object") {
    const o = b as Record<string, unknown>;
    const type = String(o.type ?? "").toLowerCase();
    const src = (o.source ?? {}) as Record<string, unknown>;
    if (type.includes("image") || o.image_url || o.image || src.media_type || (src.type === "base64")) {
      const url = imageSrc(b);
      // No src we can render (unknown provider shape, non-http scheme) — show the raw block rather
      // than a mute "image" chip that hides what actually arrived.
      if (!url) return { kind: "json", data: b };
      return { kind: "image", url, label: (src.media_type as string) ?? (o.mime_type as string) ?? "image" };
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

// A compact attachment chip. Deliberately lightweight — it shows an icon + name and NEVER loads
// the full image inline (a table can hold many of these). When the block carries a url/path the
// chip is a link that opens the image/document in a new tab.
function Attachment({ part }: { part: Exclude<Part, { kind: "text" }> }) {
  const [broken, setBroken] = useState(false);
  if (part.kind === "json") return <JsonPill raw={JSON.stringify(part.data)} />;
  const isImg = part.kind === "image";
  const url = part.url;
  // ponytail: a plain <img> thumbnail — no lightbox, click opens the full image in a tab. If the
  // fetch fails (expired signed URL, hotlink block) we fall through to the link chip below.
  if (isImg && url && !broken) {
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} title={`Open ${part.label}`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt={part.label}
          onError={() => setBroken(true)}
          className="max-h-24 max-w-[200px] rounded-md border border-line object-contain"
        />
      </a>
    );
  }
  const icon = isImg ? (
    <ImageIcon className="h-3.5 w-3.5 shrink-0 text-syn-key" />
  ) : (
    <FileIcon className="h-3.5 w-3.5 shrink-0 text-info" />
  );
  const base =
    "inline-flex max-w-[200px] items-center gap-1.5 rounded-md border border-line bg-ink-700/60 px-2 py-1 text-[11px] text-fg";
  if (url && /^(https?:|data:)/.test(url)) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        title={`Open ${part.label}`}
        className={clsx(base, "transition-colors hover:border-line-bright hover:bg-ink-600/70 hover:text-fg")}
      >
        {icon}
        <span className="truncate">{part.label}</span>
        <ExternalLink className="h-3 w-3 shrink-0 text-fg-faint" />
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
  if (value == null || value === "") return <span className="text-fg-faint">—</span>;
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
  user: "bg-info/10 text-info border-info/30",
  assistant: "bg-ok/10 text-ok border-ok/30",
  system: "bg-line-bright/25 text-fg border-line-bright/40",
  tool: "bg-t_tool/10 text-t_tool border-t_tool/30",
  thinking: "bg-t_think/10 text-t_think border-t_think/30",
};
function RoleTag({ role }: { role?: string }) {
  const r = (role || "msg").toLowerCase();
  return (
    <span className={clsx("inline-block shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider", ROLE_CHIP[r] ?? "bg-line-bright/25 text-fg border-line-bright/40")}>
      {r}
    </span>
  );
}
// Full (un-clamped) content for the conversation popover: text wraps, attachments as chips, data as JSON.
function ContentBody({ value }: { value: unknown }) {
  if (value == null || value === "") return <span className="text-fg-faint">—</span>;
  if (typeof value === "string") {
    const s = value.trim();
    if (/^https?:\/\/\S+$/.test(s)) {
      return (
        <a href={s} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="break-all text-[12px] leading-relaxed text-signal underline decoration-signal/40 underline-offset-2 hover:decoration-signal">
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
          <pre className="whitespace-pre-wrap break-words rounded-md border border-line/60 bg-ink-900/50 p-2 font-mono text-[11px] leading-relaxed text-fg">
            <HJson text={pretty} />
          </pre>
        );
      }
    }
    return <div className="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-fg">{value}</div>;
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
        {text && <div className="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-fg">{text}</div>}
        {media.length > 0 && <div className="flex flex-wrap gap-1.5">{media.map((m, i) => <Attachment key={i} part={m} />)}</div>}
      </div>
    );
  }
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-fg">
      <HJson text={JSON.stringify(value, null, 2)} />
    </pre>
  );
}


// A model's tool/function calls (function calling) — name + parsed arguments.
function ToolCalls({ calls }: { calls: unknown[] }) {
  return (
    <div className="mt-2 space-y-1.5">
      <div className="text-[9.5px] uppercase tracking-wider text-fg-faint">Tool calls</div>
      {calls.map((raw, i) => {
        const c = (raw ?? {}) as Record<string, unknown>;
        const fn = (c.function ?? c) as Record<string, unknown>;
        const name = String(fn.name ?? c.name ?? "tool");
        let args: unknown = fn.arguments ?? c.arguments ?? c.args;
        if (typeof args === "string") {
          try { args = JSON.parse(args); } catch { /* keep string */ }
        }
        return (
          <div key={i} className="rounded-md border border-line/60 bg-ink-900/50 p-2">
            <div className="flex items-center gap-1.5 font-mono text-[11.5px] font-medium text-t_think">
              <span className="text-[10px]">⛭</span>
              {name}
            </div>
            {args != null && args !== "" && (
              <pre className="mt-1 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-fg">
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
    <div className="rounded-lg border border-line/60 bg-ink-700/40 p-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <RoleTag role={m.role} />
        {finish && (
          <span className="rounded bg-ink-600/50 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-fg-muted">{finish}</span>
        )}
      </div>
      {hasContent && <ContentBody value={m.content} />}
      {calls.length > 0 && <ToolCalls calls={calls} />}
      {!hasContent && calls.length === 0 && <span className="text-fg-faint">—</span>}
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
          <span className="uppercase text-fg-muted">{(last.role || "msg").toString()}</span>
          {preview && <span className="truncate text-fg-faint">{preview}</span>}
        </span>
      }
      badge={<span className="rounded bg-ink-600/60 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-fg-muted">{n}</span>}
      panel={(a, c) => (
        <FloatingPanel anchor={a} onClose={c} icon={icon} title="conversation" subtitle={`${n} message${n === 1 ? "" : "s"}`} copyText={JSON.stringify(msgs, null, 2)}>
          <ChatBody msgs={msgs} />
        </FloatingPanel>
      )}
    />
  );
}

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
      summary={<span className="truncate text-fg/90">{preview}</span>}
      panel={(a, c) => (
        <FloatingPanel anchor={a} onClose={c} icon={icon} title="text" subtitle={`${text.length} chars`} copyText={text}>
          <div className="max-w-full whitespace-pre-wrap break-words p-3 text-[12px] leading-relaxed text-fg">{text}</div>
        </FloatingPanel>
      )}
    />
  );
}

// The universal renderer used for every message/step input & output, so the same
// content reads the same way at any level (and attachments/multi-part work everywhere).
export function MessageContent({ raw }: { raw: string | null }) {
  if (raw == null || raw === "") return <span className="text-fg-faint">—</span>;
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
export function TurnMessage({ raw, role }: { raw: string | null; role: "user" | "assistant" }) {
  const msg = useMemo(() => lastTurnMessage(raw, role), [raw, role]);
  if (msg === undefined) return <MessageContent raw={asRoleMessage(role, raw)} />;
  if (msg === null) return <span className="text-fg-faint">—</span>;
  const calls = Array.isArray(msg.tool_calls) ? msg.tool_calls : [];
  if (calls.length > 0) return <ChatPill msgs={[msg]} />; // assistant tool call(s) → keep them visible
  const c = msg.content;
  if (c == null || c === "" || (Array.isArray(c) && c.length === 0)) return <span className="text-fg-faint">—</span>;
  // Render as a chat pill with the role badge — symmetric across user/assistant. Multimodal content
  // (URLs/base64 attachments) survives as the pill's content array and renders in the popover.
  return <ChatPill msgs={[msg]} />;
}

// ── badges ──────────────────────────────────────────────────────────────────────
export function RoleBadge({ role }: { role: "user" | "assistant" }) {
  const cls = role === "user" ? "bg-info/10 text-info border-info/30" : "bg-ok/10 text-ok border-ok/30";
  const dot = role === "user" ? "bg-info" : "bg-ok";
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-semibold uppercase", cls)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", dot)} />
      {role}
    </span>
  );
}

export function AgentBadge({ agent }: { agent: string }) {
  return (
    <span className="inline-flex max-w-full items-center truncate rounded border border-t_agent/30 bg-t_agent/10 px-2 py-0.5 text-[11px] font-medium text-t_agent" title={agent}>
      {agent}
    </span>
  );
}

// What this row wrote to the shared state object, as the object itself — rendered by the same
// JsonPill the Input/Output columns use, so it previews inline and expands to the full JSON.
export function StateCell({ writes }: { writes: Record<string, unknown> | null }) {
  if (!writes) return <span className="text-fg-faint">—</span>;
  return <JsonPill raw={JSON.stringify(writes)} />;
}

// The row's writes merged into one delta object; later spans win, so an M row shows the turn's
// net change rather than each step's intermediate value.
export function stateWritesOf(spans: SpanOut[]): Record<string, unknown> | null {
  const merged: Record<string, unknown> = {};
  for (const s of spans) Object.assign(merged, spanStateWrites(s) ?? {});
  return Object.keys(merged).length > 0 ? merged : null;
}

export function ModelBadge({ model }: { model: string }) {
  return (
    <span className={clsx("inline-flex max-w-full items-center truncate rounded border px-2 py-0.5 text-[11px] font-medium", modelColor(model))} title={model}>
      {model}
    </span>
  );
}
