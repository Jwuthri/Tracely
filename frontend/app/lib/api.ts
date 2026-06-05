const API = process.env.TRACELY_API ?? "http://localhost:8000";
const KEY = process.env.TRACELY_KEY ?? "tracely_dev_key";

const headers = { Authorization: `Bearer ${KEY}` };

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
  verdict: string;
  comment: string;
  data_type: string;
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
  const res = await fetch(`${API}/api/traces?limit=50`, { headers, cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
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
  last_ts: string;
  last_trace_id: string;
  failing: number;
};

export async function getSessions(): Promise<Thread[]> {
  const res = await fetch(`${API}/api/sessions?limit=50`, { headers, cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
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

export async function getSession(id: string): Promise<{ thread_id: string; turns: ThreadTurn[] }> {
  const res = await fetch(`${API}/api/sessions/${id}`, { headers, cache: "no-store" });
  if (!res.ok) return { thread_id: id, turns: [] };
  return res.json();
}

// ── Hierarchical trace table (conversation → message → step) ──────────────────
// A turn with its spans eagerly attached (detail mode pre-seeds the whole tree).
export type FullTurn = ThreadTurn & { spans: SpanOut[] };
// A conversation node. `turnsData` is present in detail mode and lazily filled in list mode.
export type ConvNode = Thread & { turnsData?: FullTurn[] };

export type TraceDetailData = {
  trace_id: string;
  spans: SpanOut[];
  scores: EvalScore[];
  eval_verdict: string | null;
};

export async function getTrace(traceId: string): Promise<TraceDetailData> {
  const res = await fetch(`${API}/api/traces/${traceId}`, { headers, cache: "no-store" });
  if (!res.ok) return { trace_id: traceId, spans: [], scores: [], eval_verdict: null };
  return res.json();
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
  const res = await fetch(`${API}/api/cases`, { headers, cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function getCase(caseId: string): Promise<EvalCase | null> {
  const res = await fetch(`${API}/api/cases/${caseId}`, { headers, cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
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
  const res = await fetch(`${API}/api/stats`, { headers, cache: "no-store" });
  if (!res.ok)
    return { traces: 0, spans: 0, failing_traces: 0, auto_failures: 0, open_clusters: 0, agents: 0, cases: 0 };
  return res.json();
}

export type ClusterMember = {
  trace_id: string;
  is_medoid: boolean;
  summary?: string;
  input?: string;
  latency_ms?: number;
};

export type SuggestedEvaluator = { name: string; language: string; code: string };

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
  const res = await fetch(`${API}/api/clusters`, { headers, cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function getCluster(id: string): Promise<FailureCluster | null> {
  const res = await fetch(`${API}/api/clusters/${id}`, { headers, cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
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
  const res = await fetch(`${API}/api/gates`, { headers, cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function getGate(gateId: string): Promise<GateRun | null> {
  const res = await fetch(`${API}/api/gates/${gateId}`, { headers, cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
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

const EMPTY_TRENDS: Trends = {
  days: 14,
  daily: [],
  gates_daily: [],
  summary: {
    total_traces: 0, total_failures: 0, failure_rate: 0, gate_runs: 0, gate_pass_rate: 0,
    cases: 0, open_clusters: 0, resolved_clusters: 0, mttr_hours: null,
  },
};

export async function getTrends(days = 14): Promise<Trends> {
  const res = await fetch(`${API}/api/trends?days=${days}`, { headers, cache: "no-store" });
  if (!res.ok) return EMPTY_TRENDS;
  return res.json();
}
