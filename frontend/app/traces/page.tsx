import { getTraces } from "../lib/api";
import { Badge } from "../components/ui";
import { CopyId } from "../components/CopyId";
import { RowLink } from "../components/RowLink";
import { IconChevron } from "../components/icons";

function ago(ts: string): string {
  const d = new Date(ts).getTime();
  if (Number.isNaN(d)) return "";
  const s = Math.max(0, (Date.now() - d) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default async function TracesPage() {
  const traces = await getTraces();
  return (
    <div className="space-y-6">
      <header className="reveal flex items-end justify-between">
        <div>
          <h1 className="font-display text-[26px] font-extrabold tracking-tight">Traces</h1>
          <p className="mt-1.5 text-[14px] text-fg-muted">Every agent run, captured as an OTel trace.</p>
        </div>
        <Badge variant="neutral">{traces.length} runs</Badge>
      </header>

      <div className="reveal card overflow-hidden" style={{ animationDelay: "80ms" }}>
        <div className="grid grid-cols-[1fr_120px_120px_150px_32px] items-center gap-3 border-b border-line bg-ink-900/50 px-4 py-2.5 font-mono text-[10.5px] uppercase tracking-wider text-fg-faint">
          <span>Trace</span>
          <span>Status</span>
          <span className="text-right">Spans</span>
          <span className="text-right">When</span>
          <span />
        </div>
        {traces.length === 0 ? (
          <div className="px-4 py-14 text-center text-[13px] text-fg-faint">
            No traces yet — send one with the SDK or point an OTLP exporter at <code className="text-fg-muted">/v1/traces</code>.
          </div>
        ) : (
          traces.map((t, i) => (
            <RowLink
              key={t.trace_id}
              href={`/traces/${t.trace_id}`}
              className="group grid grid-cols-[1fr_120px_120px_150px_32px] items-center gap-3 border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-white/[0.025]"
            >
              <span className="flex min-w-0 items-center gap-2.5">
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${t.has_error ? "bg-fail" : "bg-ok"}`} />
                <span className="truncate text-[13.5px] text-fg">{t.root_name || "trace"}</span>
                <CopyId value={t.trace_id} label="trace id" />
              </span>
              <span>{t.has_error ? <Badge variant="fail" dot>error</Badge> : <Badge variant="ok" dot>ok</Badge>}</span>
              <span className="text-right font-mono text-[12px] text-fg-muted">{t.spans}</span>
              <span className="text-right font-mono text-[11.5px] text-fg-faint">{ago(t.ts)}</span>
              <IconChevron className="h-4 w-4 justify-self-end text-fg-faint transition-colors group-hover:text-signal" />
            </RowLink>
          ))
        )}
      </div>
    </div>
  );
}
