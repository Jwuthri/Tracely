"use client";

import clsx from "clsx";
import { useState } from "react";
import type { Draft, TriggerId } from "@/app/lib/alerts";
import { TRIGGERS } from "@/app/lib/alerts";
import type { StepDraft } from "@/app/lib/ruleFlow";
import { FIELD, LABEL } from "./tone";

/** "Describe the alert you want" → a drawn flow.
 *
 *  The panel never edits anything itself: it hands the page a draft, and the page pushes it onto
 *  the live canvas (`replaceFlow`). One shape in, one shape out — the same one Save produces. */

export type GeneratedDraft = {
  name: string;
  description: string;
  target_agent: string;
  condition: { type: TriggerId } & Record<string, unknown>;
  steps: StepDraft[];
  message: string;
};

const EXAMPLES = [
  "Slack me when the refund judge fails a live conversation on support-bot",
  "When a CI gate fails on a PR, post the failing case count and a link to Slack",
  "A brand new failure mode appears → ask a model to write a one-line triage note, then Slack it",
  "Page our on-call webhook with a bearer token when the overall failure rate goes over 25%",
];

export function AssistantPanel({
  draft,
  steps,
  onApply,
}: {
  /** The rule as it stands, so a follow-up reads as an edit rather than a rebuild. */
  draft: Draft;
  steps: () => StepDraft[];
  onApply: (generated: GeneratedDraft) => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function send() {
    const text = prompt.trim();
    if (text.length < 3) return;
    setBusy(true);
    setErr(null);
    setNote(null);
    try {
      const r = await fetch("/api/monitors/generate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          prompt: text,
          trigger: draft.type,
          current: {
            name: draft.name,
            trigger: draft.type,
            target_agent: draft.target_agent,
            steps: steps().map((s) => ({ name: s.name, step_type: s.step_type, config: s.config })),
          },
        }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `The assistant could not answer (HTTP ${r.status}).`);
        return;
      }
      onApply(d as GeneratedDraft);
      setNote(d?.message ?? "Drafted.");
      setPrompt("");
    } catch {
      setErr("Could not reach the assistant.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="card flex flex-col gap-3 px-4 py-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-signal/15 text-[12px] text-signal">✦</span>
          <span className="text-[13px] font-semibold text-fg">Rule assistant</span>
        </div>
        <p className="mt-1.5 text-[12px] leading-relaxed text-fg-muted">
          Describe the alert in a sentence and it draws the flow. It leaves every destination blank —
          you paste your own Slack URL or address.
        </p>
      </div>

      <div className="space-y-1">
        <label htmlFor="assist-prompt" className={LABEL}>
          What should this alert do?
        </label>
        <textarea
          id="assist-prompt"
          rows={4}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            // ⌘/Ctrl+Enter sends: the textarea is multi-line on purpose, so plain Enter must not.
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void send();
          }}
          placeholder="Slack me when a conversation fails the PII judge, but only on support-bot"
          className={clsx(FIELD, "min-h-[88px] resize-y")}
        />
      </div>

      <button onClick={send} disabled={busy || prompt.trim().length < 3} className="btn-primary">
        {busy ? "Drafting…" : "Draft the flow"}
      </button>

      {err !== null ? (
        <p role="alert" className="text-[12px] text-fail">
          {err}
        </p>
      ) : null}
      {note !== null ? <p className="text-[12px] text-ok">{note}</p> : null}

      <div className="space-y-1.5">
        <div className={LABEL}>Try</div>
        <ul className="space-y-1">
          {EXAMPLES.map((ex) => (
            <li key={ex}>
              <button
                onClick={() => setPrompt(ex)}
                className="w-full rounded-md border border-line bg-ink-700 px-2 py-1.5 text-left text-[11.5px] leading-snug text-fg-muted transition-colors hover:border-signal/50 hover:text-fg"
              >
                {ex}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <p className="mt-auto text-[11px] text-fg-faint">
        Runs on this workspace&apos;s OpenRouter key, like the other AI features. Current trigger:{" "}
        <span className="text-fg-muted">{TRIGGERS[draft.type].label}</span>.
      </p>
    </aside>
  );
}
