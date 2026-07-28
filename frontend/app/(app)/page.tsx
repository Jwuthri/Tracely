import { getCases, getClusters, getStats, getTraces, getTrends, type FailureCluster } from "@/app/lib/api";
import { Badge, StatCard, statusVariant, verdictVariant } from "@/app/components/ui";
import { IconChevron } from "@/app/components/icons";
import { OpsStrip } from "@/app/components/OpsPanel";
import { Spark } from "@/app/components/Bars";

function SectionHead({ title, href }: { title: string; href: string }) {
  return (
    <div className="flex items-center justify-between border-b border-line px-4 py-3">
      <h2 className="text-[13.5px] font-semibold text-fg">{title}</h2>
      <a href={href} className="flex items-center gap-0.5 text-[12px] text-fg-muted transition-colors hover:text-signal">
        View all <IconChevron className="h-3.5 w-3.5" />
      </a>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-10 text-center text-[13px] text-fg-faint">{children}</div>;
}

/** Top open clusters as count-proportional bars — the dashboard's "what should I work on next".
 *  A cluster is already a ranked pile of identical failures, so the bar length IS the priority. */
function TopClusters({ clusters }: { clusters: FailureCluster[] }) {
  // "OPEN" is the only untriaged state — a cluster becomes "PROMOTED" once it has a regression
  // case, at which point it's handled and no longer work to pick up (see repositories.py).
  const top = clusters
    .filter((c) => c.status === "OPEN")
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
  if (top.length === 0) return null;

  const max = Math.max(1, ...top.map((c) => c.count));
  return (
    <section className="reveal card overflow-hidden" style={{ animationDelay: "200ms" }}>
      <SectionHead title="Biggest failure clusters" href="/clusters" />
      <div className="space-y-3 px-4 py-4">
        {top.map((c) => (
          <a key={c.id} href={`/clusters/${c.id}`} className="group block">
            <div className="flex items-baseline justify-between gap-3">
              <span className="truncate text-[13px] text-fg transition-colors group-hover:text-signal">
                {c.label || c.signature}
              </span>
              <span className="shrink-0 font-mono text-[11px] text-fg-faint">
                {c.taxonomy ? `${c.taxonomy} · ` : ""}
                {c.count} {c.count === 1 ? "trace" : "traces"}
              </span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink-900">
              <div className="h-full rounded-full bg-fail/60" style={{ width: `${(c.count / max) * 100}%` }} />
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}

export default async function Dashboard() {
  const [stats, traces, cases, trends, clusters] = await Promise.all([
    getStats(),
    getTraces(),
    getCases(),
    getTrends(14),
    getClusters(),
  ]);
  // 14-day shape behind the headline counts — a count with no direction can't tell you if it's
  // getting worse, which is the only question a dashboard number is really asked. Under three
  // days there is no shape to show, and a one-point spark just renders as a solid block.
  const spark = (values: number[], stroke: string, fill: string) =>
    values.length < 3 ? undefined : (
      <Spark series={[{ values, stroke, fill, label: "" }]} height={30} grid={false} />
    );
  const volume = trends.daily.map((d) => d.traces);
  const failures = trends.daily.map((d) => d.failures);

  return (
    <div className="space-y-8">
      <header className="reveal">
        <h1 className="font-display text-[27px] font-extrabold tracking-tight">Dashboard</h1>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          Production traces become regression tests — detect a failure, promote it, gate it forever.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Traces"
          value={stats.traces}
          sub={`${stats.spans} spans`}
          chart={spark(volume, "stroke-signal", "fill-signal/10")}
          delay={0}
        />
        <StatCard
          label="Failure clusters"
          value={stats.open_clusters}
          accent={stats.open_clusters ? "text-warn" : "text-fg"}
          sub="open · to triage"
          delay={60}
        />
        <StatCard
          label="Auto failures"
          value={stats.auto_failures}
          accent={stats.auto_failures ? "text-fail" : "text-fg"}
          sub="auto-detected, incl. silent"
          chart={spark(failures, "stroke-fail", "fill-fail/10")}
          delay={120}
        />
        <StatCard label="Regression cases" value={stats.cases} accent="text-signal" sub="forever-running" delay={180} />
      </div>

      <OpsStrip />

      <TopClusters clusters={clusters} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="reveal card overflow-hidden" style={{ animationDelay: "220ms" }}>
          <SectionHead title="Recent traces" href="/traces" />
          {traces.length === 0 ? (
            <Empty>No traces yet — send one with the SDK or OTLP.</Empty>
          ) : (
            traces.slice(0, 6).map((t) => (
              <a
                key={t.trace_id}
                href={`/traces/${t.trace_id}`}
                className="flex items-center justify-between border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-white/[0.025]"
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${t.has_error ? "bg-fail" : "bg-ok"}`} />
                  <span className="truncate text-[13px] text-fg">{t.root_name || "trace"}</span>
                </span>
                <span className="flex shrink-0 items-center gap-3 font-mono text-[11px] text-fg-faint">
                  <span>{t.spans} spans</span>
                  {t.has_error ? <Badge variant="fail">error</Badge> : null}
                </span>
              </a>
            ))
          )}
        </section>

        <section className="reveal card overflow-hidden" style={{ animationDelay: "280ms" }}>
          <SectionHead title="Regression cases" href="/cases" />
          {cases.length === 0 ? (
            <Empty>No cases yet — promote a failing trace.</Empty>
          ) : (
            cases.slice(0, 6).map((c) => (
              <a
                key={c.id}
                href={`/cases/${c.id}`}
                className="flex items-center justify-between border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-white/[0.025]"
              >
                <span className="truncate text-[13px] text-fg">{c.title || "case"}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {c.last_verdict && <Badge variant={verdictVariant(c.last_verdict)}>{c.last_verdict}</Badge>}
                  <Badge variant={statusVariant(c.status)} dot>
                    {c.status}
                  </Badge>
                </span>
              </a>
            ))
          )}
        </section>
      </div>
    </div>
  );
}
