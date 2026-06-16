// Pure formatting / parsing / message-extraction helpers for the trace table. No React, no I/O —
// extracted from TraceTable.tsx so the tricky title/message/score logic is unit-testable in isolation.
import type { EvalScore, SpanOut } from "../../lib/api";

export type ChatMsg = { role?: string; content?: unknown; tool_calls?: unknown; finish_reason?: unknown };

// ── time / number formatting ────────────────────────────────────────────────────
export function fmtDateTime(ts?: string | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function fmtMs(ms?: number | null): string {
  if (ms == null || ms < 0) return "—";
  if (ms === 0) return "<1ms"; // sub-millisecond runs (synthetic demo spans) → don't show "—"
  if (ms < 1) return `${ms.toFixed(2)}ms`;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function durationMs(span: SpanOut): number | null {
  if (span.latency_ms != null && span.latency_ms > 0) return span.latency_ms;
  if (span.end_time && span.start_time) {
    const d = new Date(span.end_time).getTime() - new Date(span.start_time).getTime();
    return d > 0 ? d : null;
  }
  return null;
}

// ── readable-text extraction (title / message) ───────────────────────────────────
// Pull the first human-readable text out of a value that may be a string, a content-block
// array ([{type:"text",text}, {type:"image_url"}…]), a chat-message array, or a {content} object.
export function firstText(v: unknown): string {
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

export function deriveTitle(s: string | null): string {
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

// ── span helpers ─────────────────────────────────────────────────────────────────
export function sortSpans(spans: SpanOut[]): SpanOut[] {
  return [...spans].sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime());
}

// agent_id is a resolved registry UUID; the human slug is kept in metadata.
export function agentLabel(span: SpanOut): string {
  return span.metadata?.["tracely.agent.id"] || span.agent_id || "";
}

// The Agent column should reflect the nearest enclosing AGENT — so under "Agent workflow" (the
// OpenAI Agents SDK's outer wrapper) the column reads "Agent workflow", and only switches to
// "support-agent" once we enter that sub-agent's subtree. Falls back to the trace's agent_id when
// no AGENT ancestor exists.
export function nearestAgentLabel(span: SpanOut, allSpans: SpanOut[]): string {
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

export function modelColor(m: string): string {
  const s = m.toLowerCase();
  if (s.includes("gpt-4o") || s.includes("gpt-4-turbo")) return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
  if (s.includes("gpt-4")) return "bg-green-500/10 text-green-400 border-green-500/30";
  if (s.includes("gpt-3.5")) return "bg-teal-500/10 text-teal-400 border-teal-500/30";
  if (s.includes("opus")) return "bg-orange-600/10 text-orange-400 border-orange-600/30";
  if (s.includes("sonnet") || s.includes("haiku") || s.includes("claude")) return "bg-orange-500/10 text-orange-400 border-orange-500/30";
  return "bg-slate-700/40 text-slate-300 border-slate-600/40";
}

// ── chat-message normalization ───────────────────────────────────────────────────
export const MESSAGE_TYPES = new Set(["human", "ai", "system", "tool", "function", "user", "assistant", "developer"]);

export function parseMaybe(s: string | null): unknown {
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

// OpenAI messages carry `role`; LangChain/LangGraph carry `type` ("human"/"ai"/…). Normalize both.
export function msgRole(m: Record<string, unknown>): string {
  const r = String(m.role ?? m.type ?? "").toLowerCase();
  if (r === "human") return "user";
  if (r === "ai") return "assistant";
  return r;
}

export function looksLikeMessage(m: unknown): m is Record<string, unknown> {
  if (!m || typeof m !== "object") return false;
  const o = m as Record<string, unknown>;
  return "role" in o || MESSAGE_TYPES.has(String(o.type ?? "").toLowerCase());
}

// The messages inside a turn payload: the {messages:[…]} state wrapper, or a bare chat array. Returns
// null for anything else (a single message, multimodal content blocks, plain text, data) so the
// caller renders it verbatim.
export function messageList(parsed: unknown): Record<string, unknown>[] | null {
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
export function lastTurnMessage(raw: string | null, role: "user" | "assistant"): ChatMsg | null | undefined {
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
export function asRoleMessage(role: "user" | "assistant", raw: string | null): string | null {
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

// The assistant's reply text out of a value that may be a plain string, a chat-message array (take
// the last assistant/ai turn), or a {role:"assistant", content} object — the output-side mirror of
// firstText (which prefers the user turn).
export function assistantText(v: unknown): string {
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
export function toMsg(role: string, raw: string | null): { role: string; content: unknown } | null {
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
  // ASSISTANT answer identically in every view.
  if (v && typeof v === "object") {
    const text = role === "assistant" ? assistantText(v) : firstText(v);
    if (text) return { role, content: text };
  }
  return { role, content: v };
}

// ── score formatting ─────────────────────────────────────────────────────────────
export function scoreKey(s: EvalScore): string | null {
  if (s.observation_id) return `span:${s.observation_id}|${s.name}`;
  if (s.evaluation_level === "CONVERSATION") return s.session_id ? `th:${s.session_id}|${s.name}` : null;
  return s.trace_id ? `tr:${s.trace_id}|${s.name}` : null;
}

// Classification-style json results should headline their LABEL (intent, risk_level,
// trajectory_signal…), not the internal normalized score: the first short string field that
// isn't prose. Returns null when the object has no label-ish field (pure score objects).
const _PROSE_KEYS = new Set(["reason", "reasoning", "summary", "evidence", "drift_point"]);
export function jsonResultLabel(raw: string): string | null {
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    for (const [key, value] of Object.entries(parsed)) {
      if (typeof value === "string" && value && value.length <= 24 && !_PROSE_KEYS.has(key)) {
        return value;
      }
    }
  } catch {
    /* not JSON */
  }
  return null;
}

export function fmtScoreValue(s: EvalScore): string {
  if (s.data_type === "BOOLEAN") return ""; // the verdict chip says it all
  if (s.data_type === "TEXT" && s.string_value) {
    const label = jsonResultLabel(s.string_value);
    if (label) return label;
  }
  if (s.value != null) {
    // NUMERIC results, and json results' normalized score
    if (s.name.endsWith("latency_ms")) {
      return s.value < 1000 ? `${Math.round(s.value)}ms` : `${(s.value / 1000).toFixed(2)}s`;
    }
    return Number.isInteger(s.value) ? String(s.value) : s.value.toFixed(2);
  }
  if ((s.data_type === "CATEGORICAL" || s.data_type === "TEXT") && s.string_value) return s.string_value;
  return "";
}

// Pretty-print structured outputs in the detail panel (json results store the object compact).
export function fmtPanelOutput(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
