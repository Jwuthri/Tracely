import type { Metadata } from "next";
import Link from "next/link";

import { DOCS_URL, GITHUB_URL, SITE_URL } from "@/app/lib/site";
import { PageShell, prose } from "../_components/PageShell";

// Target: "llm as a judge" (2,400/mo, KD 31) + "llm judge" (260) + "what is llm as a judge" (110)
// + "llm as judge evaluation" (50). The biggest term in the category.
//
// The SERP is definitional: Wikipedia, an arxiv survey, Langfuse docs at #2, vendor guides. To
// compete we need a genuinely complete explainer, not a pitch. Our differentiated angle is the
// section nobody else on page 1 covers properly — how do you know the judge itself is right?
// (hamel.dev ranks #20 on exactly that, and Tracely ships judge calibration as a feature.)
//
// Same rules as the other content pages: competitor claims verified against live docs, opinions
// labelled, and nothing listed as someone else's downside that Tracely also does.

export const metadata: Metadata = {
  title: { absolute: "LLM-as-a-Judge: How It Works, Where It Fails, How to Trust It" },
  description:
    "A practical guide to LLM-as-a-judge evaluation: how it works, the biases that break it, prompt patterns that hold up, and how to calibrate a judge against human labels before it gates a release.",
  alternates: { canonical: "/llm-as-a-judge" },
  openGraph: {
    title: "LLM-as-a-Judge: How It Works, Where It Fails, How to Trust It",
    description:
      "How LLM-as-a-judge evaluation works, the biases that break it, and how to calibrate a judge before you trust it.",
    url: `${SITE_URL}/llm-as-a-judge`,
    type: "article",
  },
};

const JSON_LD = [
  {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "LLM-as-a-Judge: How It Works, Where It Fails, How to Trust It",
    description:
      "How LLM-as-a-judge evaluation works, the biases that break it, prompt patterns that hold up, and how to calibrate a judge against human labels.",
    url: `${SITE_URL}/llm-as-a-judge`,
    datePublished: "2026-08-12",
    dateModified: "2026-08-12",
    author: { "@type": "Organization", name: "Tracely", url: SITE_URL },
    publisher: { "@type": "Organization", name: "Tracely", url: SITE_URL },
  },
  {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Tracely", item: SITE_URL },
      { "@type": "ListItem", position: 2, name: "LLM evaluation", item: `${SITE_URL}/llm-evaluation` },
      { "@type": "ListItem", position: 3, name: "LLM-as-a-judge", item: `${SITE_URL}/llm-as-a-judge` },
    ],
  },
  {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: [
      {
        "@type": "Question",
        name: "What is LLM-as-a-judge?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "LLM-as-a-judge is an evaluation method where a language model scores the output of another model or agent against criteria written in plain language. It exists because most qualities worth measuring — groundedness, tone, whether a task was actually completed — cannot be asserted with string equality, and human review does not scale to production traffic.",
        },
      },
      {
        "@type": "Question",
        name: "Is LLM-as-a-judge reliable?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Only once you have measured it. Judges exhibit known biases: position bias in pairwise comparisons, verbosity bias toward longer answers, self-preference toward output from their own model family, and score clustering on numeric scales. A judge becomes trustworthy when you label a sample of runs by hand, compare its verdicts against those labels, and track agreement over time.",
        },
      },
      {
        "@type": "Question",
        name: "Should an LLM judge use a numeric score or pass/fail?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Prefer binary pass/fail, or a scale with at most three points and an explicit definition of each. Models cluster scores heavily on 1-10 scales — the difference between a 6 and a 7 is usually noise rather than signal, and it is not reproducible between runs. If you need granularity, decompose the rubric into several binary criteria and count how many pass.",
        },
      },
      {
        "@type": "Question",
        name: "Which model should I use as the judge?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Use a strong model from a different family than the one being evaluated, to limit self-preference bias. The judge does not need to be able to produce the answer, only to assess it against a rubric, so a mid-tier model with a well-written rubric often outperforms a frontier model with a vague one. Keep the judge model pinned — silently upgrading it changes your historical baseline.",
        },
      },
    ],
  },
];

