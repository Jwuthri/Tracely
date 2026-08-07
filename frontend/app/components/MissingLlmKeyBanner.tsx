import Link from "next/link";

import { getLlmKeyConfigured } from "@/app/lib/api";

/** Shown across the app until the workspace sets an OpenRouter key. Without one every LLM-backed
 *  feature is a no-op — evaluators produce no scores, clusters never build — and silence is the
 *  worst way to learn that: the product looks broken rather than unconfigured. */
export async function MissingLlmKeyBanner() {
  if (await getLlmKeyConfigured()) return null;
  return (
    <div className="mx-auto w-full max-w-[1240px] px-8 pt-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-warn/30 bg-warn/10 px-4 py-3 text-[13px] text-warn">
        <span className="font-semibold">No OpenRouter key</span>
        <span className="text-fg-muted">
          LLM evaluators, failure clustering, meta-analysis and scenario gates need your own key
          before they can run. Tracing and structural checks work without it.
        </span>
        <Link href="/settings" className="font-medium text-warn underline underline-offset-2">
          Add a key
        </Link>
      </div>
    </div>
  );
}
