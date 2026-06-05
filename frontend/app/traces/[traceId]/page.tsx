import { getTrace, type ConvNode, type FullTurn } from "../../lib/api";
import { convUsage, fmtUsd } from "../../lib/usage";
import { PromoteButton } from "../../components/PromoteButton";
import { SingleTraceView } from "../../components/SingleTraceView";
import { CopyId } from "../../components/CopyId";
import { Badge } from "../../components/ui";
import { IconArrowLeft } from "../../components/icons";

export default async function TracePage({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  const { spans, scores, eval_verdict } = await getTrace(traceId);
  const hasError = spans.some((s) => s.level === "ERROR");
  const failing = hasError || eval_verdict === "FAIL";
  const root = spans.find((s) => s.parent_span_id === "") ?? spans[0];

  const t0 = spans.length ? Math.min(...spans.map((s) => new Date(s.start_time).getTime())) : 0;
  const t1 = spans.length ? Math.max(...spans.map((s) => new Date(s.end_time ?? s.start_time).getTime())) : 0;
  const totalMs = Math.max(t1 - t0, 0);
  const totalTokens = spans.reduce((a, s) => a + (s.tokens || 0), 0);
  const totalCost = spans.reduce((a, s) => a + (s.cost || 0), 0);

  // Derive the user/assistant text for the turn from the run's root span.
  const input = root?.input ?? spans.find((s) => s.input)?.input ?? null;
  const output =
    root?.output ?? [...spans].reverse().find((s) => s.output && s.type !== "TOOL")?.output ?? null;

  const turn: FullTurn = {
    trace_id: traceId,
    input,
    output,
    tokens: totalTokens,
    cost: totalCost,
    latency_ms: totalMs,
    ts: root?.start_time ?? "",
    failing: failing ? 1 : 0,
    scores,
    verdict: eval_verdict,
    spans,
  };
  const conv: ConvNode = {
    thread: traceId,
    turns: 1,
    first_input: input,
    last_output: output,
    tokens: totalTokens,
    cost: totalCost,
    last_ts: root?.start_time ?? "",
    last_trace_id: traceId,
    failing: failing ? 1 : 0,
    turnsData: [turn],
  };
  const usage = convUsage(conv);

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
              {failing ? (
                <Badge variant="fail" dot>{hasError ? "error" : "failing"}</Badge>
              ) : (
                <Badge variant="ok" dot>ok</Badge>
              )}
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-3 font-mono text-[11.5px] text-fg-faint">
              <CopyId value={traceId} label="trace id" />
              <span>{spans.length} spans</span>
              <span>{totalMs < 1000 ? `${Math.round(totalMs)}ms` : `${(totalMs / 1000).toFixed(2)}s`}</span>
              {usage.input_tokens ? <span>{usage.input_tokens.toLocaleString("en-US")} in</span> : null}
              {usage.output_tokens ? <span>{usage.output_tokens.toLocaleString("en-US")} out</span> : null}
              {usage.total_tokens ? <span>{usage.total_tokens.toLocaleString("en-US")} tokens</span> : null}
              {usage.cost ? <span className="text-amber-300/90">{fmtUsd(usage.cost)}</span> : null}
            </div>
          </div>
          {failing && <PromoteButton traceId={traceId} />}
        </div>
      </header>

      <SingleTraceView conv={conv} spans={spans} scores={scores} verdict={eval_verdict} />
    </div>
  );
}
