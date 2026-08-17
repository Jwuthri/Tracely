/* Pure logic for the onboarding quest — the gamified tour of every feature. Same philosophy as
   Activation.tsx: anything the product can count is DERIVED from real data (no stored progress
   to drift out of sync); only "go look at a page" steps live in localStorage as visit markers. */

export type QuestStatus = {
  traces: number;
  evaluators: number;
  failures: number;
  clusters: number;
  cases: number;
  gates: number;
  llm_key: boolean;
  ingest_key: string | null;
  endpoint: string;
};

export const EMPTY_STATUS: QuestStatus = {
  traces: 0,
  evaluators: 0,
  failures: 0,
  clusters: 0,
  cases: 0,
  gates: 0,
  llm_key: false,
  ingest_key: null,
  endpoint: "http://localhost:8000",
};

export type QuestLocal = {
  visited: string[];
  key_copied?: boolean;
  llm_skipped?: boolean;
  opened?: boolean;
  celebrated?: boolean;
  dismissed?: boolean;
};

export const EMPTY_LOCAL: QuestLocal = { visited: [] };

export type QuestStep = {
  id: string;
  group: string;
  title: string;
  detail: string;
  href: string;
  cta: string;
  done: boolean;
  /** llm step only: no key, but the user said they don't have one. Counts as complete. */
  skipped?: boolean;
};

/** Which quest marker (if any) a visit to `path` ticks. Order matters: a fleet/replay page is
 *  also a session page, so the more specific suffix wins. */
export function visitMarker(path: string): string | null {
  if (path.startsWith("/trends")) return "trends";
  if (path.startsWith("/settings/api-keys")) return "keys";
  if (path.endsWith("/fleet") || path.endsWith("/replay")) return "fleet";
  if (/^\/(traces|sessions)\/.+/.test(path)) return "trace";
  return null;
}

export function deriveSteps(s: QuestStatus, l: QuestLocal): QuestStep[] {
  const seen = (m: string) => l.visited.includes(m);
  return [
    {
      id: "key",
      group: "Set up",
      title: "Grab your API key",
      detail: "Every SDK call authenticates with this workspace's ingest key — copy it or manage keys in Settings.",
      href: "/settings/api-keys",
      cta: "Manage keys",
      done: !!l.key_copied || seen("keys"),
    },
    {
      id: "llm",
      group: "Set up",
      title: "Connect your OpenRouter key",
      detail: "Powers LLM-judge evaluators, failure clustering and meta-analysis. Structural checks run without it.",
      href: "/settings/llm",
      cta: "Add key",
      done: s.llm_key,
      skipped: !s.llm_key && !!l.llm_skipped,
    },
    {
      id: "trace",
      group: "Set up",
      title: "Send your first trace",
      detail: "pip install the SDK and point it at this workspace — auto-instrumentation does the rest.",
      href: "/dashboard",
      cta: "Get the snippet",
      done: s.traces > 0,
    },
    {
      id: "open",
      group: "Explore",
      title: "Open a trace",
      detail: "Drill into a conversation: every turn, span, tool call and token, accounted for.",
      href: "/traces",
      cta: "Browse traces",
      done: seen("trace"),
    },
    {
      id: "eval",
      group: "Explore",
      title: "Add an evaluator column",
      detail: "Evaluators are the columns of the traces table — every new run gets graded automatically.",
      href: "/traces",
      cta: "+ Add column on Traces",
      done: s.evaluators > 0,
    },
    {
      id: "trends",
      group: "Explore",
      title: "Read your Trends",
      detail: "Daily volume, failure rate, gate pass rate — plus per-agent meta-analysis.",
      href: "/trends",
      cta: "Open Trends",
      done: seen("trends"),
    },
    {
      id: "fleet",
      group: "Explore",
      title: "Watch the Fleet",
      detail: "A conversation replayed as a pixel office — a desk per agent, tools on the wall, delegations walking over.",
      href: "/traces",
      cta: "Open a conversation → Fleet tab",
      done: seen("fleet"),
    },
    {
      id: "fail",
      group: "Close the loop",
      title: "Catch a failure",
      detail: "Ticks itself the first time an evaluator fails a run; similar failures cluster into one issue.",
      href: "/clusters",
      cta: "See failure clusters",
      done: s.failures > 0 || s.clusters > 0,
    },
    {
      id: "case",
      group: "Close the loop",
      title: "Promote a regression case",
      detail: "A failure becomes a fail-to-pass test with the real tool calls recorded — it replays hermetically.",
      href: "/clusters",
      cta: "Promote from a cluster",
      done: s.cases > 0,
    },
    {
      id: "gate",
      group: "Close the loop",
      title: "Gate a pull request",
      detail: "Run the promoted cases against a PR's agent — exits non-zero, so the bug you fixed can't come back.",
      href: "/gates",
      cta: "See gate runs",
      done: s.gates > 0,
    },
  ];
}

export const stepComplete = (st: QuestStep) => st.done || !!st.skipped;

export const XP_PER_STEP = 10;

export function questRank(complete: number, total: number): string {
  const f = total ? complete / total : 0;
  if (f >= 1) return "Trace Master";
  if (f >= 0.7) return "Gate Keeper";
  if (f >= 0.4) return "Trace Detective";
  if (f > 0) return "Observer";
  return "Rookie";
}
