// Token + cost usage derivation, shared by the trace table (client) and the detail-page
// headers (server). Pure functions — no React. Cost isn't traced, so price is derived from a
// per-model rate table when token counts are present.
import type { ConvNode, FullTurn, SpanOut } from "./api";

// Approx public list price, USD per 1M tokens: [input, output].
const PRICES: [RegExp, number, number][] = [
  [/gpt-4o-mini/, 0.15, 0.6],
  [/gpt-4o/, 2.5, 10],
  [/gpt-4-turbo/, 10, 30],
  [/gpt-4/, 30, 60],
  [/gpt-3\.5/, 0.5, 1.5],
  [/o3|o1/, 15, 60],
  [/opus/, 15, 75],
  [/sonnet/, 3, 15],
  [/haiku/, 0.25, 1.25],
];
export function rateFor(model: string): [number, number] {
  const s = model.toLowerCase();
  for (const [re, i, o] of PRICES) if (re.test(s)) return [i, o];
  return [0, 0];
}
export function round(n: number, d = 6): number {
  const f = 10 ** d;
  return Math.round(n * f) / f;
}
function pickNum(md: Record<string, string>, keys: string[]): number | undefined {
  for (const k of keys) {
    if (md[k] != null) {
      const n = Number(md[k]);
      if (!Number.isNaN(n)) return n;
    }
  }
  return undefined;
}
export function spanUsage(span: SpanOut): Record<string, number> {
  const md = span.metadata || {};
  const u: Record<string, number> = {};
  const it = pickNum(md, ["gen_ai.usage.input_tokens", "input_tokens", "prompt_tokens"]);
  const ot = pickNum(md, ["gen_ai.usage.output_tokens", "output_tokens", "completion_tokens"]);
  const tt = pickNum(md, ["gen_ai.usage.reasoning_tokens", "thinking_tokens", "reasoning_tokens"]);
  if (it != null) u.input_tokens = it;
  if (ot != null) u.output_tokens = ot;
  if (tt != null) u.thinking_tokens = tt;
  // total = input + output (matches the backend token total, which excludes reasoning tokens);
  // thinking_tokens is surfaced separately.
  const total = span.tokens || (it || 0) + (ot || 0);
  if (total > 0) u.total_tokens = total;
  const model = md["gen_ai.request.model"] || span.model_id || "";
  const [ri, ro] = rateFor(model);
  let ip = pickNum(md, ["input_price", "input_cost"]);
  let op = pickNum(md, ["output_price", "output_cost"]);
  if (ip == null && it != null && ri) ip = round((it / 1e6) * ri);
  if (op == null && ot != null && ro) op = round((ot / 1e6) * ro);
  if (ip != null) u.input_price = ip;
  if (op != null) u.output_price = op;
  const cost = span.cost || (ip || 0) + (op || 0);
  if (cost > 0) u.cost = round(cost);
  return u;
}
function sumUsages(items: Array<Record<string, number>>): Record<string, number> {
  const agg: Record<string, number> = {};
  for (const u of items) for (const k in u) agg[k] = round((agg[k] || 0) + u[k]);
  return agg;
}
// Build a usage breakdown from aggregate token counts + a representative model (prices like spanUsage).
function usageFrom(it: number, ot: number, total: number, cost: number, model: string): Record<string, number> {
  const u: Record<string, number> = {};
  if (it) u.input_tokens = it;
  if (ot) u.output_tokens = ot;
  const tot = total || it + ot;
  if (tot) u.total_tokens = tot;
  const [ri, ro] = rateFor(model);
  const ip = it && ri ? round((it / 1e6) * ri) : 0;
  const op = ot && ro ? round((ot / 1e6) * ro) : 0;
  if (ip) u.input_price = ip;
  if (op) u.output_price = op;
  const c = cost || ip + op;
  if (c) u.cost = round(c);
  return u;
}
// Turn usage = exact per-span aggregation when steps are loaded, else from the turn's totals.
export function turnUsage(turn: FullTurn): Record<string, number> {
  if (turn.spans?.length) {
    const agg = sumUsages(turn.spans.map(spanUsage));
    if (Object.keys(agg).length) return agg;
  }
  return usageFrom(turn.input_tokens ?? 0, turn.output_tokens ?? 0, turn.tokens, turn.cost, turn.model ?? "");
}
// Conversation usage = sum of its turns when loaded, else from the thread's totals.
export function convUsage(conv: ConvNode): Record<string, number> {
  if (conv.turnsData?.length) {
    const agg = sumUsages(conv.turnsData.map(turnUsage));
    if (Object.keys(agg).length) return agg;
  }
  return usageFrom(conv.input_tokens ?? 0, conv.output_tokens ?? 0, conv.tokens, conv.cost, conv.model ?? "");
}
export function fmtUsd(n: number): string {
  if (n === 0) return "$0";
  return n >= 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(6)}`;
}
export function usageSummary(u: Record<string, number>): string {
  const parts: string[] = [];
  const tok = u.total_tokens ?? (u.input_tokens || 0) + (u.output_tokens || 0);
  if (tok) parts.push(`${tok.toLocaleString("en-US")} tok`);
  if (u.cost) parts.push(fmtUsd(u.cost));
  return parts.join(" · ") || "usage";
}
