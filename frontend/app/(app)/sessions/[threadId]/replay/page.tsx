import { ConversationHeader, ConversationTabs, EvalsPill } from "@/app/components/ConversationChrome";
import { ConversationStage } from "@/app/components/replay/ConversationStage";
import { loadConversation } from "@/app/lib/conversation";

export const metadata = { title: "Replay · Tracely" };

export default async function ReplayPage({ params }: { params: Promise<{ threadId: string }> }) {
  const { threadId } = await params;
  const thread = decodeURIComponent(threadId);
  const { turns, usage, agentRef, spans, verdict } = await loadConversation(thread);
  return (
    <div className="space-y-6">
      <ConversationHeader threadId={thread} turns={turns.length} usage={usage}
        agentRef={agentRef} firstInput={turns[0]?.input ?? ""} />
      <ConversationTabs threadId={thread} active="replay" spans={spans}
        right={<EvalsPill threadId={thread} verdict={verdict} />} />
      <ConversationStage threadId={thread} />
    </div>
  );
}
