import { DocLink } from "@/app/components/DocLink";
import { getCases, getClusters, getEvaluators, getGates, getStats, getTraces, getTrends, type FailureCluster } from "@/app/lib/api";
import { getMe } from "@/app/lib/auth";
import { Activation } from "@/app/components/Activation";
import { Badge, StatCard, statusVariant, verdictVariant } from "@/app/components/ui";
import { IconChevron } from "@/app/components/icons";
import { OpsStrip } from "@/app/components/OpsPanel";
import { Spark } from "@/app/components/Bars";
import { ClusterMeter, TaxonomyChip, clusterTone, compactCount } from "@/app/components/ClusterMeter";

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

/** Top open clusters as count-proportional meters — the dashboard's "what should I work on
 *  next". A cluster is already a ranked pile of identical failures, so the meter IS the
 *  priority; the colour is the failure family, so the pile is legible before it is read. */
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
      <div className="space-y-1 p-2">
        {top.map((c) => {
          const tone = clusterTone(c.taxonomy);
          return (
            <a
              key={c.id}
              href={`/clusters/${c.id}`}
              className="group flex gap-3.5 rounded-lg px-2.5 py-2.5 transition-colors hover:bg-hilite/[0.03]"
            >
              <span className="flex w-10 shrink-0 flex-col items-end pt-px leading-none" title={`${c.count} traces`}>
                <span className={`font-display text-[21px] font-extrabold tabular-nums ${tone.text}`}>
                  {compactCount(c.count)}
                </span>
                <span className="mt-1 font-mono text-[9px] uppercase tracking-wider text-fg-faint">
                  {c.count === 1 ? "trace" : "traces"}
                </span>
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-2">
                {/* clamped to two lines, not one: these labels are LLM-written sentences, and
                    truncating every one at the same column makes five rows look identical. */}
                <span className="line-clamp-2 text-[13px] leading-snug text-fg-muted transition-colors group-hover:text-fg">
                  {c.label || c.signature}
                </span>
                <span className="flex items-center gap-2.5">
                  <ClusterMeter value={c.count} max={max} tone={tone} className="min-w-0 flex-1" />
                  <TaxonomyChip taxonomy={c.taxonomy ?? ""} tone={tone} />
                </span>
              </span>
            </a>
          );
        })}
      </div>
    </section>
  );
}

export default async function Dashboard() {
  // The dashboard only ever renders the top few of each list, so it asks for exactly that many
  // instead of pulling every case and cluster in the project to slice 6 off the front. The big
  // numbers above come from `getStats()`, which counts server-side.
  const [stats, traces, casesPage, trends, clustersPage, evaluators, gatesPage, me] = await Promise.all([
    getStats(),
    getTraces(),
    getCases(6),
    getTrends(14),
    getClusters(undefined, 6),
    getEvaluators(),
    getGates(1),
    getMe(),
  ]);
  const cases = casesPage.items;
  const clusters = clustersPage.items;
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
        <div className="flex items-center gap-3"><h1 className="font-display text-[27px] font-extrabold tracking-tight">Dashboard</h1><DocLink path="/product/dashboard" /></div>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          Production traces become regression tests — detect a failure, promote it, gate it forever.
        </p>
      </header>

      {/* Shown until the loop has been closed once; every step reads a real count. */}
      <Activation
        traces={stats.traces}
        evaluators={evaluators.length}
        failures={stats.auto_failures}
        clusters={stats.open_clusters}
        cases={stats.cases}
        gates={gatesPage.total}
        ingestKey={me?.ingest_keys?.[0] ?? "<your-ingest-key>"}
        endpoint={process.env.NEXT_PUBLIC_TRACELY_PUBLIC_API ?? "http://localhost:8000"}
      />

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
                className="flex items-center justify-between border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-hilite/[0.025]"
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
                className="flex items-center justify-between border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-hilite/[0.025]"
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
