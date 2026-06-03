import { getTrace } from "../../lib/api";
import { PromoteButton } from "../../components/PromoteButton";
import { Waterfall } from "../../components/Waterfall";
import { Badge } from "../../components/ui";
import { IconArrowLeft } from "../../components/icons";

export default async function TracePage({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  const { spans } = await getTrace(traceId);
  const hasError = spans.some((s) => s.level === "ERROR");
  const root = spans.find((s) => s.parent_span_id === "") ?? spans[0];

  const durations = spans
    .map((s) => (s.end_time ? new Date(s.end_time).getTime() - new Date(s.start_time).getTime() : 0))
    .filter((n) => n >= 0);
  const t0 = spans.length ? Math.min(...spans.map((s) => new Date(s.start_time).getTime())) : 0;
  const t1 = spans.length ? Math.max(...spans.map((s) => new Date(s.end_time ?? s.start_time).getTime())) : 0;
  const totalMs = Math.max(...durations, t1 - t0, 0);

  return (
    <div className="space-y-6">
      <header className="reveal space-y-4">
        <a href="/traces" className="inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors hover:text-signal">
          <IconArrowLeft className="h-4 w-4" /> Traces
        </a>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-display text-[24px] font-extrabold tracking-tight">{root?.name ?? "trace"}</h1>
              {hasError ? <Badge variant="fail" dot>error</Badge> : <Badge variant="ok" dot>ok</Badge>}
            </div>
            <div className="mt-2 flex items-center gap-4 font-mono text-[11.5px] text-fg-faint">
              <span>{traceId.slice(0, 22)}…</span>
              <span>{spans.length} spans</span>
              <span>{totalMs < 1000 ? `${Math.round(totalMs)}ms` : `${(totalMs / 1000).toFixed(2)}s`}</span>
            </div>
          </div>
          {hasError && <PromoteButton traceId={traceId} />}
        </div>
      </header>

      <div className="reveal" style={{ animationDelay: "100ms" }}>
        <Waterfall spans={spans} />
      </div>
    </div>
  );
}
