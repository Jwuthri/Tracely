"use client";

import clsx from "clsx";
import { useState } from "react";
import { HighlightedJson } from "./JsonView";

// Smart input/output renderer: chat arrays -> conversation bubbles, objects -> collapsible JSON
// (syntax-highlighted), everything else -> readable text. Replaces raw <pre> dumps so traces are
// actually legible.

type Msg = { role?: string; content?: unknown; tool_calls?: unknown };

function parse(v: string | null): unknown {
  if (v == null || v === "") return null;
  try {
    return JSON.parse(v);
  } catch {
    return v;
  }
}

// Try JSON.parse, then a best-effort fallback for Python-repr strings (e.g. the OpenAI Agents SDK
// re-injects tool results as `{'status': 'out_for_delivery', ...}` with single quotes). Returns
// null if neither succeeds, so the caller can keep rendering the original text.
function parseObjectish(s: string): unknown {
  const t = s.trim();
  if (!(t.startsWith("{") || t.startsWith("["))) return null;
  try {
    return JSON.parse(t);
  } catch {
    /* try Python repr */
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

function isChat(x: unknown): x is Msg[] {
  return (
    Array.isArray(x) &&
    x.length > 0 &&
    x.every((m) => m != null && typeof m === "object" && ("role" in m || "content" in m))
  );
}

const ROLE: Record<string, string> = {
  user: "border-signal/30 bg-signal/[0.05] text-signal",
  assistant: "border-t_llm/30 bg-t_llm/[0.06] text-t_llm",
  system: "border-line bg-ink-900 text-fg-faint",
  tool: "border-t_tool/30 bg-t_tool/[0.06] text-t_tool",
};

// A message's content: plain strings render as text; anything structured (multimodal blocks,
// tool calls, objects) renders as a clean, indented, syntax-highlighted JSON object — never a
// half-text/half-raw-JSON smush. String content that parses as JSON is treated as structured —
// tool results in conversation history are usually `"{\"status\": ...}"` strings that read better
// as a real object than as a single-line blob.
function MsgContent({ content }: { content: unknown }) {
  if (content == null || content === "") {
    return <span className="text-[12.5px] text-fg-faint">—</span>;
  }
  if (typeof content === "string") {
    const obj = parseObjectish(content);
    if (obj !== null && typeof obj === "object") {
      return (
        <pre className="mt-0.5 overflow-auto rounded-md border border-line/70 bg-ink-900 p-2.5 font-mono text-[11px] leading-relaxed text-slate-300">
          <HighlightedJson text={JSON.stringify(obj, null, 2)} />
        </pre>
      );
    }
    return <div className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-fg-muted">{content}</div>;
  }
  return (
    <pre className="mt-0.5 overflow-auto rounded-md border border-line/70 bg-ink-900 p-2.5 font-mono text-[11px] leading-relaxed text-slate-300">
      <HighlightedJson text={JSON.stringify(content, null, 2)} />
    </pre>
  );
}

// Render assistant tool_calls as compact name + args blocks (matches how the chat-message popup
// shows them on the table side). Used when the assistant's `content` is empty but tool_calls
// are present — otherwise the panel showed "—" and hid the most important signal.
function ToolCalls({ calls }: { calls: unknown }) {
  if (!Array.isArray(calls) || calls.length === 0) return null;
  return (
    <div className="mt-1 space-y-1.5">
      {(calls as Record<string, unknown>[]).map((c, i) => {
        const fn = (c.function as Record<string, unknown> | undefined) ?? {};
        const name = String(fn.name ?? c.name ?? "");
        const argsRaw = String(fn.arguments ?? "");
        let args: unknown = argsRaw;
        try {
          args = JSON.parse(argsRaw);
        } catch {
          /* keep as raw */
        }
        const body = typeof args === "object" ? JSON.stringify(args, null, 2) : String(args);
        return (
          <div key={i} className="rounded-md border border-line/60 bg-ink-900 p-2">
            <div className="font-mono text-[10.5px] uppercase tracking-wider text-t_tool">
              <span className="opacity-70">→ </span>{name}
            </div>
            {body && body !== '""' && (
              <pre className="mt-1 overflow-auto font-mono text-[11px] leading-relaxed text-slate-300">
                <HighlightedJson text={body} />
              </pre>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function IO({ value, label }: { value: string | null; label?: string }) {
  const parsed = parse(value);
  if (parsed == null) {
    return label ? null : <div className="px-4 py-6 text-center text-[12px] text-fg-faint">(empty)</div>;
  }
  const content = isChat(parsed) ? (
    <Conversation msgs={parsed} />
  ) : typeof parsed === "object" ? (
    <Json data={parsed} />
  ) : (
    <Text text={String(parsed)} />
  );
  if (!label) return <div className="px-4 py-3">{content}</div>;
  return (
    <div className="border-t border-line px-4 py-3">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-fg-faint">{label}</div>
      {content}
    </div>
  );
}

function Conversation({ msgs }: { msgs: Msg[] }) {
  return (
    <div className="space-y-2">
      {msgs.map((m, i) => {
        const hasContent = m.content != null && m.content !== "";
        const hasToolCalls = Array.isArray(m.tool_calls) && m.tool_calls.length > 0;
        return (
          <div key={i} className={clsx("rounded-lg border px-3 py-2", ROLE[String(m.role)] ?? "border-line bg-ink-900")}>
            <div className="mb-1 font-mono text-[9.5px] uppercase tracking-wider opacity-80">{m.role ?? "message"}</div>
            {/* When the assistant only emitted tool calls (no content), show the calls instead of a bare "—". */}
            {hasContent ? <MsgContent content={m.content} /> : (!hasToolCalls && <MsgContent content={null} />)}
            {hasToolCalls && <ToolCalls calls={m.tool_calls} />}
          </div>
        );
      })}
    </div>
  );
}

function Text({ text }: { text: string }) {
  return (
    <div className="whitespace-pre-wrap rounded-lg border border-line bg-ink-900 p-3 text-[12.5px] leading-relaxed text-fg-muted">
      {text}
    </div>
  );
}

function Json({ data }: { data: unknown }) {
  const body = JSON.stringify(data, null, 2);
  const big = body.length > 600;
  // Always expanded by default — collapsing big payloads on first render hid the output behind an
  // extra click. The toggle stays available so genuinely huge blobs can still be collapsed.
  const [open, setOpen] = useState(true);
  return (
    <div>
      <pre
        className={clsx(
          "overflow-auto rounded-lg border border-line bg-ink-900 p-3 font-mono text-[11.5px] leading-relaxed text-slate-300",
          open ? "max-h-80" : "max-h-20",
        )}
      >
        <HighlightedJson text={body} />
      </pre>
      {big && (
        <button onClick={() => setOpen((o) => !o)} className="mt-1.5 font-mono text-[11px] text-signal hover:underline">
          {open ? "collapse" : "expand"}
        </button>
      )}
    </div>
  );
}
