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
  input: string | null;
  output: string | null;
};

export async function getTraces(): Promise<TraceRow[]> {
  const res = await fetch(`${API}/api/traces?limit=50`, { headers, cache: "no-store" });
  if (!res.ok) return [];
  return res.json();
}

export async function getTrace(traceId: string): Promise<{ trace_id: string; spans: SpanOut[] }> {
  const res = await fetch(`${API}/api/traces/${traceId}`, { headers, cache: "no-store" });
  if (!res.ok) return { trace_id: traceId, spans: [] };
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
  agents: number;
  cases: number;
};

export async function getStats(): Promise<Stats> {
  const res = await fetch(`${API}/api/stats`, { headers, cache: "no-store" });
  if (!res.ok) return { traces: 0, spans: 0, failing_traces: 0, agents: 0, cases: 0 };
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
