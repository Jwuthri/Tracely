"use client";

import type { EvalScore } from "./api";

// ── Evaluator (= evaluation column) client API ─────────────────────────────────
// Browser-side helpers over the Next proxy routes (/api/evaluators*, /api/evaluations/run).
// Server components use lib/api.ts; client components (the table, the Add Column modal) use these.

export type EvaluatorLevel = "CONVERSATION" | "AGENT_RUN" | "SPAN" | "TOOL" | "GENERATION" | "CHAIN";

export type EvaluatorOutputType = "score" | "number" | "boolean" | "text" | "json" | "category";

export type EvaluatorConfig = {
  prompt?: string;
  threshold?: number;
  output_type?: EvaluatorOutputType; // "category" is legacy — superseded by json + enum schemas
  output_schema?: Record<string, unknown>; // JSON Schema, for output_type "json"
  execution_mode?: "batch" | "sequential"; // sequential = chain items of this metric
  categories?: string[]; // legacy (category output type)
  fail_categories?: string[]; // legacy
  model?: string;
  span_types?: string[];
  check?: string; // structural evaluators
  params?: Record<string, unknown>;
};

export type JudgeModelOption = { id: string; label: string };
export type JudgeModels = { default: string; models: JudgeModelOption[] };

export type EvaluatorDef = {
  id: string;
  name: string;
  description: string;
  kind: "structural" | "llm_judge";
  score_name: string;
  level: EvaluatorLevel;
  enabled: boolean;
  target_agent?: string;
  target_env?: string;
  sampling?: number;
  config: EvaluatorConfig;
  created_at?: string | null;
};

export type EvaluatorTemplate = {
  name: string;
  description: string;
  kind: "structural" | "llm_judge";
  score_name: string;
  level: EvaluatorLevel;
  config: EvaluatorConfig;
  recommended?: boolean;
  category?: string;
  installed: boolean;
};

export type EvaluatorDraft = {
  name: string;
  description: string;
  kind: "structural" | "llm_judge";
  level: EvaluatorLevel;
  config: EvaluatorConfig;
  score_name?: string;
};

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function listEvaluators(): Promise<EvaluatorDef[]> {
  const res = await fetch("/api/evaluators", { cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function createEvaluator(draft: EvaluatorDraft & { enabled?: boolean }): Promise<EvaluatorDef> {
  return jsonOrThrow(await fetch("/api/evaluators", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(draft),
  }));
}

export async function updateEvaluator(
  id: string,
  patch: Partial<Pick<EvaluatorDef, "name" | "description" | "level" | "enabled" | "config">>,
): Promise<EvaluatorDef> {
  return jsonOrThrow(await fetch(`/api/evaluators/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  }));
}

export async function deleteEvaluator(id: string): Promise<void> {
  await jsonOrThrow(await fetch(`/api/evaluators/${encodeURIComponent(id)}`, { method: "DELETE" }));
}

export async function listTemplates(): Promise<EvaluatorTemplate[]> {
  const res = await fetch("/api/evaluators/templates", { cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function listJudgeModels(): Promise<JudgeModels> {
  const res = await fetch("/api/evaluators/models", { cache: "no-store" });
  if (!res.ok) return { default: "", models: [] };
  return res.json();
}

export async function generateEvaluator(description: string): Promise<EvaluatorDraft> {
  return jsonOrThrow(await fetch("/api/evaluators/generate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ description }),
  }));
}

// ── Streaming runs ──────────────────────────────────────────────────────────────

export type RunScope = { evaluator_ids?: string[]; thread_ids?: string[]; trace_ids?: string[] };

export type RunEvent =
  | { type: "start"; targets: number; evaluators: number }
  | { type: "result"; score: EvalScore }
  | { type: "target_done"; target: string; scores: number }
  | { type: "target_error"; target: string; detail: string }
  | { type: "error"; detail: string }
  | { type: "done" };

// POST the run and decode the SSE frames (`data: <json>` lines, `data: [DONE]` terminator),
// invoking `onEvent` per frame. Resolves when the stream ends; rejects on a non-2xx response.
export async function streamEvaluationRun(
  scope: RunScope,
  onEvent: (e: RunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/evaluations/run", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(scope),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail || "evaluation run failed");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice("data: ".length).trim();
      if (payload === "[DONE]") return;
      try {
        onEvent(JSON.parse(payload) as RunEvent);
      } catch {
        /* skip malformed frame */
      }
    }
  }
}

// ── Display helpers shared by the table + modal ─────────────────────────────────

// Which C/M/S column group an evaluator's level renders under.
export function levelGroup(level: EvaluatorLevel | string): "C" | "M" | "S" {
  if (level === "CONVERSATION") return "C";
  if (level === "AGENT_RUN") return "M";
  return "S";
}

export const LEVEL_LABEL: Record<string, string> = {
  CONVERSATION: "Conversation",
  AGENT_RUN: "Message",
  SPAN: "Step",
  TOOL: "Tool step",
  GENERATION: "Generation step",
  CHAIN: "Chain step",
};
