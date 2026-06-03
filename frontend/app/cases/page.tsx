import { getCases } from "../lib/api";
import { Badge, statusVariant, verdictVariant } from "../components/ui";
import { IconChevron } from "../components/icons";

export default async function CasesPage() {
  const cases = await getCases();
  return (
    <div className="space-y-6">
      <header className="reveal flex items-end justify-between">
        <div>
          <h1 className="font-display text-[26px] font-extrabold tracking-tight">Regression cases</h1>
          <p className="mt-1.5 text-[14px] text-fg-muted">
            Each case is a production trace promoted into a forever-running regression test.
          </p>
        </div>
        <Badge variant="signal">{cases.length} cases</Badge>
      </header>

      <div className="reveal card overflow-hidden" style={{ animationDelay: "80ms" }}>
        <div className="grid grid-cols-[1fr_130px_120px_90px_36px] items-center gap-3 border-b border-line bg-ink-900/50 px-4 py-2.5 font-mono text-[10.5px] uppercase tracking-wider text-fg-faint">
          <span>Case</span>
          <span>Status</span>
          <span>Contract</span>
          <span>Last run</span>
          <span />
        </div>
        {cases.length === 0 ? (
          <div className="px-4 py-14 text-center text-[13px] text-fg-faint">
            No cases yet — open a failing trace and click <span className="text-fg-muted">Promote to regression test</span>.
          </div>
        ) : (
          cases.map((c, i) => (
            <a
              key={c.id}
              href={`/cases/${c.id}`}
              className="group grid grid-cols-[1fr_130px_120px_90px_36px] items-center gap-3 border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-white/[0.025]"
              style={{ animationDelay: `${120 + i * 25}ms` }}
            >
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-[13.5px] text-fg">{c.title || "case"}</span>
                <span className="font-mono text-[10.5px] text-fg-faint">src {c.source_trace_id.slice(0, 12)}…</span>
              </span>
              <span>
                <Badge variant={statusVariant(c.status)} dot>
                  {c.status}
                </Badge>
              </span>
              <span className="font-mono text-[11px]">
                {c.fail_to_pass_validated ? (
                  <span className="text-ok">fail → pass ✓</span>
                ) : (
                  <span className="text-fg-faint">—</span>
                )}
              </span>
              <span>{c.last_verdict ? <Badge variant={verdictVariant(c.last_verdict)}>{c.last_verdict}</Badge> : <span className="font-mono text-[11px] text-fg-faint">—</span>}</span>
              <IconChevron className="h-4 w-4 justify-self-end text-fg-faint transition-colors group-hover:text-signal" />
            </a>
          ))
        )}
      </div>
    </div>
  );
}
