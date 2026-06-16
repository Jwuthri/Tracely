import { getEvaluatorCost, type EvaluatorCostRow } from "@/app/lib/api";

// Format USD cents into a compact label. Shows "<¢" for sub-cent totals so a real $0.003 doesn't
// read as a fake $0.00 — and shows whole dollars without decimals once we're past $100 (the
// column gets dense). Coarse on purpose: this is a "what's expensive" surface, not an invoice.
function fmtCents(cents: number): string {
  if (cents <= 0) return "<¢";
  if (cents < 100) return `${cents}¢`;
  if (cents < 10_000) return `$${(cents / 100).toFixed(2)}`;
  return `$${Math.round(cents / 100).toLocaleString()}`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function perThousand(totalCents: number, traces: number): string {
  // $/1k traces is the metric customers actually budget against ("we have ~50k prod traces/mo;
  // how much will the judge column cost me?"). Zero traces in the window → no rate.
  if (!traces) return "—";
  const centsPer1k = (totalCents / traces) * 1000;
  return fmtCents(Math.round(centsPer1k));
}

export async function EvalCostPanel({ days = 30 }: { days?: number }) {
  // Fetched independently of the trends payload — the cost surface is opt-in (no LLM-judge
  // configured / no auto-eval run yet → empty panel + a "configure a judge" hint instead of
  // failing the whole page).
  let data;
  try {
    data = await getEvaluatorCost(days);
  } catch {
    return null; // never block the Trends page on a cost-fetch hiccup
  }

  const entries = Object.entries(data.evaluators)
    .map(([name, c]) => ({ name, ...c }))
    .sort((a, b) => b.cost_usd_cents - a.cost_usd_cents || b.total_tokens - a.total_tokens);

  const s = data.summary;
  const empty = entries.length === 0;

  return (
    <section className="reveal card p-5" style={{ animationDelay: "210ms" }}>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-semibold text-fg">Judge column cost</h2>
          <p className="mt-1 text-[12px] text-fg-muted">
            What each LLM-judge column has cost to run over the last {s.days} days — priced from
            OpenRouter when reachable, else a static fallback table.
          </p>
        </div>
        {!empty && (
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-fg-faint">
            <span className="rounded-md bg-ink-900 px-2 py-1">
              <span className="text-fg">{fmtCents(s.total_cost_usd_cents)}</span> total
            </span>
            <span className="rounded-md bg-ink-900 px-2 py-1">
              <span className="text-fg">{perThousand(s.total_cost_usd_cents, s.traces_in_window)}</span>{" "}
              per 1k traces
            </span>
            <span className="rounded-md bg-ink-900 px-2 py-1">
              <span className="text-fg">{fmtTokens(s.total_input_tokens + s.total_output_tokens)}</span>{" "}
              tokens · {s.total_runs.toLocaleString()} grades
            </span>
          </div>
        )}
      </div>

      {empty ? (
        <div className="rounded-lg border border-dashed border-line bg-ink-900/40 px-4 py-8 text-center text-[12.5px] text-fg-muted">
          No judge cost yet — install an LLM-judge column from the trace table&apos;s{" "}
          <span className="text-fg-muted">+ Add Column</span> menu, and cost will start flowing
          here as soon as the next trace is auto-evaluated.
        </div>
      ) : (
        <CostTable rows={entries} totalTraces={s.traces_in_window} />
      )}
    </section>
  );
}

function CostTable({
  rows,
  totalTraces,
}: {
  rows: ({ name: string } & EvaluatorCostRow)[];
  totalTraces: number;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b border-line text-left font-mono text-[10px] uppercase tracking-wider text-fg-faint">
            <th className="px-2 py-2 font-medium">Evaluator</th>
            <th className="px-2 py-2 text-right font-medium">Cost</th>
            <th className="px-2 py-2 text-right font-medium">$ / 1k traces</th>
            <th className="px-2 py-2 text-right font-medium">Runs</th>
            <th className="px-2 py-2 text-right font-medium">Tokens</th>
            <th className="px-2 py-2 font-medium">Model</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-b border-line/40 last:border-0 hover:bg-white/[0.015]">
              <td className="px-2 py-2 font-mono text-fg">{r.name}</td>
              <td className="px-2 py-2 text-right font-mono tabular-nums text-fg">
                {fmtCents(r.cost_usd_cents)}
              </td>
              <td className="px-2 py-2 text-right font-mono tabular-nums text-fg-muted">
                {perThousand(r.cost_usd_cents, totalTraces)}
              </td>
              <td className="px-2 py-2 text-right font-mono tabular-nums text-fg-muted">
                {r.runs.toLocaleString()}
              </td>
              <td className="px-2 py-2 text-right font-mono tabular-nums text-fg-muted">
                {fmtTokens(r.total_tokens)}
              </td>
              <td className="px-2 py-2 font-mono text-fg-muted">
                {r.model || <span className="text-fg-faint">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
