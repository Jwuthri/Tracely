import { CopyId } from "./CopyId";

/* The first-run path, told as the product's own loop: trace → grade → failure → case → gate.
   Every step's done-ness is DERIVED from real counts — there is no stored progress to drift
   out of sync, and a workspace that already did the work never sees this card. Only the first
   unfinished step is expanded; the rest are one line each. */

export type ActivationState = {
  traces: number;
  evaluators: number;
  failures: number;
  /** Clusters count as a caught failure too: a raw execution error is clustered without any
   *  evaluator scoring it FAIL, and the step must not read "not done" next to a full
   *  clusters page. */
  clusters: number;
  cases: number;
  gates: number;
  ingestKey: string;
  endpoint: string;
};

type Step = {
  title: string;
  done: boolean;
  /** Shown on the right of a finished step — the evidence it's done. */
  proof: string;
  /** What to do about it, rendered only while this is the current step. */
  body: React.ReactNode;
};

const n = (v: number) => v.toLocaleString("en-US");

function Snippet({ code, label }: { code: string; label: string }) {
  return (
    <div className="mt-2 overflow-hidden rounded-lg border border-line bg-ink-900">
      <div className="flex items-center justify-between border-b border-line/60 px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">{label}</span>
        <CopyId value={code} text="copy" label={label} />
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-[11.5px] leading-relaxed text-fg-muted">{code}</pre>
    </div>
  );
}

function Action({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} className="btn-ghost mt-2 inline-flex">
      {children}
    </a>
  );
}

export function Activation(s: ActivationState) {
  const steps: Step[] = [
    {
      title: "Send your first trace",
      done: s.traces > 0,
      proof: `${n(s.traces)} traces`,
      body: (
        <>
          <p className="text-[12.5px] text-fg-muted">
            Point the SDK at this workspace. Auto-instrumentation traces your existing agent with
            no span code.
          </p>
          <Snippet
            label="python"
            code={`pip install "tracely-sdk[openai]"

import tracely_sdk as tracely
tracely.init(endpoint="${s.endpoint}", api_key="${s.ingestKey}")

with tracely.trace(agent="support", conversation="conv-1"):
    ...  # your agent runs as usual`}
          />
        </>
      ),
    },
    {
      title: "Let Tracely grade every run",
      done: s.evaluators > 0,
      proof: `${n(s.evaluators)} evaluator${s.evaluators === 1 ? "" : "s"}`,
      body: (
        <>
          <p className="text-[12.5px] text-fg-muted">
            Evaluators are the columns of the traces table — structural checks run free, an
            LLM judge grades the answer. They run automatically on every new trace.
          </p>
          <Action href="/traces">Add a column on Traces →</Action>
        </>
      ),
    },
    {
      title: "Catch a real failure",
      done: s.failures > 0 || s.clusters > 0,
      proof: s.failures > 0 ? `${n(s.failures)} detected` : `${n(s.clusters)} clustered`,
      body: (
        <>
          <p className="text-[12.5px] text-fg-muted">
            Nothing to do here — this ticks the first time an evaluator fails a production run.
            Similar failures are then clustered into one issue instead of a wall of traces.
          </p>
          <Action href="/clusters">See failure clusters →</Action>
        </>
      ),
    },
    {
      title: "Promote a failure to a regression case",
      done: s.cases > 0,
      proof: `${n(s.cases)} case${s.cases === 1 ? "" : "s"}`,
      body: (
        <>
          <p className="text-[12.5px] text-fg-muted">
            A promoted failure becomes a fail-to-pass test with the real tool calls recorded, so
            it replays hermetically — no dataset to hand-write.
          </p>
          <Action href="/clusters">Promote from a cluster →</Action>
        </>
      ),
    },
    {
      title: "Gate a pull request",
      done: s.gates > 0,
      proof: `${n(s.gates)} gate run${s.gates === 1 ? "" : "s"}`,
      body: (
        <>
          <p className="text-[12.5px] text-fg-muted">
            Run the promoted cases against the PR's agent. It exits non-zero and posts a commit
            status, so the failure you fixed can never come back.
          </p>
          <Snippet
            label="ci"
            code={`pip install tracely-sdk
TRACELY_API=${s.endpoint} TRACELY_KEY=${s.ingestKey} \\
  tracely replay --agent support --entrypoint app.agent:run`}
          />
        </>
      ),
    },
  ];

  const done = steps.filter((x) => x.done).length;
  if (done === steps.length) return null; // the loop is closed — this card has nothing left to say
  const current = steps.findIndex((x) => !x.done);

  return (
    <section className="reveal card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <h2 className="text-[13.5px] font-semibold text-fg">Get to your first gate</h2>
          <p className="mt-0.5 text-[12px] text-fg-muted">
            The whole loop, once: a production trace becomes a test that blocks a PR.
          </p>
        </div>
        <span className="shrink-0 font-mono text-[11px] text-fg-faint">
          {done} / {steps.length}
        </span>
      </div>
      <ol className="divide-y divide-line/50">
        {steps.map((step, i) => (
          <li key={step.title} className={i === current ? "bg-white/[0.02] px-4 py-3.5" : "px-4 py-2.5"}>
            <div className="flex items-center gap-2.5">
              <span
                className={`grid h-4 w-4 shrink-0 place-items-center rounded-full border text-[9px] ${
                  step.done
                    ? "border-ok/50 bg-ok/15 text-ok"
                    : i === current
                      ? "border-signal/60 text-signal"
                      : "border-line text-fg-faint"
                }`}
              >
                {step.done ? "✓" : i + 1}
              </span>
              <span
                className={`flex-1 truncate text-[13px] ${
                  step.done ? "text-fg-muted line-through decoration-line" : i === current ? "font-semibold text-fg" : "text-fg-muted"
                }`}
              >
                {step.title}
              </span>
              {step.done && <span className="shrink-0 font-mono text-[10.5px] text-fg-faint">{step.proof}</span>}
            </div>
            {i === current && <div className="mt-2 pl-6.5">{step.body}</div>}
          </li>
        ))}
      </ol>
    </section>
  );
}
