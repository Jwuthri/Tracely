"use client";

import clsx from "clsx";
import { useState } from "react";
import { HighlightedJson } from "./JsonView";

// Smart input/output renderer: chat arrays -> conversation bubbles, objects -> collapsible JSON
// (syntax-highlighted), everything else -> readable text. Replaces raw <pre> dumps so traces are
// actually legible.

type Msg = { role?: string; content?: unknown };

function parse(v: string | null): unknown {
  if (v == null || v === "") return null;
  try {
    return JSON.parse(v);
  } catch {
    return v;
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

function asText(c: unknown): string {
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    return c
      .map((p) => (typeof p === "string" ? p : (p?.text ?? JSON.stringify(p))))
      .join("\n");
  }
  return JSON.stringify(c, null, 2);
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
      {msgs.map((m, i) => (
        <div key={i} className={clsx("rounded-lg border px-3 py-2", ROLE[String(m.role)] ?? "border-line bg-ink-900")}>
          <div className="mb-1 font-mono text-[9.5px] uppercase tracking-wider opacity-80">{m.role ?? "message"}</div>
          <div className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-fg-muted">{asText(m.content)}</div>
        </div>
      ))}
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
  const [open, setOpen] = useState(!big);
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
