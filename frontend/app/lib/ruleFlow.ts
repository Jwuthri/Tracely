import type { Edge, Node } from "@xyflow/react";

/** The alert-rule flow: types, step-type palette, and the pure graph utilities.
 *
 *  **These utilities are the half that has to match the backend exactly.** The same three stages
 *  run in `backend/tracely/domain/alerting/flow.py`: dedupe edges → BFS reachability from the
 *  trigger → Kahn topological sort with sorted-id tie-breaks. If the two drift, a rule runs
 *  differently than it looked on screen — which is the one bug a visual builder must not have.
 *
 *  `RULE_TRIGGER_NODE_ID` is declared here and again in `flow.py`. It is the id of a node that
 *  exists on the canvas and in `flow_layout.edges`, and never as a step row. */

export const RULE_TRIGGER_NODE_ID = "__rule_trigger__";
export const VARIABLE_DRAG_MIME = "text/x-variable";
export const CYCLE_ERROR = "Cycle detected in the flow — remove a connection to fix.";

export type StepType = "condition" | "webhook" | "slack" | "send_email" | "llm_prompt" | "python_expression";

export type TriggerId =
  | "gate_failed"
  | "trace_failed"
  | "cluster_new"
  | "fail_rate_over"
  | "score_below"
  | "trace_failure_rate";

export type HeaderEntry = { key: string; value: string };
export type OutputField = { name: string; type: "string" | "number" | "boolean" | "array"; description: string };

export type StepConfig = Record<string, unknown>;

export type StepDraft = {
  id: string;
  order_index: number;
  name: string;
  step_type: StepType;
  config: StepConfig;
};

export type StepNodeData = { name: string; step_type: StepType; config: StepConfig };

export type FlowLayout = { nodes: Node[]; edges: Edge[] };

export type SavePayload = { steps: StepDraft[]; flow_layout: FlowLayout; error: string | null };

/** The imperative contract between the page and the canvas — the whole surface. `getSavePayload`
 *  turns a picture into rows; `replaceFlow` is how the assistant drops a generated graph onto a
 *  live canvas without a remount. */
export type RuleFlowHandle = {
  getSavePayload: () => SavePayload;
  replaceFlow: (nodes: readonly Node[], edges: readonly Edge[]) => void;
};

// ── step palette: one entry per type, five uses each ─────────────────────────

export type StepMeta = {
  label: string;
  /** Tracely theme token name (see globals.css) — never a raw hex, so both themes work. */
  tone: "signal" | "info" | "ok" | "warn" | "fail" | "tool";
  blurb: string;
  outputs: { name: string; desc: string }[];
};

export const STEP_META: Record<StepType, StepMeta> = {
  condition: {
    label: "Condition",
    tone: "warn",
    blurb: "A gate. Renders an expression — anything falsy stops the whole run.",
    outputs: [
      { name: "matched", desc: "true / false — the gate decision" },
      { name: "expression", desc: "What the expression rendered to" },
    ],
  },
  slack: {
    label: "Slack",
    tone: "ok",
    blurb: "Post a templated message to a Slack incoming webhook.",
    outputs: [
      { name: "status", desc: "HTTP status from Slack" },
      { name: "text", desc: "Slack's response body" },
    ],
  },
  send_email: {
    label: "Send email",
    tone: "info",
    blurb: "Mail one or more addresses. Needs RESEND_API_KEY on the backend.",
    outputs: [
      { name: "status", desc: "HTTP status from Resend" },
      { name: "recipients", desc: "Addresses the mail went to" },
    ],
  },
  webhook: {
    label: "Webhook",
    tone: "tool",
    blurb: "Any verb, any headers (Authorization: Bearer …), a templated JSON body.",
    outputs: [
      { name: "status", desc: "HTTP status" },
      { name: "text", desc: "Response body (truncated)" },
    ],
  },
  llm_prompt: {
    label: "LLM prompt",
    tone: "signal",
    blurb: "Ask a model about this failure and hand the answer to the next step. Uses your OpenRouter key.",
    outputs: [{ name: "text", desc: "Model output" }],
  },
  python_expression: {
    label: "Python expression",
    tone: "fail",
    blurb: "One allowlisted expression — counting, slicing, a threshold a template can't compute.",
    outputs: [{ name: "result", desc: "Value the expression returned" }],
  },
};

export const STEP_ORDER: StepType[] = [
  "condition",
  "slack",
  "send_email",
  "webhook",
  "llm_prompt",
  "python_expression",
];

