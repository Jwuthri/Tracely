import { getTrends } from "@/app/lib/api";
import { StatCard } from "@/app/components/ui";
import { Bars, Legend } from "@/app/components/Bars";
import { MetaAnalysisPanel } from "@/app/components/MetaAnalysisPanel";
import { EvalCostPanel } from "@/app/components/EvalCostPanel";

const pct = (x: number) => `${Math.round(x * 100)}%`;
const mmdd = (d: string) => d.slice(5); // YYYY-MM-DD -> MM-DD

export default async function TrendsPage() {
  const t = await getTrends(14);
  const s = t.summary;

  return (
    <div className="space-y-6">
      <header className="reveal flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-[26px] font-extrabold tracking-tight">Trends</h1>
          <p className="mt-1.5 max-w-2xl text-[14px] text-fg-muted">
            How your agents are doing over time — how often they fail, whether the gate is holding the line,
            and how quickly failures turn into regression tests.
          </p>
        </div>
        <span className="font-mono text-[11px] text-fg-faint">last {t.days} days</span>
      </header>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Failure rate" value={pct(s.failure_rate)} accent="text-fail"
          sub={`${s.total_failures} of ${s.total_traces} traces`} delay={40} />
        <StatCard label="Gate pass-rate" value={pct(s.gate_pass_rate)} accent="text-ok"
          sub={`${s.gate_runs} gate runs`} delay={70} />
        <StatCard label="Open issues" value={s.open_clusters} accent={s.open_clusters ? "text-warn" : "text-fg"}
          sub={`${s.resolved_clusters} resolved`} delay={100} />
        <StatCard label="Regression tests" value={s.cases} accent="text-signal"
          sub={s.mttr_hours != null ? `~${s.mttr_hours}h failure → test` : "forever-running"} delay={130} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="reveal card p-5" style={{ animationDelay: "150ms" }}>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-[13px] font-semibold text-fg">Traces &amp; failures</h2>
            <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">per day</span>
          </div>
          <Bars
            color="bg-signal/20"
            subColor="bg-fail/70"
            data={t.daily.map((d) => ({
              label: mmdd(d.date),
              value: d.traces,
              sub: d.failures,
              title: `${d.date}: ${d.failures} failing of ${d.traces} traces`,
            }))}
          />
          <Legend items={[["bg-signal/20", "traces"], ["bg-fail/70", "failing"]]} />
        </section>

        <section className="reveal card p-5" style={{ animationDelay: "170ms" }}>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-[13px] font-semibold text-fg">Gate runs</h2>
            <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">per day</span>
          </div>
          <Bars
            color="bg-ok/30"
            subColor="bg-fail/70"
            data={t.gates_daily.map((g) => ({
              label: mmdd(g.date),
              value: g.passed + g.failed,
              sub: g.failed,
              title: `${g.date}: ${g.passed} passed, ${g.failed} failed`,
            }))}
          />
          <Legend items={[["bg-ok/30", "passed"], ["bg-fail/70", "failed"]]} />
        </section>
      </div>

      <EvalCostPanel days={30} />

      <MetaAnalysisPanel />
    </div>
  );
}