const BIASES = [
  {
    name: "Position bias",
    what: "In pairwise comparisons, judges favour whichever response came first.",
    fix: "Run both orderings and keep the result only when they agree — or avoid pairwise entirely and score against an absolute rubric.",
  },
  {
    name: "Verbosity bias",
    what: "Longer, more confident-sounding answers score higher whether or not they are more correct.",
    fix: "State length expectations in the rubric, and score correctness separately from completeness.",
  },
  {
    name: "Self-preference",
    what: "A judge rates output from its own model family more generously.",
    fix: "Judge with a different family than the one under test. Never let a model grade its own homework.",
  },
  {
    name: "Score clustering",
    what: "On a 1–10 scale, almost everything lands on 7 or 8. The distribution carries little information.",
    fix: "Use binary pass/fail, or decompose into several binary criteria and count passes.",
  },
  {
    name: "Rubric sensitivity",
    what: "Small rewordings of the prompt move verdicts more than real quality differences do.",
    fix: "Version the rubric like code and re-check agreement whenever it changes.",
  },
];

export default function Page() {
  return (
    <PageShell>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }} />

      {/* ---------------------------------- hero ---------------------------------- */}
      <div className="relative pb-4 pt-2">
        <div className="pointer-events-none absolute left-1/2 top-[-64px] -z-10 h-[480px] w-screen -translate-x-1/2">
          <div className="bg-blueprint absolute inset-0 opacity-60" />
          <div
            className="absolute inset-0"
            style={{ background: "radial-gradient(700px 320px at 50% 0%, rgba(34,211,238,0.16), transparent 70%)" }}
          />
          <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-b from-transparent to-ink-950" />
        </div>
        <div className="relative">
          <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-signal/80">Guide · 2026</p>
          <h1 className="mt-4 font-display text-4xl font-bold leading-[1.08] tracking-tight text-fg sm:text-[54px]">
            LLM-as-a-judge, and{" "}
            <span className="text-gradient-cyan">how to know it&apos;s right</span>
          </h1>
          <p className="mt-6 text-lg leading-relaxed text-fg-muted">
            Using a language model to score another model&apos;s output is the only practical way to
            measure the things that matter. It&apos;s also a model, which means it can be confidently
            wrong. Here&apos;s how it works, the biases that break it, and the step most teams skip.
          </p>
        </div>
      </div>

      {/* --------------------------------- what is -------------------------------- */}
      <h2 className={prose.h2}>What LLM-as-a-judge is</h2>
      <p className={prose.p}>
        A judge is a language model given three things: the output to assess, criteria written in plain
        language, and a required response format. It returns a verdict — pass or fail, a score, a label —
        that gets attached to the run as a score you can filter, chart and alert on.
      </p>
      <p className={prose.p}>
        It exists because the interesting properties resist assertion. You can assert that JSON parses.
        You cannot assert that an answer is grounded in the retrieved documents, that the tone suits a
        frustrated customer, or that a six-step agent actually resolved the request. Human review can
        judge all three and doesn&apos;t scale past a sample. A model judge is the compromise: worse than
        a careful human, available on every single run.
      </p>

      <div className="mt-7 rounded-xl border border-line bg-ink-900/50 p-6">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-signal/80">The mechanics</p>
        <ol className="mt-4 space-y-2.5 text-fg-muted">
          <li>
            <strong className="text-fg">1.</strong> Take the run&apos;s input, output, and any context it
            used.
          </li>
          <li>
            <strong className="text-fg">2.</strong> Fill a rubric template with them.
          </li>
          <li>
            <strong className="text-fg">3.</strong> Ask a model for a verdict in a fixed schema — reasoning
            first, verdict last.
          </li>
          <li>
            <strong className="text-fg">4.</strong> Write the verdict back onto the run as a score.
          </li>
        </ol>
      </div>

      {/* ------------------------------- when to use ------------------------------ */}
      <h2 className={prose.h2}>Use it only for what you can&apos;t assert</h2>
      <p className={prose.p}>
        A judge costs tokens, adds latency, and introduces a second source of error. Anything a
        deterministic check can catch should be caught by one: valid JSON, schema conformance, required
        fields present, forbidden strings absent, latency and cost inside budget. Those are free,
        instant and perfectly reliable.
      </p>
      <p className={prose.p}>
        Reach for a judge when the property is genuinely semantic — groundedness against retrieved
        context, faithfulness to a source document, tone, refusal appropriateness, task completion. Two
        or three good judges beat twelve mediocre ones, and every extra judge is another thing that can
        drift.
      </p>

      {/* --------------------------------- biases --------------------------------- */}
      <h2 className={prose.h2}>The five ways judges go wrong</h2>
      <p className={prose.p}>
        These are well documented and they are not edge cases. Each has a cheap mitigation.
      </p>
      <div className="mt-6 space-y-3">
        {BIASES.map((b) => (
          <div key={b.name} className="rounded-xl border border-line bg-ink-900/40 p-5">
            <p className="font-display text-lg font-bold text-fg">{b.name}</p>
            <p className="mt-2 leading-relaxed text-fg-muted">{b.what}</p>
            <p className="mt-2.5 leading-relaxed text-fg-faint">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ok">Mitigation</span>{" "}
              {b.fix}
            </p>
          </div>
        ))}
      </div>

      {/* --------------------------------- prompts -------------------------------- */}
      <h2 className={prose.h2}>Rubric patterns that hold up</h2>
      <ul className={prose.ul}>
        <li>
          <strong className="text-fg">Reasoning before verdict.</strong> Make the judge state why, then
          decide. A verdict-first schema is a coin flip with a justification bolted on afterwards.
        </li>
        <li>
          <strong className="text-fg">One criterion per judge.</strong> &ldquo;Is this helpful, accurate
          and well-formatted?&rdquo; produces a verdict you can&apos;t act on. Three judges produce three
          you can.
        </li>
        <li>
          <strong className="text-fg">Define failure, not just success.</strong> Concrete examples of what
          a FAIL looks like move agreement more than any amount of describing PASS.
        </li>
        <li>
          <strong className="text-fg">Give it the context the run had.</strong> A groundedness judge
          without the retrieved documents is guessing, and will confidently tell you the answer was
          grounded.
        </li>
        <li>
          <strong className="text-fg">Pin the model and version the rubric.</strong> Both are inputs to
          your baseline. Changing either silently invalidates every historical comparison.
        </li>
        <li>
          <strong className="text-fg">Allow abstention.</strong> A judge that must answer will invent a
          verdict on a run it can&apos;t assess. Let it skip — and make sure your roll-up treats a skip as
          &ldquo;not evaluated&rdquo; rather than &ldquo;passed&rdquo;.
        </li>
      </ul>

      {/* --------------------------------- levels --------------------------------- */}
      <h2 className={prose.h2}>Judge the right thing</h2>
      <p className={prose.p}>
        A rubric can be perfect and still miss the bug, because the judge was pointed at the wrong scope.
        An agent that calls a refund API, receives a timeout, and then tells the customer the refund went
        through has <em>no bad span</em> — the call was correct, the reply was fluent. The failure exists
        only in the sequence.
      </p>
      <p className={prose.p}>
        So check what your tooling can target before you trust a green dashboard. A judge scoped to a
        single observation cannot see a trajectory failure no matter how good the rubric is. Tracely
        judges at conversation, run or span level as a field on the evaluator; more on why the level
        decides what you catch in our{" "}
        <Link
          className="text-signal underline decoration-signal/30 underline-offset-4 transition hover:decoration-signal"
          href="/llm-evaluation"
        >
          guide to LLM evaluation
        </Link>
        , and how the tools differ in{" "}
        <Link
          className="text-signal underline decoration-signal/30 underline-offset-4 transition hover:decoration-signal"
          href="/langfuse-alternatives"
        >
          our Langfuse comparison
        </Link>
        .
      </p>

      {/* ------------------------------- calibration ------------------------------ */}
      <h2 className={prose.h2}>The step almost everyone skips: calibrate the judge</h2>
      <p className={prose.p}>
        Everything above improves a judge. None of it tells you whether the judge is <em>right</em>. For
        that there is exactly one method: label a sample of runs by hand, compare against what the judge
        said, and measure agreement.
      </p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-fail/25 bg-fail-dim/25 p-5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-fail">False pass</p>
          <p className="mt-3 leading-relaxed text-fg-muted">
            The judge said PASS, the human said FAIL. A real bug reached a real user and your dashboard
            stayed green.
          </p>
          <p className="mt-3 leading-relaxed text-fg-faint">The expensive error. Optimise against this.</p>
        </div>
        <div className="rounded-xl border border-warn/25 bg-warn-dim/25 p-5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-warn">False fail</p>
          <p className="mt-3 leading-relaxed text-fg-muted">
            The judge said FAIL, the human said PASS. Over-flagging that trains the team to ignore the
            signal.
          </p>
          <p className="mt-3 leading-relaxed text-fg-faint">
            The insidious error. It kills the practice rather than the release.
          </p>
        </div>
      </div>
      <p className={prose.p}>
        Fifty labelled runs per evaluator is enough to see whether a judge is usable. Do it before a
        judge is allowed to block a deploy — a gate built on an uncalibrated judge is worse than no gate,
        because it converts an unknown risk into false confidence. Then re-check whenever you change the
        rubric or the model.
      </p>
      <p className={prose.p}>
        This is the part of the workflow we think is most underserved, so it&apos;s built into Tracely:
        label verdicts in the UI, get per-evaluator agreement with false-pass and false-fail broken out,
        and see an over-flagging judge before it gates anything.
      </p>

      {/* ---------------------------------- close --------------------------------- */}
      <h2 className={prose.h2}>A working checklist</h2>
      <ol className="mt-5 space-y-3 text-fg-muted">
        {[
          "Exhaust deterministic checks first — a judge should never be asked whether JSON parses.",
          "Write two or three judges, one criterion each, reasoning before verdict.",
          "Use a judge model from a different family than the system under test, and pin it.",
          "Prefer binary verdicts over numeric scores.",
          "Point each judge at the right level — conversation, run or span.",
          "Label ~50 runs by hand and measure agreement before trusting it.",
          "Only then let a judge gate a release.",
        ].map((step, i) => (
          <li key={i} className="flex gap-3.5 leading-relaxed">
            <span className="mt-0.5 grid h-6 w-6 flex-none place-items-center rounded-full border border-line-bright bg-ink-900 font-mono text-[11px] text-signal">
              {i + 1}
            </span>
            <span>{step}</span>
          </li>
        ))}
      </ol>

      <div className="mt-14 rounded-2xl border border-signal/30 bg-signal/[0.06] p-7">
        <p className="font-display text-2xl font-bold text-fg">Judges, calibration and the gate — for $0</p>
        <p className="mt-3 leading-relaxed text-fg-muted">
          Tracely is MIT-licensed with no paywalled internals: self-host the whole product free, or use
          the hosted free tier. Judges run on your own model key, so we never take a cut of inference.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <a
            className="inline-flex items-center gap-2 rounded-full bg-signal px-5 py-2.5 text-sm font-semibold text-ink-950 transition hover:bg-signal-soft hover:shadow-glow"
            href="/dashboard"
          >
            Start free
          </a>
          <a
            className="inline-flex items-center gap-2 rounded-full border border-line-bright/70 bg-white/[0.04] px-5 py-2.5 text-sm font-medium text-fg transition hover:bg-white/[0.08]"
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
          >
            Self-host it
          </a>
          <a
            className="inline-flex items-center gap-2 rounded-full border border-line-bright/70 bg-white/[0.04] px-5 py-2.5 text-sm font-medium text-fg transition hover:bg-white/[0.08]"
            href={`${DOCS_URL}/evaluations`}
            target="_blank"
            rel="noreferrer"
          >
            Evaluator docs
          </a>
        </div>
      </div>
    </PageShell>
  );
}
