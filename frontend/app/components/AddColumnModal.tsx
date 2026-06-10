"use client";

import clsx from "clsx";
import { useEffect, useMemo, useState, type SVGProps } from "react";
import {
  createEvaluator,
  generateEvaluator,
  listTemplates,
  updateEvaluator,
  type EvaluatorConfig,
  type EvaluatorDef,
  type EvaluatorDraft,
  type EvaluatorLevel,
  type EvaluatorTemplate,
} from "../lib/evaluators";

// ── Add Evaluation Column ───────────────────────────────────────────────────────
// The TurnWise-style wizard: Browse Library (one click) · Manual (form) · Use AI
// (describe → draft → review in the form). Editing an existing column jumps straight
// to the form. Creation never runs anything — columns evaluate on ingest + via Run.

const svg = (p: SVGProps<SVGSVGElement>) => ({
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  ...p,
});
const BookIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>
);
const CodeIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="m18 16 4-4-4-4" /><path d="m6 8-4 4 4 4" /><path d="m14.5 4-5 16" /></svg>
);
const SparklesIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}>
    <path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z" />
    <path d="M20 3v4" /><path d="M22 5h-4" />
  </svg>
);
const XIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>
);

type Step = "type" | "library" | "config";

const LEVEL_OPTIONS: { value: EvaluatorLevel; label: string; hint: string }[] = [
  { value: "CONVERSATION", label: "Conversation", hint: "one grade per thread" },
  { value: "AGENT_RUN", label: "Message", hint: "one grade per turn" },
  { value: "SPAN", label: "Step", hint: "one grade per tool call / generation" },
];
// Step-flavored levels all live in the S group; the segmented control canonicalizes to SPAN
// unless the evaluator already uses a narrower step level.
const S_LEVELS = new Set<EvaluatorLevel>(["SPAN", "TOOL", "GENERATION", "CHAIN"]);

const OUTPUT_OPTIONS = [
  { value: "score", label: "Score (0–1 + threshold)" },
  { value: "boolean", label: "Pass / Fail" },
  { value: "category", label: "Category" },
  { value: "text", label: "Text" },
  { value: "json", label: "JSON object" },
] as const;

type FormState = {
  name: string;
  description: string;
  kind: "llm_judge" | "structural";
  level: EvaluatorLevel;
  prompt: string;
  model: string;
  outputType: (typeof OUTPUT_OPTIONS)[number]["value"];
  threshold: string;
  categories: string;
  failCategories: string;
  paramsJson: string; // structural evaluators only
  enabled: boolean;
  scoreName?: string; // set when installing a template (stable identity)
};

const EMPTY_FORM: FormState = {
  name: "", description: "", kind: "llm_judge", level: "AGENT_RUN", prompt: "", model: "",
  outputType: "score", threshold: "0.6", categories: "", failCategories: "", paramsJson: "",
  enabled: true,
};

function formFromConfig(
  base: Pick<FormState, "name" | "description" | "kind" | "level" | "enabled">,
  config: EvaluatorConfig,
  scoreName?: string,
): FormState {
  return {
    ...EMPTY_FORM,
    ...base,
    prompt: config.prompt ?? "",
    model: config.model ?? "",
    outputType: (config.output_type as FormState["outputType"]) ?? "score",
    threshold: config.threshold != null ? String(config.threshold) : "0.6",
    categories: (config.categories ?? []).join(", "),
    failCategories: (config.fail_categories ?? []).join(", "),
    paramsJson: config.check ? JSON.stringify(config.params ?? {}, null, 2) : "",
    scoreName,
  };
}

