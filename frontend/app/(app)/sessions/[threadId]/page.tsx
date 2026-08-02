import { getSession, getTrace, type ConvNode, type FullTurn } from "@/app/lib/api";
import { convUsage, fmtUsd } from "@/app/lib/usage";
import { CopyId } from "@/app/components/CopyId";
import { SaveAsScenarioButton } from "@/app/components/SaveAsScenarioButton";
import { SessionView } from "@/app/components/SessionView";
import { ShareButton } from "@/app/components/ShareButton";
import { IconArrowLeft } from "@/app/components/icons";

export default async function ThreadPage({ params }: { params: Promise<{ threadId: string }> }) {
  const { threadId } = await params;
  const { turns, scores: threadScores } = await getSession(threadId);
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
    scores: threadScores ?? [],
  };
  const usage = convUsage(conv);
  // Importing needs an agent to attach the scenario to. Spans carry the agent id, so read it off
  // the conversation rather than making the page fetch the registry; no agent → no button.
  const agentRef = traces.flatMap((t) => t.spans).find((s) => s.agent_id)?.agent_id ?? "";
  const firstInput = turns[0]?.input ?? "";

  return (
    <div className="space-y-6">
      <header className="reveal">
        <a href="/traces" className="inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors hover:text-signal">
          <IconArrowLeft className="h-4 w-4" /> Traces
        </a>
        <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
          <div>
          <h1 className="font-display text-[22px] font-extrabold tracking-tight">Conversation</h1>
          <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11.5px] text-fg-faint">
            <CopyId value={threadId} label="thread id" />
            <span>{turns.length} turns</span>
            {usage.input_tokens ? <span>{usage.input_tokens.toLocaleString("en-US")} in</span> : null}
            {usage.cached_tokens ? <span>{usage.cached_tokens.toLocaleString("en-US")} cached</span> : null}
            {usage.output_tokens ? <span>{usage.output_tokens.toLocaleString("en-US")} out</span> : null}
            {usage.total_tokens ? <span>{usage.total_tokens.toLocaleString("en-US")} tokens</span> : null}
            {usage.cost ? <span className="text-amber-300/90">{fmtUsd(usage.cost)}</span> : null}
          </div>
          </div>
          <div className="flex items-center gap-3">
            {turns.length > 0 && agentRef && (
              <SaveAsScenarioButton
                threadId={threadId}
                agent={agentRef}
                defaultTitle={firstInput ? `Prod · ${firstInput.slice(0, 70)}` : undefined}
              />
            )}
            {/* Tracely's own grading of THIS conversation. It lives here rather than as rows in
                /traces, where every conversation added one list entry per eval level. */}
            {turns.length > 0 && (
              <a href={`/sessions/${encodeURIComponent(threadId)}/evals`} className="btn-ghost">
                Show evals
              </a>
            )}
            {turns.length > 0 && <ShareButton threadId={threadId} />}
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
