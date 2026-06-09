import { getCases, getStats, getTraces } from "@/app/lib/api";
import { Badge, StatCard, statusVariant, verdictVariant } from "@/app/components/ui";
import { IconChevron } from "@/app/components/icons";

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

export default async function Dashboard() {
  const [stats, traces, cases] = await Promise.all([getStats(), getTraces(), getCases()]);
  return (
    <div className="space-y-8">
      <header className="reveal">
        <h1 className="font-display text-[27px] font-extrabold tracking-tight">Dashboard</h1>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          Production traces become regression tests — detect a failure, promote it, gate it forever.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Traces" value={stats.traces} sub={`${stats.spans} spans`} delay={0} />
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
          delay={120}
        />
        <StatCard label="Regression cases" value={stats.cases} accent="text-signal" sub="forever-running" delay={180} />
      </div>

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
