import { getSession, getTrace, type ConvNode, type FullTurn } from "@/app/lib/api";
import { convUsage, fmtUsd } from "@/app/lib/usage";
import { CopyId } from "@/app/components/CopyId";
import { SessionView } from "@/app/components/SessionView";
import { IconArrowLeft } from "@/app/components/icons";

export default async function ThreadPage({ params }: { params: Promise<{ threadId: string }> }) {
  const { threadId } = await params;
  const { turns } = await getSession(threadId);
  // Eagerly resolve each turn's spans so the whole tree renders pre-expanded.
  const traces = await Promise.all(turns.map((t) => getTrace(t.trace_id)));
  const fullTurns: FullTurn[] = turns.map((t, i) => ({ ...t, spans: traces[i].spans }));

  const totalTokens = turns.reduce((a, t) => a + (t.tokens || 0), 0);
  const totalCost = turns.reduce((a, t) => a + (t.cost || 0), 0);
  const failing = turns.some((t) => t.failing === 1 || t.verdict === "FAIL") ? 1 : 0;

  const conv: ConvNode = {
    thread: threadId,
    turns: turns.length,
    first_input: turns[0]?.input ?? null,
    last_output: turns[turns.length - 1]?.output ?? null,
    tokens: totalTokens,
    cost: totalCost,
    first_ts: turns[0]?.ts ?? "",
    last_ts: turns[turns.length - 1]?.ts ?? "",
    last_trace_id: turns[turns.length - 1]?.trace_id ?? threadId,
    failing,
    turnsData: fullTurns,
  };
  const usage = convUsage(conv);

  return (
    <div className="space-y-6">
      <header className="reveal">
        <a href="/traces" className="inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors hover:text-signal">
          <IconArrowLeft className="h-4 w-4" /> Traces
        </a>
        <div className="mt-4">
          <h1 className="font-display text-[22px] font-extrabold tracking-tight">Conversation</h1>
          <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11.5px] text-fg-faint">
            <CopyId value={threadId} label="thread id" />
            <span>{turns.length} turns</span>
            {usage.input_tokens ? <span>{usage.input_tokens.toLocaleString("en-US")} in</span> : null}
            {usage.output_tokens ? <span>{usage.output_tokens.toLocaleString("en-US")} out</span> : null}
            {usage.total_tokens ? <span>{usage.total_tokens.toLocaleString("en-US")} tokens</span> : null}
            {usage.cost ? <span className="text-amber-300/90">{fmtUsd(usage.cost)}</span> : null}
          </div>
        </div>
      </header>

      {turns.length === 0 ? (
        <div className="card p-10 text-center text-[13px] text-fg-faint">Thread not found.</div>
      ) : (
        <div className="reveal" style={{ animationDelay: "60ms" }}>
          <SessionView conv={conv} turns={fullTurns} />
        </div>
      )}
    </div>
  );
}
