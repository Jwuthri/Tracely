import { getGates, type GateRun } from "@/app/lib/api";
import { Badge } from "@/app/components/ui";
import { RowLink } from "@/app/components/RowLink";
import { RunGateButton } from "@/app/components/RunGateButton";
import { TimeAgo } from "@/app/components/TimeAgo";
import { IconChevron } from "@/app/components/icons";

function gateVariant(s: string): "ok" | "fail" | "info" | "neutral" {
  if (s === "PASS") return "ok";
  if (s === "FAIL") return "fail";
  if (s === "RUNNING") return "info";
  return "neutral";
}

function Counts({ g }: { g: GateRun }) {
  return (
    <span className="flex items-center gap-2.5 font-mono text-[11.5px]">
      <span className="text-ok">{g.passed}✓</span>
      <span className={g.failed ? "text-fail" : "text-fg-faint"}>{g.failed}✗</span>
      <span className="text-fg-faint">{g.skipped}–</span>
    </span>
  );
}

export default async function GatesPage() {
  const gates = await getGates();
  return (
    <div className="space-y-6">
      <header className="reveal flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-[26px] font-extrabold tracking-tight">CI gates</h1>
          <p className="mt-1.5 max-w-2xl text-[14px] text-fg-muted">
            A PR is gated on the agent&apos;s regression suite — every promoted production failure
            must <span className="text-fg">not</span> recur. Runs in CI via the GitHub Action.
          </p>
        </div>
        <RunGateButton agent="planner" />
      </header>

      <div className="reveal card overflow-hidden" style={{ animationDelay: "80ms" }}>
        <div className="grid grid-cols-[92px_1fr_150px_120px_28px] items-center gap-3 border-b border-line bg-ink-900/50 px-4 py-2.5 font-mono text-[10.5px] uppercase tracking-wider text-fg-faint">
          <span>Result</span>
          <span>Agent / ref</span>
          <span>Cases</span>
          <span className="text-right">When</span>
          <span />
        </div>
        {gates.length === 0 ? (
          <div className="px-4 py-14 text-center text-[13px] text-fg-faint">
            No gate runs yet — click <span className="text-fg-muted">Run gate</span>, or wire the
            GitHub Action (<code className="text-fg-muted">.github/workflows/tracely-gate.yml</code>).
          </div>
        ) : (
          gates.map((g) => (
            <RowLink
              key={g.id}
              href={`/gates/${g.id}`}
              className="group grid grid-cols-[92px_1fr_150px_120px_28px] items-center gap-3 border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-white/[0.025]"
            >
              <Badge variant={gateVariant(g.status)} dot>
                {g.status}
              </Badge>
              <span className="flex min-w-0 items-center gap-2 font-mono text-[12.5px]">
                <span className="text-fg">{g.agent}</span>
                <span className="rounded bg-ink-700 px-1.5 py-0.5 text-[10.5px] text-fg-faint">{g.env}</span>
                {g.git_ref && <span className="truncate text-fg-faint">{g.git_ref.slice(0, 8)}</span>}
              </span>
              <Counts g={g} />
              <TimeAgo ts={g.created_at} className="text-right font-mono text-[11.5px] text-fg-faint" />
              <IconChevron className="h-4 w-4 justify-self-end text-fg-faint transition-colors group-hover:text-signal" />
            </RowLink>
          ))
        )}
      </div>
    </div>
  );
}
