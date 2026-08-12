import type { Metadata } from "next";
import Link from "next/link";

import { SITE_URL } from "@/app/lib/site";
import { PageShell, prose } from "../_components/PageShell";

// Target query: "langfuse alternatives" (140/mo, KD 0, $36.73 CPC — see SEO.md).
// The SERP is entirely listicles, so a single-vendor pitch page would mismatch intent. This is a
// comparison with a stated point of view.
//
// EVERY factual claim about a competitor on this page is verified against their live docs, not
// against our design dossier (which was reverse-engineered from Langfuse v3.177.1 and is now stale
// — they have since shipped CI/CD experiments). Opinions are labelled as opinions. If you edit
// this page, keep that split: a false claim here costs more than the page earns.
//
// AND: before listing something as a competitor's trade-off, check we don't do the same thing.
// "Self-hosting means ClickHouse + Postgres + Redis + S3" was on this page as a Langfuse downside
// until someone noticed that is *exactly* Tracely's stack (see CLAUDE.md, "Five stores"). A reader
// who spots that stops believing the rest of the page. Shared cost is not a differentiator.
export const metadata: Metadata = {
  title: { absolute: "Langfuse Alternatives (2026): 6 Options, One Opinion" },
  description:
    "LangSmith, Braintrust, Arize Phoenix, Helicone and Tracely compared against Langfuse — where its evaluation model breaks down for agents, and when it's still the right call.",
  alternates: { canonical: "/langfuse-alternatives" },
  openGraph: {
    title: "Langfuse Alternatives (2026): 6 Options, One Opinion",
    description:
      "Where Langfuse's evaluation model breaks down for AI agents — and the five tools worth considering instead.",
    url: `${SITE_URL}/langfuse-alternatives`,
    type: "article",
  },
};

const TOOLS = [
  {
    name: "Langfuse",
    oss: "MIT core",
    bestFor: "The default. Mature tracing, prompt management with versioning, evaluators, datasets and experiments — and the biggest community here.",
    watchOut:
      "Evaluators read one observation in isolation — no conversation-level target. CI experiments need a dataset you author and make live model calls on every run. Prompt management is a large surface to carry if your prompts live in Git.",
    pick: "You want one mature tool for tracing, prompts and evals, and the largest community in the category.",
  },
  {
    name: "LangSmith",
    oss: "Closed",
    bestFor: "The tightest LangChain/LangGraph integration that exists, because they build both.",
    watchOut: "Closed source, no self-host on lower tiers. One vendor owns your framework and your data.",
    pick: "Your stack is LangChain end to end and you'd rather not think about it.",
  },
  {
    name: "Braintrust",
    oss: "Closed",
    bestFor: "A genuinely polished eval and experiment workflow, plus CI deployment blocking.",
    watchOut: "Proprietary storage engine. Eval-centric rather than a general observability backend.",
    pick: "Evaluation quality is the centre of your workflow and hosted is fine.",
  },
  {
    name: "Arize Phoenix",
    oss: "Open source",
    bestFor: "OpenInference-native tracing with notebook-driven analysis.",
    watchOut: "Phoenix is the OSS slice; the deeper platform lives in the commercial Arize product.",
    pick: "You live in Jupyter and want tracing that meets you there.",
  },
  {
    name: "Helicone",
    oss: "Open source",
    bestFor: "One proxy line gets you logging, caching and cost tracking. Fastest setup on this page.",
    watchOut: "Proxy-first means a request-level view — less natural for deep multi-step trajectories.",
    pick: "You want cost and latency visibility today and nothing more.",
  },
  {
    name: "Tracely",
    oss: "MIT, whole product",
    bestFor: "Judges that grade a whole conversation, and production failures that become hermetic CI tests with no dataset to author.",
    watchOut: "Youngest project here, smallest community. No prompt management — deliberately.",
    pick: "The same production failure keeps shipping twice and you're tired of maintaining the test set that was supposed to stop it.",
  },
];

const JSON_LD = [
  {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Tracely", item: SITE_URL },
      {
        "@type": "ListItem",
        position: 2,
        name: "Langfuse alternatives",
        item: `${SITE_URL}/langfuse-alternatives`,
      },
    ],
  },
  {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Is Langfuse open source?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. The Langfuse core is MIT-licensed and can be self-hosted, though some enterprise features are commercially licensed.",
      },
    },
    {
      "@type": "Question",
      name: "Can Langfuse evaluate a whole multi-turn conversation?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Not natively. Langfuse evaluators target a single trace or a single observation, and per their documentation do not load sibling or child observations. Session or conversation-level evaluation is not a distinct evaluation target — the documented workaround is to write a logical root observation that summarises the multi-turn interaction yourself.",
      },
    },
    {
      "@type": "Question",
      name: "Does Langfuse support CI/CD?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes, via CI/CD experiments and a GitHub Action. You create a dataset of test cases, write an experiment script, and raise a RegressionError when a score drops below threshold. The experiment runs your real code, so it makes live model API calls during CI and provider keys must be available as CI secrets.",
      },
    },
    {
      "@type": "Question",
      name: "What is the best open source alternative to Langfuse?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "It depends on the failure you are trying to stop. Arize Phoenix for OpenInference-native tracing, Helicone for gateway-style cost tracking, and Tracely for conversation-level evaluation and turning production failures into hermetic regression tests. For tracing plus prompt management in one mature tool, Langfuse itself is usually still the answer.",
      },
    },
  ],
  },
];