const UNKNOWN_META: StepMeta = {
  label: "Unknown step",
  tone: "info",
  blurb: "This step type came from a newer version of Tracely.",
  outputs: [],
};

export const stepMeta = (t: string): StepMeta => STEP_META[t as StepType] ?? UNKNOWN_META;

export const isKnownStepType = (t: string): t is StepType => t in STEP_META;

/** The Output column: an LLM step's declared schema wins over the default `text`. */
export const stepOutputs = (stepType: string, config?: StepConfig): { name: string; desc: string }[] => {
  if (stepType === "llm_prompt") {
    const schema = (config?.output_schema as OutputField[] | undefined) ?? [];
    if (schema.length > 0) return schema.map((f) => ({ name: f.name, desc: f.description || f.type }));
  }
  return stepMeta(stepType).outputs;
};

export const defaultStepConfig = (stepType: StepType): StepConfig => {
  switch (stepType) {
    case "condition":
      return { expression: "" };
    case "slack":
      return { url: "", text_template: "" };
    case "send_email":
      return { to_template: "", subject_template: "", body_template: "", body_is_html: false };
    case "webhook":
      return { url: "", method: "POST", headers: [] as HeaderEntry[], body_template: "" };
    case "llm_prompt":
      return { model: "", system_prompt: "", user_prompt_template: "", temperature: 0, output_schema: [] };
    case "python_expression":
      return { expression: "" };
  }
};

export const newStepId = (): string =>
  typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? `s-${crypto.randomUUID()}`
    : `s-${Math.round(performance.now())}-${Math.floor(Math.random() * 1e6)}`;

// ── graph utilities (mirror of domain/alerting/flow.py) ───────────────────────