function configFromForm(f: FormState, previous?: EvaluatorConfig): EvaluatorConfig {
  if (f.kind === "structural") {
    const config: EvaluatorConfig = { ...(previous ?? {}) };
    if (f.paramsJson.trim()) config.params = JSON.parse(f.paramsJson) as Record<string, unknown>;
    return config;
  }
  // preserve advanced keys we don't surface (span_types, max_spans, …) when editing
  const config: EvaluatorConfig = { ...(previous ?? {}) };
  delete config.check;
  delete config.params;
  config.prompt = f.prompt.trim();
  config.output_type = f.outputType;
  if (f.model.trim()) config.model = f.model.trim();
  else delete config.model;
  if (f.outputType === "score" || f.outputType === "json") {
    const t = parseFloat(f.threshold);
    if (!Number.isNaN(t)) config.threshold = Math.min(Math.max(t, 0), 1);
  } else {
    delete config.threshold;
  }
  if (f.outputType === "category") {
    config.categories = f.categories.split(",").map((s) => s.trim()).filter(Boolean);
    const fails = f.failCategories.split(",").map((s) => s.trim()).filter(Boolean);
    if (fails.length) config.fail_categories = fails;
    else delete config.fail_categories;
  } else {
    delete config.categories;
    delete config.fail_categories;
  }
  return config;
}

