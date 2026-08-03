"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// How long to keep looking before calling it empty. A scenario turn is a real HTTP call to the
// customer's agent, and a multi-turn conversation with a slow model runs into minutes.
const GIVE_UP_MS = 5 * 60_000;
const EVERY_MS = 2_000;

/** The empty state for a conversation that may not exist YET.
 *
 *  A scenario run returns its conversation id the moment the work is queued, so the page opens
 *  before the first turn has been driven. Rendering "Thread not found." there is wrong twice: it
 *  is not true, and it teaches you to hit reload — which was the actual complaint. So poll, and
 *  refresh the server component the moment something lands.
 *
 *  Only say "not found" once we have genuinely stopped looking. A thread id that really is bogus
 *  reaches the same message, just later, and the cost of being slow to say "no" is far lower than
 *  the cost of saying it while the answer is on its way.
 */
export function AwaitingTurns({ threadId }: { threadId: string }) {
  const router = useRouter();
  const [gaveUp, setGaveUp] = useState(false);
  const [waitedMs, setWaited] = useState(0);

  useEffect(() => {
    let live = true;
    const started = Date.now();
    const timer = setInterval(async () => {
      if (!live) return;
      const elapsed = Date.now() - started;
      setWaited(elapsed);
      if (elapsed > GIVE_UP_MS) {
        setGaveUp(true);
        clearInterval(timer);
        return;
      }
      try {
        const r = await fetch(`/api/sessions/${encodeURIComponent(threadId)}`, {
          cache: "no-store",
        });
        const d = await r.json().catch(() => null);
        if (live && d?.turns?.length) {
          clearInterval(timer);
          router.refresh(); // re-render the server component with the turns attached
        }
      } catch {
        /* a blip while the run is in flight is not an answer — keep looking */
      }
    }, EVERY_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [threadId, router]);

  if (gaveUp) {
    return (
      <div className="card p-10 text-center text-[13px] text-fg-faint">
        Thread not found — nothing arrived for this id.
      </div>
    );
  }

  return (
    <div className="card flex flex-col items-center gap-3 p-10 text-center">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-signal/30 border-t-signal" />
      <p className="text-[13px] text-fg-muted">Waiting for the first turn…</p>
      <p className="text-[11.5px] text-fg-faint">
        Each turn is a live call to your agent, so this can take a moment. The conversation appears
        here on its own — no need to reload.
        {waitedMs > 30_000 && (
          <>
            <br />
            Still nothing after {Math.round(waitedMs / 1000)}s — if the endpoint is failing, the
            first turn will land as an <span className="text-fail">ERROR</span> turn with the HTTP
            status on it.
          </>
        )}
      </p>
    </div>
  );
}
