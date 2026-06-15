"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { SuggestedEvaluator } from "../lib/api";
import type { EvaluatorConfig, EvaluatorDraft, EvaluatorLevel } from "../lib/evaluators";
import { AddColumnModal } from "./AddColumnModal";
import { CodeBlock } from "./CodeBlock";

// The cluster detail's "Suggested evaluator" panel. The backend now returns a creatable DRAFT
// (built-in structural check or an LLM-judge rubric) — this opens it in the Add Column editor
// prefilled, so the user reviews/edits then saves, exactly like the "Use AI" / "Browse Library"
// flows. (There is no user-Python evaluator kind, so a code snippet had nowhere to go.)

const LEVEL_LABEL: Record<string, string> = {
  CONVERSATION: "Conversation", AGENT_RUN: "Message", SPAN: "Step",
  TOOL: "Tool step", GENERATION: "Generation step", CHAIN: "Chain step",
};

export function SuggestedEvaluatorCard({ ev }: { ev: SuggestedEvaluator }) {
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState(false);
  const router = useRouter();

  // Stable draft reference so the modal's open-seed effect doesn't re-fire on every render.
  const draft = useMemo<EvaluatorDraft>(() => ({
    name: ev.name,
    description: ev.description,
    kind: ev.kind,
    level: ev.level as EvaluatorLevel,
    config: ev.config as EvaluatorConfig,
  }), [ev]);

  const isStructural = ev.kind === "structural";
  const checkName = typeof ev.config.check === "string" ? ev.config.check : "";
  const prompt = typeof ev.config.prompt === "string" ? ev.config.prompt : "";

  return (
    <section className="reveal card overflow-hidden" style={{ animationDelay: "125ms" }}>
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="text-[13px] font-semibold text-fg">Suggested evaluator</span>
          <span className="font-mono text-[11px] text-fg-faint">{ev.name}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="rounded border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wider text-violet-400">
            {isStructural ? "check" : "llm"}
          </span>
          <span className="rounded bg-ink-700 px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wider text-fg-faint">
            {LEVEL_LABEL[ev.level] ?? ev.level}
          </span>
        </div>
      </div>
      <div className="space-y-3 px-4 py-3.5">
        <p className="text-[12.5px] leading-relaxed text-fg-muted">{ev.rationale}</p>
        {isStructural ? (
          <div className="rounded-lg border border-line bg-ink-900/60 px-3 py-2 text-[12px] text-fg-muted">
            Built-in structural check <span className="font-mono text-fg">{checkName}</span> — {ev.description}
          </div>
        ) : (
          <CodeBlock code={prompt} action="Copy" />
        )}
        <div className="flex items-center gap-3">
          <button
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-[12.5px] font-medium text-white transition-colors hover:bg-blue-500"
          >
            + Create evaluator
          </button>
          {created && <span className="text-[12px] text-ok">Created ✓ — runs on new traces.</span>}
        </div>
      </div>

      <AddColumnModal
        open={open}
        onClose={() => setOpen(false)}
        onSaved={() => { setOpen(false); setCreated(true); router.refresh(); }}
        prefill={draft}
      />
    </section>
  );
}