export function AddColumnModal({
  open,
  onClose,
  onSaved,
  editing,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (ev: EvaluatorDef) => void;
  editing?: EvaluatorDef | null;
}) {
  const [step, setStep] = useState<Step>("type");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Use AI
  const [aiOpen, setAiOpen] = useState(false);
  const [aiText, setAiText] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  // Library
  const [templates, setTemplates] = useState<EvaluatorTemplate[] | null>(null);

  // (Re)seed on open: editing jumps straight to the form.
  useEffect(() => {
    if (!open) return;
    setError("");
    setAiOpen(false);
    setAiText("");
    setBusy(false);
    if (editing) {
      setForm(formFromConfig(
        {
          name: editing.name, description: editing.description, kind: editing.kind,
          level: editing.level, enabled: editing.enabled,
        },
        editing.config ?? {},
      ));
      setStep("config");
    } else {
      setForm(EMPTY_FORM);
      setStep("type");
    }
  }, [open, editing]);

  useEffect(() => {
    if (open && step === "library" && templates === null) {
      void listTemplates().then(setTemplates).catch(() => setTemplates([]));
    }
  }, [open, step, templates]);

  const grouped = useMemo(() => {
    const tpl = templates ?? [];
    const groups: { key: string; label: string; items: EvaluatorTemplate[] }[] = [
      { key: "C", label: "Conversation level", items: [] },
      { key: "M", label: "Message level", items: [] },
      { key: "S", label: "Step level", items: [] },
    ];
    for (const t of tpl) {
      const g = t.level === "CONVERSATION" ? 0 : t.level === "AGENT_RUN" ? 1 : 2;
      groups[g].items.push(t);
    }
    return groups.filter((g) => g.items.length > 0);
  }, [templates]);

  if (!open) return null;

  function pickTemplate(t: EvaluatorTemplate) {
    if (t.installed) return;
    setForm(formFromConfig(
      { name: t.name, description: t.description, kind: t.kind, level: t.level, enabled: true },
      t.config ?? {},
      t.score_name,
    ));
    setStep("config");
  }

  async function runGenerate() {
    if (!aiText.trim()) return;
    setAiBusy(true);
    setError("");
    try {
      const draft: EvaluatorDraft = await generateEvaluator(aiText.trim());
      setForm(formFromConfig(
        {
          name: draft.name, description: draft.description, kind: draft.kind,
          level: draft.level, enabled: true,
        },
        draft.config ?? {},
      ));
      setStep("config");
    } catch (e) {
      setError(e instanceof Error ? e.message : "generation failed");
    } finally {
      setAiBusy(false);
    }
  }

  async function save() {
    if (!form.name.trim()) {
      setError("Name is required.");
      return;
    }
    if (form.kind === "llm_judge" && !form.prompt.trim()) {
      setError("Evaluation prompt is required.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const config = configFromForm(form, editing?.config);
      const saved = editing
        ? await updateEvaluator(editing.id, {
            name: form.name.trim(),
            description: form.description.trim(),
            level: form.level,
            enabled: form.enabled,
            config,
          })
        : await createEvaluator({
            name: form.name.trim(),
            description: form.description.trim(),
            kind: form.kind,
            level: form.level,
            config,
            enabled: form.enabled,
            ...(form.scoreName ? { score_name: form.scoreName } : {}),
          });
      onSaved(saved);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  const isStructural = form.kind === "structural";
  const levelSegment: EvaluatorLevel = S_LEVELS.has(form.level) ? "SPAN" : form.level;

  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-[2px] sm:p-8" onClick={onClose}>
      <div
        className="mt-4 w-full max-w-xl rounded-xl border border-slate-700 bg-slate-900 shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-700/80 px-5 py-4">
          <h2 className="text-[15px] font-semibold text-slate-100">
            {editing ? "Edit Evaluation Column" : "Add Evaluation Column"}
          </h2>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white" aria-label="Close">
            <XIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[75vh] overflow-y-auto p-5">
          {step === "type" && (
            <div className="space-y-4">
              <p className="text-[13px] text-slate-400">Choose how you want to create your evaluation metric.</p>
              <button
                onClick={() => setStep("library")}
                className="flex w-full items-center gap-3 rounded-lg border border-emerald-500/25 bg-emerald-500/[0.06] p-4 text-left transition-colors hover:border-emerald-500/50 hover:bg-emerald-500/10"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
                  <BookIcon className="h-4.5 w-4.5" />
                </span>
                <span>
                  <span className="block text-[13.5px] font-medium text-slate-100">Browse Library</span>
                  <span className="block text-[12px] text-slate-400">Choose from pre-built evaluation metrics</span>
                </span>
              </button>

              <div className="flex items-center gap-3 text-[11px] uppercase tracking-wider text-slate-600">
                <span className="h-px flex-1 bg-slate-700/70" />
                or create your own
                <span className="h-px flex-1 bg-slate-700/70" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => { setForm(EMPTY_FORM); setStep("config"); }}
                  className="flex flex-col items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/40 p-5 text-center transition-colors hover:border-slate-500 hover:bg-slate-800"
                >
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/15 text-blue-400">
                    <CodeIcon className="h-5 w-5" />
                  </span>
                  <span className="text-[13px] font-medium text-slate-100">Manual</span>
                  <span className="text-[11.5px] leading-snug text-slate-400">Define prompt and output format</span>
                </button>
                <button
                  onClick={() => setAiOpen((o) => !o)}
                  className={clsx(
                    "flex flex-col items-center gap-2 rounded-lg border p-5 text-center transition-colors",
                    aiOpen
                      ? "border-violet-500/60 bg-violet-500/10"
                      : "border-slate-700 bg-slate-800/40 hover:border-slate-500 hover:bg-slate-800",
                  )}
                >
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/15 text-violet-400">
                    <SparklesIcon className="h-5 w-5" />
                  </span>
                  <span className="text-[13px] font-medium text-slate-100">Use AI</span>
                  <span className="text-[11.5px] leading-snug text-slate-400">Describe and let AI create it</span>
                </button>
              </div>

              {aiOpen && (
                <div className="space-y-3 rounded-lg border border-slate-700 bg-slate-800/40 p-4">
                  <label className="block text-[12px] font-medium text-slate-300">Describe your metric</label>
                  <textarea
                    value={aiText}
                    onChange={(e) => setAiText(e.target.value)}
                    rows={4}
                    placeholder="e.g., Check if the assistant's response is helpful and addresses the user's question. I want to evaluate accuracy, completeness, and tone."
                    className="w-full resize-y rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-[12.5px] text-slate-200 placeholder:text-slate-600 focus:border-violet-500/50 focus:outline-none"
                  />
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={() => setAiOpen(false)} className="rounded-lg px-3 py-1.5 text-[12.5px] text-slate-400 transition-colors hover:bg-slate-800 hover:text-white">
                      Cancel
                    </button>
                    <button
                      onClick={() => void runGenerate()}
                      disabled={aiBusy || !aiText.trim()}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3.5 py-1.5 text-[12.5px] font-medium text-white transition-colors hover:bg-violet-500 disabled:opacity-50"
                    >
                      {aiBusy ? (
                        <span className="h-3 w-3 animate-spin rounded-full border-2 border-violet-300/40 border-t-white" />
                      ) : (
                        <SparklesIcon className="h-3.5 w-3.5" />
                      )}
                      Generate
                    </button>
                  </div>
                </div>
              )}
              {error && <p className="text-[12px] text-rose-400">{error}</p>}
            </div>
          )}

          {step === "library" && (
            <div className="space-y-5">
              {templates === null ? (
                <div className="flex items-center gap-2 py-8 text-[13px] text-slate-500">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-700 border-t-slate-400" />
                  Loading library…
                </div>
              ) : (
                grouped.map((g) => (
                  <div key={g.key} className="space-y-2">
                    <div className="text-[10.5px] font-medium uppercase tracking-wider text-slate-500">{g.label}</div>
                    {g.items.map((t) => (
                      <button
                        key={t.score_name}
                        onClick={() => pickTemplate(t)}
                        disabled={t.installed}
                        className={clsx(
                          "flex w-full items-start justify-between gap-3 rounded-lg border p-3 text-left transition-colors",
                          t.installed
                            ? "cursor-default border-slate-800 bg-slate-800/20 opacity-60"
                            : "border-slate-700 bg-slate-800/40 hover:border-slate-500 hover:bg-slate-800",
                        )}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-[13px] font-medium text-slate-100">{t.name}</span>
                          <span className="mt-0.5 block text-[11.5px] leading-snug text-slate-400">{t.description}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-1.5">
                          {t.kind === "llm_judge" && (
                            <span className="rounded border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 text-[9.5px] font-medium uppercase tracking-wider text-violet-300">LLM</span>
                          )}
                          {t.installed && (
                            <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[9.5px] font-medium uppercase tracking-wider text-emerald-300">Installed</span>
                          )}
                        </span>
                      </button>
                    ))}
                  </div>
                ))
              )}
              <div className="flex justify-start pt-1">
                <button onClick={() => setStep("type")} className="rounded-lg border border-slate-700 px-3.5 py-1.5 text-[12.5px] text-slate-300 transition-colors hover:bg-slate-800">
                  Back
                </button>
              </div>
            </div>
          )}

          {step === "config" && (
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-[12px] font-medium text-slate-300">Evaluation Level</label>
                <div className="grid grid-cols-3 gap-2">
                  {LEVEL_OPTIONS.map((o) => (
                    <button
                      key={o.value}
                      onClick={() => setForm((f) => ({ ...f, level: o.value }))}
                      title={o.hint}
                      className={clsx(
                        "rounded-lg border px-3 py-2 text-[12.5px] font-medium transition-colors",
                        levelSegment === o.value
                          ? "border-blue-500/60 bg-blue-500/15 text-blue-300"
                          : "border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500 hover:text-slate-200",
                      )}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
                {S_LEVELS.has(form.level) && form.level !== "SPAN" && (
                  <p className="mt-1 text-[11px] text-slate-500">
                    Currently scoped to <span className="font-mono">{form.level}</span> steps only.
                  </p>
                )}
              </div>

              <div>
                <label className="mb-1.5 block text-[12px] font-medium text-slate-300">Metric Name</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g., Helpfulness Score"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-[12.5px] text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none"
                />
              </div>

              <div>
                <label className="mb-1.5 block text-[12px] font-medium text-slate-300">
                  Description <span className="font-normal text-slate-500">(optional)</span>
                </label>
                <input
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="Brief description of what this metric evaluates"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-[12.5px] text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none"
                />
              </div>

              {isStructural ? (
                <div>
                  <label className="mb-1.5 block text-[12px] font-medium text-slate-300">
                    Parameters <span className="font-normal text-slate-500">(structural check: {editing?.config?.check ?? form.scoreName ?? "built-in"})</span>
                  </label>
                  <textarea
                    value={form.paramsJson}
                    onChange={(e) => setForm((f) => ({ ...f, paramsJson: e.target.value }))}
                    rows={4}
                    spellCheck={false}
                    className="w-full resize-y rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 font-mono text-[12px] text-slate-200 focus:border-blue-500/50 focus:outline-none"
                  />
                </div>
              ) : (
                <>
                  <div>
                    <label className="mb-1.5 block text-[12px] font-medium text-slate-300">Evaluation Prompt</label>
                    <textarea
                      value={form.prompt}
                      onChange={(e) => setForm((f) => ({ ...f, prompt: e.target.value }))}
                      rows={5}
                      placeholder="You are evaluating the quality of an AI assistant's response. Consider…"
                      className="w-full resize-y rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-[12.5px] leading-relaxed text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none"
                    />
                    <p className="mt-1 text-[11px] text-slate-500">
                      The trace content (request, answer, tool results / transcript / step I/O) is appended automatically.
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1.5 block text-[12px] font-medium text-slate-300">Model</label>
                      <input
                        value={form.model}
                        onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                        placeholder="default judge model"
                        className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 font-mono text-[12px] text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-[12px] font-medium text-slate-300">Output Type</label>
                      <select
                        value={form.outputType}
                        onChange={(e) => setForm((f) => ({ ...f, outputType: e.target.value as FormState["outputType"] }))}
                        className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-[12.5px] text-slate-200 focus:border-blue-500/50 focus:outline-none"
                      >
                        {OUTPUT_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {(form.outputType === "score" || form.outputType === "json") && (
                    <div>
                      <label className="mb-1.5 block text-[12px] font-medium text-slate-300">
                        Pass threshold <span className="font-normal text-slate-500">(0–1{form.outputType === "json" ? ", applied to a `score` field when present" : ""})</span>
                      </label>
                      <input
                        value={form.threshold}
                        onChange={(e) => setForm((f) => ({ ...f, threshold: e.target.value }))}
                        inputMode="decimal"
                        className="w-32 rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 font-mono text-[12px] text-slate-200 focus:border-blue-500/50 focus:outline-none"
                      />
                    </div>
                  )}

                  {form.outputType === "category" && (
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="mb-1.5 block text-[12px] font-medium text-slate-300">Categories</label>
                        <input
                          value={form.categories}
                          onChange={(e) => setForm((f) => ({ ...f, categories: e.target.value }))}
                          placeholder="question, complaint, other"
                          className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-[12px] text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="mb-1.5 block text-[12px] font-medium text-slate-300">
                          Failing categories <span className="font-normal text-slate-500">(optional)</span>
                        </label>
                        <input
                          value={form.failCategories}
                          onChange={(e) => setForm((f) => ({ ...f, failCategories: e.target.value }))}
                          placeholder="complaint"
                          className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-[12px] text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none"
                        />
                      </div>
                    </div>
                  )}
                </>
              )}

              <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-slate-300">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
                  className="accent-blue-500"
                />
                Run automatically on new traces
              </label>

              {error && <p className="text-[12px] text-rose-400">{error}</p>}

              <div className="flex items-center justify-between border-t border-slate-700/80 pt-4">
                <button
                  onClick={() => (editing ? onClose() : setStep("type"))}
                  className="rounded-lg border border-slate-700 px-3.5 py-1.5 text-[12.5px] text-slate-300 transition-colors hover:bg-slate-800"
                >
                  {editing ? "Cancel" : "Back"}
                </button>
                <button
                  onClick={() => void save()}
                  disabled={busy}
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-[12.5px] font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
                >
                  {busy && <span className="h-3 w-3 animate-spin rounded-full border-2 border-blue-300/40 border-t-white" />}
                  {editing ? "Save Changes" : "Create Column"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
