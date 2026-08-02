import { getSession, getTrace, type ConvNode, type FullTurn } from "@/app/lib/api";
import { CopyId } from "@/app/components/CopyId";
import { EvalLevelView } from "@/app/components/EvalLevelView";
import { LEVELS, type EvalLevel } from "@/app/components/eval-levels";
import { IconArrowLeft } from "@/app/components/icons";

// How Tracely graded ONE conversation, split the way the evaluators are: one tab per level.
//
// These runs used to sit in /traces behind an "Evals" chip, where 12 conversations showed up as 42
// extra rows you had to read the title of to know what they graded. They belong to the conversation
// they are about, so that is where they are now — and the recording writes one thread per level
// (`eval:<thread>:step|msg|conv`), which is exactly the three tabs. Batch and sequential columns
// share a level, so they share a tab; the Agent column names the column each row came from.
export default async function ConversationEvalsPage({
  params,
}: {
  params: Promise<{ threadId: string }>;
}) {
  const { threadId } = await params;
  const levels = await Promise.all(LEVELS.map((level) => loadLevel(threadId, level.key)));
  const found = levels.filter((l): l is NonNullable<typeof l> => l !== null);

  return (
    <div className="space-y-6">
      <header className="reveal">
        <a
          href={`/sessions/${encodeURIComponent(threadId)}`}
          className="inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors hover:text-signal"
        >
          <IconArrowLeft className="h-4 w-4" /> Conversation
        </a>
        <h1 className="mt-4 font-display text-[22px] font-extrabold tracking-tight">Evaluations</h1>
        <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11.5px] text-fg-faint">
          <CopyId value={threadId} label="thread id" />
          <span>
            {found.reduce((a, l) => a + l.turns.length, 0)} run
            {found.reduce((a, l) => a + l.turns.length, 0) === 1 ? "" : "s"}
          </span>
        </div>
      </header>

      {found.length === 0 ? (
        <div className="card p-10 text-center text-[13px] text-fg-faint">
          Nothing graded this conversation yet — run the evaluators from the conversation page.
        </div>
      ) : (
        <div className="reveal" style={{ animationDelay: "60ms" }}>
          <EvalLevelView levels={found} />
        </div>
      )}
    </div>
  );
}

/** One level's eval runs as a conversation, or null when that level graded nothing. */
async function loadLevel(
  threadId: string,
  key: EvalLevel,
): Promise<{ key: EvalLevel; conv: ConvNode; turns: FullTurn[] } | null> {
  const evalThread = `eval:${threadId}:${key}`;
  const { turns } = await getSession(encodeURIComponent(evalThread));
  if (turns.length === 0) return null;
  const traces = await Promise.all(turns.map((t) => getTrace(t.trace_id)));
  const fullTurns: FullTurn[] = turns.map((t, i) => ({ ...t, spans: traces[i].spans }));
  return {
    key,
    turns: fullTurns,
    conv: {
      thread: evalThread,
      turns: turns.length,
      first_input: turns[0]?.input ?? null,
      last_output: turns[turns.length - 1]?.output ?? null,
      tokens: turns.reduce((a, t) => a + (t.tokens || 0), 0),
      cost: turns.reduce((a, t) => a + (t.cost || 0), 0),
      first_ts: turns[0]?.ts ?? "",
      last_ts: turns[turns.length - 1]?.ts ?? "",
      last_trace_id: turns[turns.length - 1]?.trace_id ?? evalThread,
      failing: 0,
      turnsData: fullTurns,
      scores: [],
    },
  };
}
