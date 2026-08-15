import { ConversationStage } from "@/app/components/replay/ConversationStage";

export const metadata = { title: "Replay · Tracely" };

export default async function ReplayPage({ params }: { params: Promise<{ threadId: string }> }) {
  const { threadId } = await params;
  return (
    <div className="space-y-6">
      <header className="reveal">
        <h1 className="font-display text-[26px] font-extrabold tracking-tight">Conversation replay</h1>
        <p className="mt-1.5 max-w-2xl text-[14px] text-fg-muted">
          Watch this conversation happen step by step — each agent, the sub-agents it pulls in, and
          every tool and model call, on one clock you can scrub.
        </p>
      </header>
      <ConversationStage threadId={decodeURIComponent(threadId)} />
    </div>
  );
}
