import { getSessions } from "../lib/api";
import { Badge } from "../components/ui";
import { TracesExplorer } from "../components/TracesExplorer";

export default async function TracesPage() {
  const threads = await getSessions();
  const multi = threads.filter((t) => t.turns > 1).length;
  return (
    <div className="space-y-6">
      <header className="reveal flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-[26px] font-extrabold tracking-tight">Traces</h1>
          <p className="mt-1.5 text-[14px] text-fg-muted">
            Agent runs grouped into conversation threads — expand any conversation into its messages and steps.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          {multi > 0 && <Badge variant="signal">{multi} multi-turn</Badge>}
          <Badge variant="neutral">{threads.length} threads</Badge>
        </div>
      </header>

      {threads.length === 0 ? (
        <div className="card px-4 py-14 text-center text-[13px] text-fg-faint">
          No traces yet — send one with the SDK or point an OTLP exporter at{" "}
          <code className="text-fg-muted">/v1/traces</code>.
        </div>
      ) : (
        <TracesExplorer conversations={threads} />
      )}
    </div>
  );
}
