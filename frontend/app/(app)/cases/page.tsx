import { getCases, PAGE_SIZE } from "@/app/lib/api";
import { Badge, statusVariant, verdictVariant } from "@/app/components/ui";
import { CopyId } from "@/app/components/CopyId";
import { Pager, pageParam } from "@/app/components/Pager";
import { RowLink } from "@/app/components/RowLink";
import { IconChevron } from "@/app/components/icons";

export default async function CasesPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string }>;
}) {
  const page = pageParam((await searchParams).page);
  const { items: cases, total } = await getCases(PAGE_SIZE, (page - 1) * PAGE_SIZE);
  return (
    <div className="space-y-6">
      <header className="reveal flex items-end justify-between">
        <div>
          <h1 className="font-display text-[26px] font-extrabold tracking-tight">Regression cases</h1>
          <p className="mt-1.5 text-[14px] text-fg-muted">
            Each case is a production trace promoted into a forever-running regression test,
            attached to the agent it came from — <a href="/gates" className="text-signal">the gate</a>{" "}
            replays one agent&apos;s cases at a time.
          </p>
        </div>
        {/* the project-wide count, not this page's — a COUNT(*), so it stays true as the list pages */}
        <Badge variant="signal">{total} cases</Badge>
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
            <RowLink
              key={c.id}
              href={`/cases/${c.id}`}
              className="group grid grid-cols-[1fr_130px_120px_90px_36px] items-center gap-3 border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-hilite/[0.025]"
            >
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-[13.5px] text-fg">{c.title || "case"}</span>
                <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-fg-faint">
                  {c.agent && (
                    <span className="rounded bg-ink-700 px-1.5 py-0.5 text-fg-muted">{c.agent}</span>
                  )}
                  src <CopyId value={c.source_trace_id} label="source trace" />
                </span>
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
            </RowLink>
          ))
        )}
      </div>

      <Pager
        page={page}
        pageSize={PAGE_SIZE}
        total={total}
        label="cases"
        href={(p) => `/cases?page=${p}`}
      />
    </div>
  );
}