export const dedupeEdges = (edges: readonly Edge[]): Edge[] => {
  const seen = new Set<string>();
  const out: Edge[] = [];
  for (const e of edges) {
    if (!e.source || !e.target || e.source === e.target) continue;
    const key = `${e.source}->${e.target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(e);
  }
  return out;
};

/** Steps reachable from the trigger. Anything else is a *parked* node: saved, visible, not run. */
export const reachableStepIds = (edges: readonly Edge[], stepIds: ReadonlySet<string>): string[] => {
  const outgoing = new Map<string, string[]>();
  for (const e of edges) {
    if (e.target === RULE_TRIGGER_NODE_ID || !stepIds.has(e.target)) continue;
    if (e.source !== RULE_TRIGGER_NODE_ID && !stepIds.has(e.source)) continue;
    outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]);
  }
  const visited = new Set<string>([RULE_TRIGGER_NODE_ID]);
  const queue: string[] = [RULE_TRIGGER_NODE_ID];
  const collected: string[] = [];
  while (queue.length > 0) {
    const u = queue.shift() as string;
    for (const v of outgoing.get(u) ?? []) {
      if (visited.has(v)) continue;
      visited.add(v);
      queue.push(v);
      collected.push(v);
    }
  }
  return collected.sort((a, b) => a.localeCompare(b));
};

/** Kahn's algorithm, ready nodes popped in sorted-id order so the client and the worker emit the
 *  same order for the same graph. */
export const topoOrder = (
  edges: readonly Edge[],
  stepIds: ReadonlySet<string>,
): { order: string[]; error: string | null } => {
  const deduped = dedupeEdges(edges);
  const reachable = new Set(reachableStepIds(deduped, stepIds));
  const nodes = new Set<string>([RULE_TRIGGER_NODE_ID, ...reachable]);
  const indegree = new Map<string, number>();
  for (const n of nodes) indegree.set(n, 0);
  const outgoing = new Map<string, string[]>();
  for (const e of deduped) {
    if (!nodes.has(e.source) || !nodes.has(e.target) || e.target === RULE_TRIGGER_NODE_ID) continue;
    indegree.set(e.target, (indegree.get(e.target) ?? 0) + 1);
    outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]);
  }
  const ready = [...nodes].filter((n) => (indegree.get(n) ?? 0) === 0).sort((a, b) => a.localeCompare(b));
  const order: string[] = [];
  let popped = 0;
  while (ready.length > 0) {
    const u = ready.shift() as string;
    popped += 1;
    if (u !== RULE_TRIGGER_NODE_ID) order.push(u);
    for (const v of outgoing.get(u) ?? []) {
      const next = (indegree.get(v) ?? 0) - 1;
      indegree.set(v, next);
      if (next === 0) {
        ready.push(v);
        ready.sort((a, b) => a.localeCompare(b));
      }
    }
  }
  if (popped !== nodes.size) return { order: [], error: CYCLE_ERROR };
  return { order, error: null };
};

export const readStepNodeData = (raw: unknown): StepNodeData => {
  const d = (raw !== null && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const name = typeof d.name === "string" ? d.name : "";
  const rawType = typeof d.step_type === "string" ? d.step_type : "";
  const config =
    d.config !== null && typeof d.config === "object"
      ? (d.config as StepConfig)
      : isKnownStepType(rawType)
        ? defaultStepConfig(rawType)
        : {};
  return { name, step_type: rawType as StepType, config };
};

/** Canvas → rows. Reachable steps first in run order (`order_index` 0…n), then orphans, so a
 *  parked node is never silently deleted by a save. A cycle refuses to produce drafts at all. */
export const flowToStepDrafts = (
  nodes: readonly Node[],
  edges: readonly Edge[],
): { drafts: StepDraft[]; error: string | null; orphanIds: string[] } => {
  const deduped = dedupeEdges(edges);
  const stepNodes = nodes.filter((n) => n.type === "ruleStep" && n.id !== RULE_TRIGGER_NODE_ID);
  const stepIds = new Set(stepNodes.map((n) => n.id));
  const { order, error } = topoOrder(deduped, stepIds);
  if (error !== null) return { drafts: [], error, orphanIds: [] };
  const reachable = new Set(reachableStepIds(deduped, stepIds));
  const orphanIds = [...stepIds].filter((id) => !reachable.has(id)).sort((a, b) => a.localeCompare(b));
  const byId = new Map(stepNodes.map((n) => [n.id, n]));
  const drafts: StepDraft[] = [];
  for (const id of [...order, ...orphanIds]) {
    const node = byId.get(id);
    if (!node) continue;
    const d = readStepNodeData(node.data);
    drafts.push({ id, order_index: drafts.length, name: d.name, step_type: d.step_type, config: d.config });
  }
  return { drafts, error: null, orphanIds };
};

/** The ancestors of `selectedId` in run order — the steps whose output it can read.
 *
 *  Upstream outputs are **positional**: the engine hands each step
 *  `steps = [{result}, …]` for exactly these ancestors, so the chip label `steps[0].result` IS the
 *  runtime path. This is the same reverse BFS `ancestor_step_ids` does in Python. */
export const priorStepsOrdered = (
  selectedId: string,
  drafts: readonly StepDraft[],
  edges: readonly Edge[],
  stepIds: ReadonlySet<string>,
): StepDraft[] => {
  const incoming = new Map<string, string[]>();
  for (const e of dedupeEdges(edges)) {
    if (e.target === RULE_TRIGGER_NODE_ID || !stepIds.has(e.target)) continue;
    if (e.source !== RULE_TRIGGER_NODE_ID && !stepIds.has(e.source)) continue;
    incoming.set(e.target, [...(incoming.get(e.target) ?? []), e.source]);
  }
  const ancestors = new Set<string>();
  const visited = new Set<string>([selectedId]);
  const queue = [selectedId];
  while (queue.length > 0) {
    const u = queue.shift() as string;
    for (const p of incoming.get(u) ?? []) {
      if (p === RULE_TRIGGER_NODE_ID || !stepIds.has(p) || visited.has(p)) continue;
      visited.add(p);
      ancestors.add(p);
      queue.push(p);
    }
  }
  const byId = new Map(drafts.map((d) => [d.id, d]));
  return [...ancestors]
    .map((id) => byId.get(id))
    .filter((d): d is StepDraft => d !== undefined)
    .sort((a, b) => a.order_index - b.order_index);
};

// ── layout construction ──────────────────────────────────────────────────────

export const EDGE_DEFAULTS = {
  type: "smoothstep" as const,
  animated: true,
  // A 1.75px line is unclickable without this: the hit area, not the stroke, is what you grab.
  interactionWidth: 28,
  style: { stroke: "rgb(var(--c-signal) / 0.55)", strokeWidth: 1.75 },
};

export const applyEdgeDefaults = (e: Edge): Edge => ({
  ...EDGE_DEFAULTS,
  ...e,
  style: { ...EDGE_DEFAULTS.style, ...(typeof e.style === "object" && e.style !== null ? e.style : {}) },
});

export const triggerNode = (label: string, position = { x: 40, y: 120 }): Node => ({
  id: RULE_TRIGGER_NODE_ID,
  type: "trigger",
  position,
  deletable: false,
  data: { label },
});

/** Rows → canvas. Uses the saved layout when it has nodes, otherwise synthesises a horizontal
 *  chain from `order_index` — which is why an API-created rule and a hand-drawn one open the same.
 *  Either way step data is re-merged by id with the ROW winning, so an API-side edit can never be
 *  shadowed by a stale layout blob. */
export const buildFlowFromRule = (rule: {
  steps: readonly StepDraft[];
  flow_layout: FlowLayout | null;
  triggerLabel: string;
}): FlowLayout => {
  const byId = new Map(rule.steps.map((s) => [s.id, s]));
  const merge = (nodes: readonly Node[]): Node[] =>
    nodes.map((n) => {
      if (n.id === RULE_TRIGGER_NODE_ID) {
        return { ...n, type: "trigger", deletable: false, data: { ...(n.data ?? {}), label: rule.triggerLabel } };
      }
      const row = byId.get(n.id);
      const data = row
        ? { name: row.name, step_type: row.step_type, config: row.config }
        : readStepNodeData(n.data);
      return { ...n, type: "ruleStep", data: data as unknown as Record<string, unknown> };
    });

  const layout = rule.flow_layout;
  if (layout && Array.isArray(layout.nodes) && layout.nodes.length > 0) {
    const hasTrigger = layout.nodes.some((n) => n.id === RULE_TRIGGER_NODE_ID);
    const nodes = merge(hasTrigger ? layout.nodes : [triggerNode(rule.triggerLabel), ...layout.nodes]);
    return { nodes, edges: (layout.edges ?? []).map(applyEdgeDefaults) };
  }
  const sorted = [...rule.steps].sort((a, b) => a.order_index - b.order_index);
  const nodes: Node[] = [triggerNode(rule.triggerLabel)];
  const edges: Edge[] = [];
  let prev = RULE_TRIGGER_NODE_ID;
  sorted.forEach((s, i) => {
    nodes.push({
      id: s.id,
      type: "ruleStep",
      position: { x: 300 + i * 280, y: 120 },
      data: { name: s.name, step_type: s.step_type, config: s.config } as unknown as Record<string, unknown>,
    });
    edges.push(applyEdgeDefaults({ id: `e-${prev}-${s.id}`, source: prev, target: s.id }));
    prev = s.id;
  });
  return { nodes, edges };
};

/** A brand-new rule: the trigger plus one Slack step, already wired. An empty canvas is a worse
 *  first screen than a flow you can run immediately. */
export const initialFlow = (triggerLabel: string): FlowLayout => {
  const id = newStepId();
  return {
    nodes: [
      triggerNode(triggerLabel),
      {
        id,
        type: "ruleStep",
        position: { x: 340, y: 120 },
        data: {
          name: "Notify Slack",
          step_type: "slack",
          config: {
            url: "",
            text_template: "🚨 {{ alert.name }}\n{{ alert.summary }}\n{{ alert.url }}",
          },
        } as unknown as Record<string, unknown>,
      },
    ],
    edges: [applyEdgeDefaults({ id: `e-${RULE_TRIGGER_NODE_ID}-${id}`, source: RULE_TRIGGER_NODE_ID, target: id })],
  };
};

// ── {{ variable }} tokens ────────────────────────────────────────────────────

const TOKEN_RE = /\{\{[\s\S]*?\}\}/g;

export type VariableSegment = { kind: "text" | "token"; value: string };

/** Split a template into plain text and `{{ token }}` runs — what the highlighted mirror renders. */
export const splitVariableTokens = (value: string): VariableSegment[] => {
  const out: VariableSegment[] = [];
  TOKEN_RE.lastIndex = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(value)) !== null) {
    if (m.index > i) out.push({ kind: "text", value: value.slice(i, m.index) });
    out.push({ kind: "token", value: m[0] });
    i = m.index + m[0].length;
  }
  if (i < value.length) out.push({ kind: "text", value: value.slice(i) });
  return out;
};

export const variableTokenRanges = (value: string): [number, number][] => {
  const out: [number, number][] = [];
  TOKEN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(value)) !== null) out.push([m.index, m.index + m[0].length]);
  return out;
};

/** Backspace/Delete next to a token removes the WHOLE token. Twelve lines, and it's the difference
 *  between a template field feeling like a form and feeling like a tool. */
export const tokenDeletionRange = (
  value: string,
  caret: number,
  key: "Backspace" | "Delete",
): [number, number] | null => {
  const ranges = variableTokenRanges(value);
  const hit =
    key === "Backspace"
      ? ranges.find(([s, e]) => s < caret && caret <= e)
      : ranges.find(([s, e]) => s <= caret && caret < e);
  return hit ?? null;
};
