import { getOps, type Ops } from "@/app/lib/api";
import { StatCard } from "@/app/components/ui";
import { Spark, Legend } from "@/app/components/Bars";
import { fmtUsd } from "@/app/lib/usage";
import { dur, modelCost, pct, tokens, totalCost, ttft } from "@/app/components/ops-format";

/** Dashboard vitals strip: the same roll-up over a 24h window. The dashboard's cards are
 *  all-time counts, so this is the only thing on the page that answers "how is it doing *now*" —
 *  deliberately a one-line summary, not a second Trends page. */
export async function OpsStrip() {
  let ops: Ops;
  try {
    ops = await getOps(1);
  } catch {
    return null;
  }
  const s = ops.summary;
  if (!s.traces) return null; // quiet 24h → no strip, rather than a row of zeros

  const cost = totalCost(ops);
  const vitals: [string, string, string?][] = [
    ["traces", s.traces.toLocaleString()],
    ["p50", dur(s.p50)],
    ["p95", dur(s.p95), "text-warn"],
    ["p99", dur(s.p99), "text-fail"],
    ["errors", pct(s.error_rate), s.errors ? "text-fail" : "text-ok"],
    ["tokens", tokens(s.tokens)],
    ["cost", fmtUsd(cost)],
  ];

  return (
    <section className="reveal card flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3" style={{ animationDelay: "200ms" }}>
      <span className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-fg-faint">Last 24h</span>
      {vitals.map(([label, value, accent]) => (
        <span key={label} className="flex items-baseline gap-1.5">
          <span className={`font-mono text-[14px] tabular-nums ${accent ?? "text-fg"}`}>{value}</span>
          <span className="text-[11.5px] text-fg-muted">{label}</span>
        </span>
      ))}
      <a href="/trends" className="ml-auto text-[12px] text-fg-muted transition-colors hover:text-signal">
        Trends →
      </a>
    </section>
  );
}

export async function OpsPanel({ days = 14 }: { days?: number }) {
  let ops: Ops;
  try {
    ops = await getOps(days);
  } catch {
    return null; // never block Trends on the ops roll-up
  }
  const s = ops.summary;
  const cost = totalCost(ops);

  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Latency (p50)" value={dur(s.p50)} sub="median trace, end-to-end" delay={40} />
        <StatCard label="Latency (p95)" value={dur(s.p95)} accent="text-warn" sub="slow tail" delay={70} />
        <StatCard label="Latency (p99)" value={dur(s.p99)} accent="text-fail" sub="worst 1%" delay={100} />
        <StatCard
          label="Time to first token"
          value={ttft(s.ttft_p50)}
          accent="text-signal"
          sub={s.ttft_p50 > 0 ? "p50 · streaming spans" : "not reported by this SDK"}
          delay={130}
        />
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Throughput" value={s.traces_per_day} sub={`traces / day · ${s.traces} total`} delay={40} />
        <StatCard
          label="Error rate"
          value={pct(s.error_rate)}
          accent={s.errors ? "text-fail" : "text-ok"}
          sub={`${s.errors} traces with an ERROR span`}
          delay={70}
        />
        <StatCard label="Tokens" value={tokens(s.tokens)} sub={`${s.llm_calls.toLocaleString()} LLM calls`} delay={100} />
        <StatCard
          label="Cost"
          value={fmtUsd(cost)}
          sub={s.traces ? `${fmtUsd((cost / s.traces) * 1000)} per 1k traces` : "—"}
          delay={130}
        />
      </div>

      <section className="reveal card p-5" style={{ animationDelay: "150ms" }}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[13px] font-semibold text-fg">Latency over time</h2>
          <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">
            per day · peak {dur(Math.max(0, ...ops.daily.map((d) => d.p99)))}
          </span>
        </div>
        <Spark
          series={[
            { values: ops.daily.map((d) => d.p99), stroke: "stroke-fail/70", label: "p99" },
            { values: ops.daily.map((d) => d.p95), stroke: "stroke-warn/70", label: "p95" },
            { values: ops.daily.map((d) => d.p50), stroke: "stroke-signal", fill: "fill-signal/10", label: "p50" },
          ]}
        />
        <div className="mt-2 flex justify-between font-mono text-[9.5px] text-fg-faint">
          <span>{ops.daily[0]?.date.slice(5) ?? ""}</span>
          <span>{ops.daily.at(-1)?.date.slice(5) ?? ""}</span>
        </div>
        <Legend items={[["bg-signal", "p50"], ["bg-warn/70", "p95"], ["bg-fail/70", "p99"]]} />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Table
          title="By model"
          note="latency of the generation span itself"
          cols={["Model", "Calls", "p50", "p95", "TTFT", "Tokens", "Cost"]}
          rows={ops.models.map((m) => [
            m.model,
            m.calls.toLocaleString(),
            dur(m.p50),
            dur(m.p95),
            ttft(m.ttft_p50),
            tokens(m.tokens),
            fmtUsd(modelCost(m)),
          ])}
          empty="No model spans in this window."
        />
        <Table
          title="Slowest operations"
          note="by p95, across every span"
          cols={["Operation", "Type", "Calls", "p50", "p95", "Max", "Errors"]}
          rows={ops.slowest.map((o) => [
            o.name,
            o.type.toLowerCase(),
            o.calls.toLocaleString(),
            dur(o.p50),
            dur(o.p95),
            dur(o.max),
            o.errors ? String(o.errors) : "0",
          ])}
          empty="No spans in this window."
        />
      </div>
    </>
  );
}

/** Shared shape for both roll-ups: first column is a left-aligned name, the rest are right-aligned
 *  numbers. Deliberately dumb (string cells, no sorting) — these are read-only summaries. */
function Table({
  title,
  note,
  cols,
  rows,
  empty,
}: {
  title: string;
  note: string;
  cols: string[];
  rows: string[][];
  empty: string;
}) {
  return (
    <section className="reveal card p-5" style={{ animationDelay: "170ms" }}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-[13px] font-semibold text-fg">{title}</h2>
        <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">{note}</span>
      </div>
      {rows.length === 0 ? (
        <div className="py-8 text-center text-[12.5px] text-fg-faint">{empty}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-line text-left font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                {cols.map((c, i) => (
                  <th key={c} className={`px-2 py-2 font-medium ${i ? "text-right" : ""}`}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r[0]} className="border-b border-line/40 last:border-0 hover:bg-white/[0.015]">
                  {r.map((cell, i) => (
                    <td
                      key={i}
                      className={`px-2 py-2 font-mono tabular-nums ${
                        i ? "text-right text-fg-muted" : "max-w-[16ch] truncate text-fg"
                      }`}
                      title={i === 0 ? cell : undefined}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
