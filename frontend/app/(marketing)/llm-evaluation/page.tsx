import type { Metadata } from "next";
import Link from "next/link";

import { DOCS_URL, GITHUB_URL, SITE_URL } from "@/app/lib/site";
import { PageShell, prose } from "../_components/PageShell";

// Pillar page. Target: "llm evaluation" (1,000/mo, KD 14 — best volume:difficulty ratio we found),
// plus "llm evals" (480), "llm evaluation metrics" (260), "llm evaluation platform" (50).
// Intent is informational, so the guide has to stand on its own — a page that is mostly pitch will
// not rank for a "what is" query. The tools section earns its place by being accurate.
//
// Same rules as /langfuse-alternatives: competitor claims verified against live docs, opinions
// labelled, and nothing listed as someone else's downside that Tracely also does.

export const metadata: Metadata = {
  title: { absolute: "LLM Evaluation: Metrics, Methods and Tools (2026 Guide)" },
  description:
    "How to evaluate LLM and agent outputs: offline vs online evaluation, deterministic checks vs LLM-as-a-judge, the metrics that matter, and the open-source tools to run it.",
  alternates: { canonical: "/llm-evaluation" },
  openGraph: {
    title: "LLM Evaluation: Metrics, Methods and Tools (2026 Guide)",
    description:
      "Offline vs online evaluation, deterministic checks vs LLM-as-a-judge, the metrics that matter, and the tools to run it.",
    url: `${SITE_URL}/llm-evaluation`,
    type: "article",
  },
};

const JSON_LD = [
  {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "LLM Evaluation: Metrics, Methods and Tools",
    description:
      "A practical guide to evaluating LLM and agent outputs — offline vs online evaluation, deterministic checks vs LLM-as-a-judge, evaluation levels, and the tools available.",
    url: `${SITE_URL}/llm-evaluation`,
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
    ],
  },
  {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: [
      {
        "@type": "Question",
        name: "What is LLM evaluation?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "LLM evaluation is the practice of scoring the output of a language model or agent against defined criteria — correctness, groundedness, format, safety, task completion — so that quality can be measured rather than guessed at. Because outputs are open-ended and non-deterministic, evaluation relies on a mix of deterministic checks, model-based judges and human review rather than exact-match assertions.",
        },
      },
      {
        "@type": "Question",
        name: "What is the difference between online and offline LLM evaluation?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Offline evaluation runs against a fixed set of examples before you ship, answering whether a change is better than what you had. Online evaluation scores real production traffic after you ship, answering whether the system is actually working for users. Offline evaluation catches regressions; online evaluation discovers failures nobody predicted. Production teams need both.",
        },
      },
      {
        "@type": "Question",
        name: "What metrics should I use to evaluate an LLM?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Start with deterministic checks that cost nothing: valid JSON, schema conformance, required fields, forbidden strings, latency and cost budgets. Add task-specific model-based judges for the qualities you cannot assert — groundedness, faithfulness to retrieved context, tone, task completion. Avoid generic reference metrics like BLEU or ROUGE for agent output; they correlate poorly with whether the answer was useful.",
        },
      },
      {
        "@type": "Question",
        name: "What is the best open source LLM evaluation tool?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Tracely is MIT-licensed with no paywalled internals and is free to self-host, and evaluates at conversation, run or span level. Langfuse has an MIT core with some commercially licensed enterprise features and the largest community. Arize Phoenix is strong for OpenInference-native tracing and notebook analysis. DeepEval and Ragas are open-source libraries rather than platforms, and are a good fit if you want evaluation in code without a backend.",
        },
      },
    ],
  },
];

