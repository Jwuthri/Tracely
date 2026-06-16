import { authHeaders } from "./auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

/** A non-2xx API response. Thrown (not swallowed) so a backend outage surfaces in the route's
 *  `error.tsx` boundary instead of rendering as an empty state — the worst failure mode for an
 *  observability tool is "looks like there's no data" when the backend is actually down. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public path: string,
  ) {
    super(`Tracely API ${status} on ${path}`);
    this.name = "ApiError";
  }
}

async function apiGet(path: string): Promise<Response> {
  return fetch(`${API}${path}`, { headers: await authHeaders(), cache: "no-store" });
}

/** GET + parse JSON; throws `ApiError` on any non-2xx (→ error boundary). */
async function getJson<T>(path: string): Promise<T> {
  const res = await apiGet(path);
  if (!res.ok) throw new ApiError(res.status, path);
  return res.json() as Promise<T>;
}

/** GET a single resource by id: `404` → `null` (→ `notFound()`), other non-2xx throw. */
async function getJsonOrNull<T>(path: string): Promise<T | null> {
  const res = await apiGet(path);
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, path);
  return res.json() as Promise<T>;
}

export type TraceRow = {
  trace_id: string;
  ts: string;
  spans: number;
  root_name: string;
  agent_id: string;
  has_error: number;
  eval?: string | null;
};

export type EvalScore = {
  name: string;
  evaluation_level: string;
  observation_id: string | null;
  value: number | null;
  string_value?: string;
  verdict: string;
  comment: string;
  data_type: string;
  // present on streamed results (SSE run frames) for cell routing
  trace_id?: string | null;
  session_id?: string | null;
};

export type SpanOut = {
  span_id: string;
  parent_span_id: string;
  name: string;
  type: string;
  level: string;
  status_message: string;
  start_time: string;
  end_time: string | null;
  latency_ms: number | null;
  agent_id: string;
  agent_run_id: string;
  turn_id: string;
  step_name: string;
  model_id: string;
  tokens: number;
  cost: number;
  metadata: Record<string, string>;
  input: string | null;
  output: string | null;
};

export async function getTraces(): Promise<TraceRow[]> {
  return getJson<TraceRow[]>(`/api/traces?limit=50`);
}

export type Thread = {
  thread: string;
  turns: number;
  first_input: string | null;
  last_output: string | null;
  tokens: number;
  input_tokens?: number;
  output_tokens?: number;
  model?: string;
  cost: number;
  first_ts: string;
  last_ts: string;
  last_trace_id: string;
  failing: number;
  metadata?: Record<string, string>;
  scores?: EvalScore[]; // CONVERSATION-level metric results for the C-row columns
};

export type SessionsQuery = {
  limit?: number;
  offset?: number;
  from?: string | null; // ISO-8601 (UTC) lower bound on a trace's start_time
  to?: string | null; // ISO-8601 (UTC) upper bound (exclusive)
};

export async function getSessions(opts: SessionsQuery = {}): Promise<Thread[]> {
  const { limit = 50, offset = 0, from, to } = opts;
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (from) qs.set("from_ts", from);
  if (to) qs.set("to_ts", to);
  return getJson<Thread[]>(`/api/sessions?${qs.toString()}`);
}

export type ThreadTurn = {
  trace_id: string;
  input: string | null;
  output: string | null;
  tokens: number;
  input_tokens?: number;
  output_tokens?: number;
  model?: string;
  cost: number;
  latency_ms: number;
  ts: string;
  failing: number;
  scores: EvalScore[];
  verdict: string | null;
};

export async function getSession(
  id: string,
): Promise<{ thread_id: string; turns: ThreadTurn[]; scores?: EvalScore[] }> {
  return getJson(`/api/sessions/${id}`);
}

// ── Hierarchical trace table (conversation → message → step) ──────────────────
// A turn with its spans eagerly attached (detail mode pre-seeds the whole tree).
export type FullTurn = ThreadTurn & { spans: SpanOut[] };
// A conversation node. `turnsData` is present in detail mode and lazily filled in list mode.
export type ConvNode = Thread & { turnsData?: FullTurn[] };

