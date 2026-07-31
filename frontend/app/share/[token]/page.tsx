import { notFound } from "next/navigation";

import { getSharedSession, type ConvNode } from "@/app/lib/api";
import { convUsage, fmtUsd } from "@/app/lib/usage";
import { SessionView } from "@/app/components/SessionView";

// Deliberately OUTSIDE the (app) route group: that layout calls requireSession() and renders the
// sidebar/topbar. A share link has no session and no navigation — it is one read-only page.
// `/share/` is also listed in middleware.ts's PUBLIC and isPublicClerk matchers.

export const metadata = {
  title: "Shared conversation · Tracely",
  robots: { index: false, follow: false }, // unlisted, not secret — keep links out of search results
};

export default async function SharedThreadPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const data = await getSharedSession(token);
  if (!data) notFound(); // expired, forged, or deleted — all indistinguishable, by design

  const { thread_id: threadId, turns, scores } = data;
  const conv: ConvNode = {
    thread: threadId,
    turns: turns.length,
    first_input: turns[0]?.input ?? null,
    last_output: turns[turns.length - 1]?.output ?? null,
    tokens: turns.reduce((a, t) => a + (t.tokens || 0), 0),
    cost: turns.reduce((a, t) => a + (t.cost || 0), 0),
    first_ts: turns[0]?.ts ?? "",
    last_ts: turns[turns.length - 1]?.ts ?? "",
    last_trace_id: turns[turns.length - 1]?.trace_id ?? threadId,
    failing: turns.some((t) => t.failing === 1 || t.verdict === "FAIL") ? 1 : 0,
    turnsData: turns,
    scores: scores ?? [],
  };
  const usage = convUsage(conv);

  return (
    <div className="bg-grid min-h-screen">
      <main className="mx-auto w-full max-w-[1240px] px-8 py-8">
        <header className="reveal">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h1 className="font-display text-[22px] font-extrabold tracking-tight">Conversation</h1>
            <span className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-fg-faint">
              Shared via Tracely · read-only
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11.5px] text-fg-faint">
            <span>{turns.length} turns</span>
            {usage.total_tokens ? <span>{usage.total_tokens.toLocaleString("en-US")} tokens</span> : null}
            {usage.cost ? <span className="text-warn/90">{fmtUsd(usage.cost)}</span> : null}
          </div>
        </header>

        <div className="mt-6">
          <SessionView conv={conv} turns={turns} shared />
        </div>
      </main>
    </div>
  );
}