const LEVELS = [
  {
    level: "Span",
    q: "Did this one step do its job?",
    ex: "Did the retriever return relevant documents? Was the tool called with valid arguments?",
    tone: "text-t_tool",
  },
  {
    level: "Run",
    q: "Did this turn produce a good answer?",
    ex: "Is the response grounded in what was retrieved? Does it follow the format contract?",
    tone: "text-t_llm",
  },
  {
    level: "Conversation",
    q: "Did the whole exchange succeed?",
    ex: "Was the user's problem actually resolved across six turns — or did the agent claim success after a tool error?",
    tone: "text-signal",
  },
];

const TOOLS = [
  {
    rank: "01",
    name: "Tracely",
    tag: "MIT · free to self-host",
    featured: true,
    body: "Evaluators are columns on the trace table, judged at conversation, run or span level, running online as traces land and on demand. Failing production runs freeze into hermetic regression cases that replay in CI with no model spend. Judge calibration scores your evaluators against human labels, so you can tell whether the judge is right before you let it gate a release.",
    cost: "$0 self-hosted with every feature and no paywalled internals. Free hosted tier at 20k traces/month; Team at $49/month. LLM judges run on your own model key — no markup on inference.",
  },
  {
    rank: "02",
    name: "Langfuse",
    tag: "MIT core",
    body: "The most widely adopted option, and the biggest community in the category. Tracing, prompt management with versioning, evaluators, datasets and experiments in one mature product.",
    cost: "Open-source core is free to self-host; some enterprise features are commercially licensed. Hosted plans available.",
  },
  {
    rank: "03",
    name: "Arize Phoenix",
    tag: "Open source",
    body: "OpenInference-native tracing with strong notebook-driven analysis. A good fit if your evaluation work happens in Jupyter rather than in a dashboard.",
    cost: "Phoenix is free and open source; the deeper platform features are in the commercial Arize product.",
  },
  {
    rank: "04",
    name: "DeepEval / Ragas",
    tag: "Open-source libraries",
    body: "Libraries rather than platforms — you get evaluation metrics you can call from pytest, with no backend to run. Ragas is RAG-focused; DeepEval is broader.",
    cost: "Free. You supply the storage, the dashboards and the production wiring yourself.",
  },
  {
    rank: "05",
    name: "Braintrust / LangSmith",
    tag: "Closed source",
    body: "Both are polished commercial platforms with strong experiment workflows. LangSmith is the natural choice if your stack is LangChain end to end.",
    cost: "Paid, hosted. Self-hosting is limited or unavailable depending on tier.",
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
            LLM evaluation, <span className="text-gradient-cyan">without the folklore</span>
          </h1>
          <p className="mt-6 text-lg leading-relaxed text-fg-muted">
            How to actually measure whether a language model or agent is doing its job: offline versus
            online evaluation, the metrics worth tracking, why most agent failures hide at the
            conversation level, and the tools that run it.
          </p>
        </div>
      </div>

      {/* --------------------------------- summary -------------------------------- */}
      <div className="mt-10 rounded-xl border border-line bg-ink-900/60 p-6">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-signal/80">The short version</p>
        <ul className="mt-4 space-y-2.5 text-fg-muted">
          <li>
            <strong className="text-fg">Assert everything you can for free.</strong> Valid JSON, schema,
            required fields, latency, cost. No judge needed.
          </li>
          <li>
            <strong className="text-fg">Use a model judge only for what you can&apos;t assert.</strong>{" "}
            Groundedness, tone, task completion.
          </li>
          <li>
            <strong className="text-fg">Evaluate the conversation, not just the span.</strong> Agent
            failures live in the trajectory.
          </li>
          <li>
            <strong className="text-fg">Then check the judge.</strong> An uncalibrated judge is a
            confident random number generator.
          </li>
        </ul>
      </div>

      {/* ---------------------------------- what ---------------------------------- */}
      <h2 className={prose.h2}>What LLM evaluation actually is</h2>
      <p className={prose.p}>
        Evaluation is scoring output against criteria you defined, so quality becomes something you
        measure instead of something you sense. Normal software testing asserts equality — this function
        returns 4. Language model output is open-ended and non-deterministic, so equality is almost never
        the right assertion. Two different answers can both be correct, and the same input can produce
        different text on Tuesday.
      </p>
      <p className={prose.p}>
        That doesn&apos;t mean you can&apos;t test it. It means the assertion moves from{" "}
        <em>is it this exact string</em> to <em>does it satisfy this property</em>. Most of the craft is
        picking properties precise enough to be checkable and important enough to be worth checking.
      </p>

      {/* -------------------------------- online/offline -------------------------- */}
      <h2 className={prose.h2}>Offline and online evaluation</h2>
      <p className={prose.p}>
        These answer different questions and neither replaces the other.
      </p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-line bg-ink-900/40 p-5">
          <p className="font-display text-lg font-bold text-fg">Offline</p>
          <p className="mt-2 font-mono text-[11px] uppercase tracking-wider text-fg-faint">before you ship</p>
          <p className="mt-3 leading-relaxed text-fg-muted">
            Run a fixed set of examples against a change and compare. Answers{" "}
            <em>is this version better than the last one?</em>
          </p>
          <p className="mt-3 leading-relaxed text-fg-faint">
            Weakness: it only contains failures someone thought to write down.
          </p>
        </div>
        <div className="rounded-xl border border-line bg-ink-900/40 p-5">
          <p className="font-display text-lg font-bold text-fg">Online</p>
          <p className="mt-2 font-mono text-[11px] uppercase tracking-wider text-fg-faint">after you ship</p>
          <p className="mt-3 leading-relaxed text-fg-muted">
            Score real production traffic as it happens. Answers{" "}
            <em>is this working for actual users right now?</em>
          </p>
          <p className="mt-3 leading-relaxed text-fg-faint">
            Weakness: it tells you after the fact, unless it feeds back into a gate.
          </p>
        </div>
      </div>
      <p className={prose.p}>
        The loop that matters connects them: online evaluation finds a failure you never imagined,
        and that failure becomes an offline test so it can never ship again. Most teams run both halves
        and never join them, which is why the same bug ships twice.
      </p>

      {/* --------------------------------- methods -------------------------------- */}
      <h2 className={prose.h2}>Three ways to score, cheapest first</h2>
      <h3 className={prose.h3}>1. Deterministic checks</h3>
      <p className={prose.p}>
        Is the JSON valid? Does it match the schema? Are required fields present, forbidden strings
        absent, latency and cost inside budget? These are free, instant, perfectly reliable, and catch a
        genuinely large share of real failures. Exhaust them before reaching for a model.
      </p>
      <h3 className={prose.h3}>2. LLM-as-a-judge</h3>
      <p className={prose.p}>
        A model scores the output against a rubric you write. This is the only practical way to measure
        groundedness, faithfulness to retrieved context, tone, or whether a task was completed. It costs
        money and tokens per evaluation, and it is <em>itself</em> a model that can be wrong — which is
        why the calibration step below is not optional.
      </p>
      <h3 className={prose.h3}>3. Human review</h3>
      <p className={prose.p}>
        The ground truth everything else approximates. Too slow to run on everything, and that&apos;s
        fine: its highest-value use isn&apos;t grading output, it&apos;s grading your judges.
      </p>
      <p className={prose.p}>
        A note on classic reference metrics — BLEU, ROUGE, exact match. They compare against a reference
        answer and punish valid rewordings. For agent output they correlate poorly with whether the
        answer was useful. They still have a place in narrow summarisation and translation work.
      </p>

      {/* --------------------------------- levels --------------------------------- */}
      <h2 className={prose.h2}>The level you evaluate at decides what you can catch</h2>
      <p className={prose.p}>
        This is the part most tooling gets wrong, and it&apos;s the difference between catching your real
        failures and catching the easy ones.
      </p>
      <div className="mt-6 space-y-3">
        {LEVELS.map((l) => (
          <div key={l.level} className="rounded-xl border border-line bg-ink-900/40 p-5">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className={`font-mono text-[11px] font-semibold uppercase tracking-wider ${l.tone}`}>
                {l.level}
              </span>
              <span className="font-display text-lg font-bold text-fg">{l.q}</span>
            </div>
            <p className="mt-2.5 leading-relaxed text-fg-muted">{l.ex}</p>
          </div>
        ))}
      </div>
      <p className={prose.p}>
        An agent that calls a refund API, gets a timeout, and then tells the customer their refund was
        processed has no bad span. The API call was correct. The response was fluent. The failure exists
        only in the sequence — and a judge scoped to one observation cannot see it, no matter how good
        the rubric is. Check whether your tooling can target a conversation before you trust a green
        dashboard.
      </p>

      {/* ------------------------------- calibration ------------------------------ */}
      <h2 className={prose.h2}>Then evaluate the evaluator</h2>
      <p className={prose.p}>
        A judge you haven&apos;t checked is a confident random number generator. The fix is
        unglamorous: label a sample of runs by hand, compare against what the judge said, and measure
        agreement. Two error types matter and they cost differently —{" "}
        <strong className="text-fg">false passes</strong> are bugs reaching users, and{" "}
        <strong className="text-fg">false fails</strong> are an alert everyone learns to ignore.
      </p>
      <p className={prose.p}>
        Do this before a judge is allowed to block a deploy. A gate built on an uncalibrated judge is
        worse than no gate: it converts an unknown risk into false confidence.
      </p>

      {/* ---------------------------------- tools --------------------------------- */}
      <h2 className={prose.h2}>Tools for running LLM evaluation</h2>
      <p className={prose.p}>
        We build the first one, so weigh it accordingly — the specifics are checkable, which is the
        point.
      </p>
      <div className="mt-6 space-y-4">
        {TOOLS.map((t) => (
          <div
            key={t.name}
            className={`rounded-xl border p-6 ${
              t.featured ? "border-signal/40 bg-signal/[0.05] shadow-glow" : "border-line bg-ink-900/40"
            }`}
          >
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-[11px] font-semibold text-signal">{t.rank}</span>
              <span className="font-display text-xl font-bold text-fg">{t.name}</span>
              <span className="rounded-full border border-line-bright bg-ink-900 px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-fg-muted">
                {t.tag}
              </span>
            </div>
            <p className="mt-3 leading-relaxed text-fg-muted">{t.body}</p>
            <p className="mt-2.5 leading-relaxed text-fg-faint">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ok">Cost</span> {t.cost}
            </p>
          </div>
        ))}
      </div>
      <p className={prose.p}>
        If you want the fuller head-to-head, we wrote one:{" "}
        <Link
          className="text-signal underline decoration-signal/30 underline-offset-4 transition hover:decoration-signal"
          href="/langfuse-alternatives"
        >
          Langfuse alternatives, compared honestly
        </Link>
        .
      </p>

      {/* --------------------------------- checklist ------------------------------ */}
      <h2 className={prose.h2}>A starting checklist</h2>
      <ol className="mt-5 space-y-3 text-fg-muted">
        {[
          "Trace everything first. You cannot evaluate what you didn't record, and instrumentation is the only step with no shortcut.",
          "Add deterministic checks: schema, required fields, latency, cost. Free, and they catch more than you'd expect.",
          "Write two or three judges for the properties you actually care about. Not twelve.",
          "Run them online, on production traffic, not only on a static set.",
          "Calibrate against human labels before any judge is allowed to block anything.",
          "Turn every real production failure into an offline test, so it cannot ship twice.",
          "Only then wire the gate into CI.",
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
        <p className="font-display text-2xl font-bold text-fg">Run all seven steps for $0</p>
        <p className="mt-3 leading-relaxed text-fg-muted">
          Tracely is MIT-licensed with no paywalled internals — self-host the whole product free, or use
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