export type TraceDetailData = {
  trace_id: string;
  thread_id?: string | null; // the conversation this trace belongs to (== trace_id when single-turn)
  spans: SpanOut[];
  scores: EvalScore[];
  eval_verdict: string | null;
};

export async function getTrace(traceId: string): Promise<TraceDetailData> {
  return getJson<TraceDetailData>(`/api/traces/${traceId}`);
}

export type Replay = {
  verdict: string;
  candidate_trace_id: string;
  detail: Record<string, unknown>;
  created_at: string | null;
};

export type EvalCase = {
  id: string;
  agent_id: string;
  level: string;
  title: string;
  status: string;
  origin: string;
  source_trace_id: string;
  input_digest: string;
  match_mode: string;
  fail_to_pass_validated: boolean;
  assertions: Record<string, unknown>;
  reference_trajectory: { steps: { kind: string; name: string; level: string }[] };
  created_at: string | null;
  last_verdict?: string | null;
  replays?: Replay[];
};

export async function getCases(): Promise<EvalCase[]> {
  return getJson<EvalCase[]>(`/api/cases`);
}

export async function getCase(caseId: string): Promise<EvalCase | null> {
  return getJsonOrNull<EvalCase>(`/api/cases/${caseId}`);
}

export type Stats = {
  traces: number;
  spans: number;
  failing_traces: number;
  auto_failures: number;
  open_clusters: number;
  agents: number;
  cases: number;
};

export async function getStats(): Promise<Stats> {
  return getJson<Stats>(`/api/stats`);
}

export type ClusterMember = {
  trace_id: string;
  is_medoid: boolean;
  summary?: string;
  input?: string;
  latency_ms?: number;
};

// A creatable evaluator draft (built-in structural check or LLM-judge rubric) the cluster view
// opens straight in the Add Column editor — see backend evaluator_suggestion.suggest_evaluator.
export type SuggestedEvaluator = {
  name: string;
  description: string;
  kind: "structural" | "llm_judge";
  level: string;
  config: Record<string, unknown>;
  rationale: string;
};

export type FailureCluster = {
  id: string;
  agent: string | null;
  label: string;
  taxonomy: string;
  description?: string;
  proposed_fix?: string;
  severity?: string;
  method?: string;
  count: number;
  status: string;
  candidate_case_id: string | null;
  signature: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  members?: ClusterMember[];
  histogram?: { t: string; count: number }[];
  suggested_evaluator?: SuggestedEvaluator;
};

export async function getClusters(): Promise<FailureCluster[]> {
  return getJson<FailureCluster[]>(`/api/clusters`);
}

export async function getCluster(id: string): Promise<FailureCluster | null> {
  return getJsonOrNull<FailureCluster>(`/api/clusters/${id}`);
}

export type GateCaseResult = {
  title: string;
  verdict: string;
  candidate_trace_id: string;
  evaluation_case_id: string;
  detail: Record<string, unknown>;
};

export type GateRun = {
  id: string;
  agent: string | null;
  env: string;
  git_ref: string;
  pr_number: number | null;
  status: string;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  latency_ms: number;
  total_tokens: number;
  warnings: string[];
  created_at: string | null;
  cases?: GateCaseResult[];
};

export async function getGates(): Promise<GateRun[]> {
  return getJson<GateRun[]>(`/api/gates`);
}

export async function getGate(gateId: string): Promise<GateRun | null> {
  return getJsonOrNull<GateRun>(`/api/gates/${gateId}`);
}

export type Trends = {
  days: number;
  daily: { date: string; traces: number; failures: number }[];
  gates_daily: { date: string; passed: number; failed: number }[];
  summary: {
    total_traces: number;
    total_failures: number;
    failure_rate: number;
    gate_runs: number;
    gate_pass_rate: number;
    cases: number;
    open_clusters: number;
    resolved_clusters: number;
    mttr_hours: number | null;
  };
};

export async function getTrends(days = 14): Promise<Trends> {
  return getJson<Trends>(`/api/trends?days=${days}`);
}