function Verdict({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-ink-900/60 p-5">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-signal/80">{label}</p>
      <p className="mt-2.5 leading-relaxed text-fg-muted">{children}</p>
    </div>
  );
}

export default function Page() {
  return (
    <PageShell>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }} />

      {/* ---------------------------------- hero ---------------------------------- */}
      <div className="relative pb-4 pt-2">
        {/* Full-bleed decoration. Clipped to the 820px column it draws a visible hard-edged box, so
            it breaks out to viewport width — the shell sets overflow-x-clip to absorb the overflow. */}
        <div className="pointer-events-none absolute left-1/2 top-[-64px] -z-10 h-[480px] w-screen -translate-x-1/2">
          <div className="bg-blueprint absolute inset-0 opacity-60" />
          <div
            className="absolute inset-0"
            style={{ background: "radial-gradient(700px 320px at 50% 0%, rgba(34,211,238,0.16), transparent 70%)" }}
          />
          <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-b from-transparent to-ink-950" />
        </div>
        <div className="relative">
          <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-signal/80">Comparison · 2026</p>
          <h1 className="mt-4 font-display text-4xl font-bold leading-[1.08] tracking-tight text-fg sm:text-[56px]">
            Langfuse alternatives,{" "}
            <span className="text-gradient-cyan">with an actual opinion</span>
          </h1>
          <p className="mt-6 text-lg leading-relaxed text-fg-muted">
            We build one of the six tools below, so discount this accordingly. But every listicle you just
            scrolled past ranked its own product first and called it research. This one at least tells you
            where the load-bearing difference is — and where Langfuse still wins.
          </p>
        </div>
      </div>

      {/* --------------------------------- verdict -------------------------------- */}
      <div className="mt-10 grid gap-4 sm:grid-cols-3">
        <Verdict label="The short version">
          Langfuse is a good <em>observability</em> product with evaluation attached. If what you need is
          evaluation of <em>agents</em>, its model fights you.
        </Verdict>
        <Verdict label="The specific reason">
          Its judges read one observation at a time and can&apos;t see the rest of the run. Agent failures
          live in the trajectory, not in a single span.
        </Verdict>
        <Verdict label="When to stay">
          You want prompt management, you value the largest community in the category, and your failures
          are single-call quality problems rather than multi-step ones.
        </Verdict>
      </div>

      {/* ------------------------------ the real gap ------------------------------ */}
      <h2 className={prose.h2}>The one that actually matters: a judge that can&apos;t see the run</h2>
      <p className={prose.p}>
        Every tool here traces, scores and charts. Feature tables blur into each other. So here is the
        difference that changes what you can catch, straight from{" "}
        <a
          className="text-signal underline decoration-signal/30 underline-offset-4 transition hover:decoration-signal"
          href="https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge"
          target="_blank"
          rel="noreferrer"
        >
          Langfuse&apos;s own documentation
        </a>
        : their evaluators target a single trace or a single observation, and they{" "}
        <strong className="text-fg">do not load sibling or child observations</strong>. Conversation-level
        evaluation is not an evaluation target. The documented workaround is to write your own
        &ldquo;logical root observation&rdquo; that summarises the whole interaction, and judge that.
      </p>

      <div className="mt-7 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-fail/25 bg-fail-dim/25 p-5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-fail">One span at a time</p>
          <p className="mt-3 leading-relaxed text-fg-muted">
            The judge sees <code className="font-mono text-[12.5px] text-fg">refund_api</code> returned a
            timeout. That span looks fine in isolation — the tool was called correctly.
          </p>
          <p className="mt-3 leading-relaxed text-fg-faint">
            It cannot see that the agent then told the customer their refund was processed.
          </p>
        </div>
        <div className="rounded-xl border border-ok/25 bg-ok-dim/25 p-5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ok">The whole conversation</p>
          <p className="mt-3 leading-relaxed text-fg-muted">
            A conversation-level judge reads all six turns and fails the run: the agent claimed success
            after a tool error.
          </p>
          <p className="mt-3 leading-relaxed text-fg-faint">
            That&apos;s the bug that reaches the customer. It exists only in the trajectory.
          </p>
        </div>
      </div>

      <p className={prose.p}>
        Tracely runs judges at <strong className="text-fg">conversation, run or span level</strong> — it&apos;s
        a field on the evaluator, not an architecture you work around. If your agents are single-call
        classifiers this is irrelevant and Langfuse is fine. If they take six steps and call four tools,
        it&apos;s most of the failures you care about. We go deeper on the trade-offs in{" "}
        <Link
          className="text-signal underline decoration-signal/30 underline-offset-4 transition hover:decoration-signal"
          href="/llm-evaluation"
        >
          our guide to LLM evaluation
        </Link>
        .
      </p>

      {/* --------------------------------- opinion -------------------------------- */}
      <h2 className={prose.h2}>The part that&apos;s opinion, stated as opinion</h2>
      <p className={prose.p}>
        We think Langfuse&apos;s UI is the weakest part of the product. Dense, closer to a database
        console than a debugging tool, and slow to answer the only question you open it with:{" "}
        <em>which run went wrong, and where?</em> That&apos;s taste, not fact — go look and disagree.
      </p>
      <p className={prose.p}>
        We built Tracely&apos;s trace view around that one question. Evaluator scores are{" "}
        <strong className="text-fg">columns on the trace table</strong>, streaming in live as judges
        finish, so a failing run is something you spot in a list rather than something you go hunting for.
        You&apos;re not clicking through five levels to find out a judge failed; the column is red.
      </p>

      {/* ---------------------------------- table --------------------------------- */}
      <h2 className={prose.h2}>All six, side by side</h2>
      <div className="mt-6 overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[680px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-line bg-ink-900/60">
              <th className="px-4 py-3 font-display font-bold text-fg">Tool</th>
              <th className="px-4 py-3 font-display font-bold text-fg">Licence</th>
              <th className="px-4 py-3 font-display font-bold text-fg">Pick it when</th>
            </tr>
          </thead>
          <tbody>
            {TOOLS.map((t) => (
              <tr key={t.name} className="border-b border-line/50 align-top last:border-0">
                <td className="px-4 py-4 font-semibold text-fg">{t.name}</td>
                <td className="px-4 py-4 font-mono text-[12px] text-fg-faint">{t.oss}</td>
                <td className="px-4 py-4 text-fg-muted">{t.pick}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {TOOLS.map((t) => (
        <div key={t.name} className="mt-9">
          <h3 className="font-display text-xl font-bold tracking-tight text-fg">{t.name}</h3>
          <p className="mt-3 leading-relaxed text-fg-muted">{t.bestFor}</p>
          <p className="mt-2.5 leading-relaxed text-fg-faint">
            <span className="font-mono text-[11px] uppercase tracking-wider text-warn">Trade-off</span>{" "}
            {t.watchOut}
          </p>
        </div>
      ))}

      {/* ------------------------------------ ci ----------------------------------- */}
      <h2 className={prose.h2}>Both of us block bad merges. The difference is what it costs you</h2>
      <p className={prose.p}>
        Langfuse ships CI/CD experiments and they work: create a dataset of test cases, write an
        experiment script, add evaluators, raise a{" "}
        <code className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[12.5px] text-signal-soft">
          RegressionError
        </code>{" "}
        past your threshold, and their GitHub Action fails the job and comments on the PR. Anyone claiming
        Langfuse has no CI story is working from stale information.
      </p>
      <p className={prose.p}>
        Two costs come with it. The dataset is <strong className="text-fg">yours to author and
        maintain</strong> — the failures you thought of, not the ones you had. And the experiment runs
        your real code, so CI makes <strong className="text-fg">live model API calls</strong>: provider
        keys in GitHub secrets, a model bill on every push, and a suite that can go red because an API had
        a bad minute.
      </p>
      <p className={prose.p}>
        Tracely starts from a failure that already happened. A production trace a judge marked FAIL gets
        promoted in one click into a case: recorded input, every tool and model response bundled as
        fixtures, fail-to-pass contract attached. CI replays against those fixtures — no provider keys, no
        model spend, identical result every time. Nobody writes the dataset because production wrote it.
      </p>
      <p className={prose.p}>
        The honest limit: this only tests failures you&apos;ve actually had. For a{" "}
        <em>new</em> capability that has never run in production, a hand-authored dataset is the only
        thing that works — and there, Langfuse does it well.
      </p>

      {/* --------------------------------- switching ------------------------------- */}
      <h2 className={prose.h2}>Trying another one is cheaper than reading about it</h2>
      <p className={prose.p}>
        Langfuse, Phoenix and Tracely all speak OpenTelemetry. If your agent emits OTLP, a second backend
        is an endpoint and a key. Run two in parallel for a week and judge on your own traces rather than
        on anyone&apos;s comparison table — including this one.
      </p>

      <div className="mt-14 rounded-2xl border border-signal/30 bg-signal/[0.06] p-7">
        <p className="font-display text-2xl font-bold text-fg">See it on a failure you actually had</p>
        <p className="mt-3 leading-relaxed text-fg-muted">
          MIT-licensed, self-hostable, free tier hosted. Three lines to instrument. The first frozen case
          is one click, and the gate is two lines of YAML in the workflow you already have.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <a
            className="inline-flex items-center gap-2 rounded-full bg-signal px-5 py-2.5 text-sm font-semibold text-ink-950 transition hover:bg-signal-soft hover:shadow-glow"
            href="/dashboard"
          >
            Start free
          </a>
          <Link
            className="inline-flex items-center gap-2 rounded-full border border-line-bright/70 bg-white/[0.04] px-5 py-2.5 text-sm font-medium text-fg transition hover:bg-white/[0.08]"
            href="/"
          >
            How the loop works
          </Link>
        </div>
      </div>
    </PageShell>
  );
}
