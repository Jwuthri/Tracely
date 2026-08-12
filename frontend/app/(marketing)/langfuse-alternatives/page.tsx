import type { Metadata } from "next";
import Link from "next/link";

import { SITE_URL } from "@/app/lib/site";
import { PageShell, prose } from "../_components/PageShell";

// Target query: "langfuse alternatives" (140/mo, KD 0, $36.73 CPC — see SEO.md).
// The SERP is entirely listicles, so a single-vendor pitch page would mismatch intent and not rank.
// This is a real multi-tool comparison in which Tracely is one honest entry.
export const metadata: Metadata = {
  title: { absolute: "Langfuse Alternatives (2026): 6 Options Compared, Honestly" },
  description:
    "A straight comparison of Langfuse alternatives — LangSmith, Braintrust, Arize Phoenix, Helicone and Tracely — including when Langfuse is still the right answer.",
  alternates: { canonical: "/langfuse-alternatives" },
  openGraph: {
    title: "Langfuse Alternatives (2026): 6 Options Compared, Honestly",
    description:
      "LangSmith, Braintrust, Arize Phoenix, Helicone and Tracely compared — including when Langfuse is still the right answer.",
    url: `${SITE_URL}/langfuse-alternatives`,
    type: "article",
  },
};

type Tool = {
  name: string;
  href: string;
  oss: string;
  bestFor: string;
  watchOut: string;
};

const TOOLS: Tool[] = [
  {
    name: "Langfuse",
    href: "https://langfuse.com",
    oss: "Yes (MIT core)",
    bestFor: "The default. Tracing, prompt management, evals and datasets in one mature product with a large community.",
    watchOut: "Self-hosting means running ClickHouse, Postgres, Redis and S3. Prompt management is a big part of the value — if you don't want it, you're carrying weight.",
  },
  {
    name: "LangSmith",
    href: "https://smith.langchain.com",
    oss: "No",
    bestFor: "Teams already deep in LangChain/LangGraph. The native integration is the tightest available.",
    watchOut: "Closed source, no self-host on lower tiers. You're betting on one vendor's framework and hosting.",
  },
  {
    name: "Braintrust",
    href: "https://braintrust.dev",
    oss: "No",
    bestFor: "Eval-first teams that want a polished experiment/scoring workflow and CI deployment blocking.",
    watchOut: "Proprietary storage engine. Strong on evals, less of a general-purpose observability backend.",
  },
  {
    name: "Arize Phoenix",
    href: "https://phoenix.arize.com",
    oss: "Yes",
    bestFor: "OpenInference-native tracing and notebook-driven analysis. Good if you live in Jupyter.",
    watchOut: "Phoenix is the OSS slice; the deeper platform features sit in the commercial Arize product.",
  },
  {
    name: "Helicone",
    href: "https://helicone.ai",
    oss: "Yes",
    bestFor: "Gateway-style setup — one proxy line and you get logging, caching and cost tracking.",
    watchOut: "Proxy-first design means a request-level view. Less natural for deep multi-step agent trajectories.",
  },
  {
    name: "Tracely",
    href: "/",
    oss: "Yes (MIT, whole product)",
    bestFor: "Turning production failures into hermetic regression tests that gate pull requests, with no hand-authored dataset.",
    watchOut: "Youngest project here, smallest community. No prompt management — deliberately out of scope.",
  },
];

const JSON_LD = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Is Langfuse open source?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. The Langfuse core is MIT-licensed and can be self-hosted, though some enterprise features are commercially licensed. Self-hosting requires running ClickHouse, Postgres, Redis and S3-compatible storage.",
      },
    },
    {
      "@type": "Question",
      name: "What is the best open source alternative to Langfuse?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "It depends what you need. Arize Phoenix is strong for OpenInference-native tracing and notebook analysis, Helicone for gateway-style logging and cost tracking, and Tracely for turning production failures into hermetic regression tests that gate CI. For general-purpose tracing plus prompt management, Langfuse itself is usually still the best answer.",
      },
    },
    {
      "@type": "Question",
      name: "Does Langfuse support CI/CD?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. Langfuse offers CI/CD experiments via a GitHub Action: you create a dataset of test cases, write an experiment script, and raise a RegressionError to fail the job. The experiment makes live model API calls during CI, so provider keys must be available as CI secrets.",
      },
    },
  ],
};

export default function Page() {
  return (
    <PageShell>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }} />

      <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-signal/80">Comparison</p>
      <h1 className="mt-4 font-display text-4xl font-bold leading-tight tracking-tight text-fg sm:text-5xl">
        Langfuse alternatives, compared honestly
      </h1>
      <p className="mt-6 text-lg leading-relaxed text-fg-muted">
        We build one of the tools on this page, so read it with that in mind. We&apos;ve tried to write the
        comparison we wanted when we were choosing: what each tool is actually good at, and{" "}
        <strong className="text-fg">when Langfuse is still the right answer</strong> — which, for a lot of
        teams, it is.
      </p>

      <h2 className={prose.h2}>First: is Langfuse actually your problem?</h2>
      <p className={prose.p}>
        Langfuse is the default choice in this category for good reasons. It has mature tracing, prompt
        management with versioning, LLM-as-a-judge evaluators, datasets and experiments, an MIT-licensed
        core you can self-host, and by far the largest community of anything here. If you searched for
        alternatives out of habit rather than friction, the honest advice is to stay.
      </p>
      <p className={prose.p}>The reasons teams do move are usually specific:</p>
      <ul className={prose.ul}>
        <li>
          <strong className="text-fg">Self-hosting weight.</strong> Running Langfuse yourself means
          ClickHouse, Postgres, Redis and S3-compatible storage. That&apos;s a real operational
          commitment for a small team.
        </li>
        <li>
          <strong className="text-fg">You don&apos;t want prompt management.</strong> It&apos;s a large
          part of the product. If your prompts live in Git, you&apos;re carrying a subsystem you never open.
        </li>
        <li>
          <strong className="text-fg">Dataset upkeep.</strong> Evals and CI both start from datasets you
          author and maintain by hand. Some teams find that&apos;s the part that quietly rots.
        </li>
      </ul>

      <h2 className={prose.h2}>The alternatives</h2>
      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-line-bright">
              <th className="py-3 pr-4 font-display font-bold text-fg">Tool</th>
              <th className="py-3 pr-4 font-display font-bold text-fg">Open source</th>
              <th className="py-3 font-display font-bold text-fg">Best for</th>
            </tr>
          </thead>
          <tbody>
            {TOOLS.map((t) => (
              <tr key={t.name} className="border-b border-line/60 align-top">
                <td className="py-4 pr-4 font-semibold text-fg">{t.name}</td>
                <td className="py-4 pr-4 font-mono text-[12px] text-fg-muted">{t.oss}</td>
                <td className="py-4 text-fg-muted">{t.bestFor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {TOOLS.map((t) => (
        <div key={t.name}>
          <h3 className={prose.h3}>{t.name}</h3>
          <p className={prose.p}>{t.bestFor}</p>
          <p className="mt-2 leading-relaxed text-fg-faint">
            <span className="font-mono text-[11px] uppercase tracking-wider text-warn">Trade-off</span>{" "}
            {t.watchOut}
          </p>
        </div>
      ))}

      <h2 className={prose.h2}>The one difference worth understanding: where test cases come from</h2>
      <p className={prose.p}>
        Most comparisons in this category are feature checklists, and every tool here traces, scores and
        charts. The distinction that actually changes your week is where the things you test against come
        from, and what they cost to run.
      </p>
      <p className={prose.p}>
        <strong className="text-fg">Langfuse&apos;s CI path</strong> is dataset-first, and it works: you
        create a dataset of test cases, write an experiment script, add evaluators, and raise a{" "}
        <code className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[12.5px] text-signal-soft">
          RegressionError
        </code>{" "}
        when a score drops below threshold. Their GitHub Action fails the job and comments on the PR. The
        experiment executes your real code, so it makes <strong className="text-fg">live model API
        calls</strong> during CI — your provider keys go in as CI secrets, and each run costs money and
        can flake when a model is non-deterministic or an API is down.
      </p>
      <p className={prose.p}>
        <strong className="text-fg">Tracely&apos;s path</strong> starts from a failure that already
        happened. A production trace that a judge marked FAIL gets promoted, in one click, into a case —
        the recorded input plus every tool and model response bundled as fixtures, with a fail-to-pass
        contract attached. CI replays it against those fixtures: no provider keys, no model spend, and
        the same result every time. Nobody writes or maintains a dataset, because production wrote it.
      </p>
      <p className={prose.p}>
        Both approaches block the merge. The difference is that one asks you to imagine the failure cases
        in advance and pay a model bill on every run, and the other only ever tests failures you actually
        had. Neither is universally better — if you need to test a{" "}
        <em>new</em> capability that has never run in production, a hand-authored dataset is the only
        thing that can do it, and Langfuse does it well.
      </p>

      <h2 className={prose.h2}>How to choose</h2>
      <ul className={prose.ul}>
        <li>
          <strong className="text-fg">Stay on Langfuse</strong> if you want one mature tool for tracing,
          prompts and evals, and you don&apos;t mind the infrastructure.
        </li>
        <li>
          <strong className="text-fg">LangSmith</strong> if your stack is LangChain/LangGraph and you
          want the tightest native integration.
        </li>
        <li>
          <strong className="text-fg">Braintrust</strong> if evaluation quality is the centre of your
          workflow and hosted is fine.
        </li>
        <li>
          <strong className="text-fg">Arize Phoenix</strong> if you want OpenInference-native tracing and
          analysis in notebooks.
        </li>
        <li>
          <strong className="text-fg">Helicone</strong> if you want logging and cost tracking from a
          single proxy line.
        </li>
        <li>
          <strong className="text-fg">Tracely</strong> if your recurring pain is the same production
          failure shipping twice, and you don&apos;t want to hand-author the test set that stops it.
        </li>
      </ul>

      <h2 className={prose.h2}>Switching is cheaper than it looks</h2>
      <p className={prose.p}>
        Langfuse, Phoenix and Tracely all speak OpenTelemetry. If your agent already emits OTLP, pointing
        it at a second backend is an endpoint and a key — you can run two in parallel for a week and
        compare on your own traces rather than on anyone&apos;s comparison table, including this one.
      </p>

      <div className="mt-14 rounded-2xl border border-signal/30 bg-signal/[0.06] p-7">
        <p className="font-display text-xl font-bold text-fg">Try Tracely on a real failure</p>
        <p className="mt-3 leading-relaxed text-fg-muted">
          MIT-licensed, self-hostable, free tier on the hosted version. Three lines to instrument, and the
          first frozen case takes one click.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <a
            className="inline-flex items-center gap-2 rounded-full bg-signal px-5 py-2.5 text-sm font-semibold text-ink-950 transition hover:bg-signal-soft"
            href="/dashboard"
          >
            Start free
          </a>
          <Link
            className="inline-flex items-center gap-2 rounded-full border border-line-bright/70 bg-white/[0.04] px-5 py-2.5 text-sm font-medium text-fg transition hover:bg-white/[0.08]"
            href="/"
          >
            How it works
          </Link>
        </div>
      </div>
    </PageShell>
  );
}
