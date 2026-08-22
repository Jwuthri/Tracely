"use client";

import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentRow, Monitor } from "@/app/lib/api";
import { TRIGGERS, draftProblem, toBody, triggerSummary, type Draft } from "@/app/lib/alerts";
import { listJudgeModels } from "@/app/lib/evaluators";
import {
  buildFlowFromRule,
  newStepId,
  type FlowLayout,
  type RuleFlowHandle,
  type StepDraft,
} from "@/app/lib/ruleFlow";
import { Toggle } from "../Toggle";
import { AssistantPanel, type GeneratedDraft } from "./AssistantPanel";
import { ExecutionCard, type Execution } from "./ExecutionCard";
import { RuleFlowCanvas } from "./RuleFlowCanvas";
import type { CatalogRow } from "./InspectorPanel";
import { FIELD, LABEL } from "./tone";

/** The alert editor: name + description, the flow canvas, save, a real test run, and the history.
 *
 *  The canvas owns the graph while you edit and hands over a payload on demand (`getSavePayload`),
 *  so there is no second copy of the flow in this component to drift from what you see. */

export function RuleEditor({
  monitorId,
  initialDraft,
  initialSteps,
  initialLayout,
  agents,
  scoreNames,
}: {
  /** null = a new rule; the first save redirects to its own page. */
  monitorId: string | null;
  initialDraft: Draft;
  initialSteps: StepDraft[];
  initialLayout: FlowLayout | null;
  agents: AgentRow[];
  scoreNames: string[];
}) {
  const router = useRouter();
  const flowRef = useRef<RuleFlowHandle | null>(null);
  const [draft, setDraft] = useState(initialDraft);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [catalog, setCatalog] = useState<CatalogRow[]>([]);
  const [subjects, setSubjects] = useState<{ id: string; label: string; detail?: string }[]>([]);
  const [subjectId, setSubjectId] = useState("");
  const [testing, setTesting] = useState(false);
  const [testRun, setTestRun] = useState<Execution | null>(null);
  const [history, setHistory] = useState<Execution[]>([]);
  const [modelOptions, setModelOptions] = useState<string[]>([]);

  // The LLM step's model list is the evaluators' judge-model allowlist — one catalog, not two.
  useEffect(() => {
    let alive = true;
    void listJudgeModels()
      .then((m) => {
        if (alive) setModelOptions(m.models.map((x) => x.id));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  const patchDraft = useCallback((patch: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setSaved(false);
  }, []);

  // The chip catalog is per trigger: a gate alert must not offer `trace.*` variables that will
  // always render empty.
  useEffect(() => {
    let alive = true;
    void fetch(`/api/monitors/inputs/schema?trigger=${encodeURIComponent(draft.type)}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows) => {
        if (alive && Array.isArray(rows)) setCatalog(rows);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [draft.type]);

  // What we can test against, also per trigger (recent failing turns / gate runs / clusters).
  useEffect(() => {
    let alive = true;
    void fetch(`/api/monitors/subjects?trigger=${encodeURIComponent(draft.type)}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows) => {
        if (!alive || !Array.isArray(rows)) return;
        setSubjects(rows);
        setSubjectId((cur) => cur || (rows[0]?.id ?? ""));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [draft.type]);

  const loadHistory = useCallback(async (id: string) => {
    const r = await fetch(`/api/monitors/${id}/executions?limit=10`);
    if (r.ok) setHistory(await r.json());
  }, []);

  useEffect(() => {
    if (monitorId) void loadHistory(monitorId);
  }, [monitorId, loadHistory]);

  /** Push a generated draft onto the live canvas without a remount, and fold its trigger half into
   *  the form. Fresh step ids: the generator's are placeholders, and two drafts in a row must not
   *  collide on the same node id. */
  function applyGenerated(g: GeneratedDraft) {
    const steps: StepDraft[] = (g.steps ?? []).map((s, i) => ({
      id: newStepId(),
      order_index: i,
      name: s.name,
      step_type: s.step_type,
      config: s.config,
    }));
    const cond = g.condition ?? { type: draft.type };
    const nextType = (cond.type as Draft["type"]) ?? draft.type;
    patchDraft({
      name: g.name || draft.name,
      description: g.description || draft.description,
      target_agent: g.target_agent ?? draft.target_agent,
      type: nextType,
      contains: (cond.contains as string) ?? "",
      score_name: (cond.score_name as string) ?? "",
      env: (cond.env as string) ?? "",
      threshold: (cond.threshold as number) ?? draft.threshold,
      window_minutes: (cond.window_minutes as number) ?? draft.window_minutes,
      min_samples: (cond.min_samples as number) ?? draft.min_samples,
    });
    const next = buildFlowFromRule({
      steps,
      flow_layout: null,
      triggerLabel: TRIGGERS[nextType].label,
    });
    flowRef.current?.replaceFlow(next.nodes, next.edges);
  }

  const flow = buildFlowFromRule({
    steps: initialSteps,
    flow_layout: initialLayout,
    triggerLabel: TRIGGERS[initialDraft.type].label,
  });

  async function save() {
    setErr(null);
    setSaved(false);
    const problem = draftProblem(draft);
    if (problem) return setErr(problem);
    const payload = flowRef.current?.getSavePayload();
    if (!payload) return setErr("The canvas is not ready yet.");
    if (payload.error !== null) return setErr(payload.error);
    if (payload.steps.length === 0) {
      return setErr("Add a step and wire it to the When node — a rule with nothing wired does nothing.");
    }
    setSaving(true);
    try {
      const body = { ...toBody(draft), steps: payload.steps, flow_layout: payload.flow_layout };
      const r = await fetch(monitorId ? `/api/monitors/${monitorId}` : "/api/monitors", {
        method: monitorId ? "PATCH" : "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `Could not save (HTTP ${r.status}).`);
        return;
      }
      setSaved(true);
      if (!monitorId && d?.id) {
        // A new rule gets its own URL, so Test and the run history have something to talk about.
        router.replace(`/settings/alerts/${d.id}`);
        router.refresh();
        return;
      }
      router.refresh();
    } catch {
      setErr("Could not save: the server is unreachable.");
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    if (!monitorId) {
      setErr("Save the rule first — a test run needs somewhere to record itself.");
      return;
    }
    setTesting(true);
    setErr(null);
    setTestRun(null);
    try {
      const r = await fetch(`/api/monitors/${monitorId}/test`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ subject_id: subjectId }),
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        setErr(d?.detail ?? `Test failed (HTTP ${r.status}).`);
        return;
      }
      if (d?.execution) setTestRun(d.execution);
      void loadHistory(monitorId);
    } catch {
      setErr("Could not run the test: the server is unreachable.");
    } finally {
      setTesting(false);
    }
  }

  const isEvent = TRIGGERS[draft.type].family === "event";

  return (
    <div className="space-y-5">
      <section className="card px-4 py-4">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <div className="space-y-1">
            <label htmlFor="rule-name" className={LABEL}>
              Name
            </label>
            <input
              id="rule-name"
              value={draft.name}
              onChange={(e) => patchDraft({ name: e.target.value })}
              placeholder="Page on-call when the gate fails"
              className={FIELD}
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="rule-desc" className={LABEL}>
              Description
            </label>
            <input
              id="rule-desc"
              value={draft.description}
              onChange={(e) => patchDraft({ description: e.target.value })}
              placeholder="Optional"
              className={FIELD}
            />
          </div>
          <div className="flex items-end gap-3">
            <Toggle
              checked={draft.enabled}
              onChange={(enabled) => patchDraft({ enabled })}
              label={draft.enabled ? "armed" : "off"}
            />
            <button onClick={save} disabled={saving} className="btn-primary">
              {saving ? "Saving…" : monitorId ? "Save" : "Create alert"}
            </button>
          </div>
        </div>
        <p className="mt-2 font-mono text-[11px] text-fg-faint">
          {TRIGGERS[draft.type].label} · {triggerSummary(draft)}
        </p>
        {err !== null ? (
          <p role="alert" className="mt-2 text-[12.5px] text-fail">
            {err}
          </p>
        ) : null}
        {saved ? <p className="mt-2 text-[12.5px] text-ok">Saved.</p> : null}
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px] xl:items-start">
        <RuleFlowCanvas
          ref={flowRef}
          initialNodes={flow.nodes}
          initialEdges={flow.edges}
          draft={draft}
          onDraftChange={patchDraft}
          agents={agents}
          scoreNames={scoreNames}
          catalog={catalog}
          modelOptions={modelOptions}
        />
        <AssistantPanel
          draft={draft}
          steps={() => flowRef.current?.getSavePayload().steps ?? []}
          onApply={applyGenerated}
        />
      </div>

      <section className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <span className="text-[13px] font-semibold text-fg">Test this flow</span>
            <p className="mt-0.5 text-[11.5px] text-warn">
              Real side effects: it posts to Slack, mails the address and calls your webhook — the same code path the
              real alert uses.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            {isEvent ? (
              <label className="space-y-1">
                <span className={clsx(LABEL, "block")}>Run against</span>
                <select
                  value={subjectId}
                  onChange={(e) => setSubjectId(e.target.value)}
                  className={clsx(FIELD, "min-w-[240px]")}
                >
                  {subjects.length === 0 ? <option value="">nothing to test against yet</option> : null}
                  {subjects.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                      {s.detail ? ` · ${s.detail}` : ""}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="max-w-[280px] text-[11.5px] text-fg-faint">
                A threshold rule has no subject — the test renders the flow against the metric as it reads right now.
              </p>
            )}
            <button onClick={runTest} disabled={testing || !monitorId} className="btn-ghost text-[12.5px]">
              {testing ? "Running…" : "Run test"}
            </button>
          </div>
        </div>
        {testRun ? (
          <div className="px-4 py-3">
            <ExecutionCard execution={testRun} title="Test run" />
          </div>
        ) : null}
      </section>

      {history.length > 0 ? (
        <section className="card overflow-hidden">
          <div className="border-b border-line px-4 py-3 text-[13px] font-semibold text-fg">
            Recent runs <span className="font-mono text-[11px] text-fg-faint">({history.length})</span>
          </div>
          <div className="space-y-3 px-4 py-3">
            {history.map((ex) => (
              <ExecutionCard key={ex.id} execution={ex} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

/** Shape a saved rule into the editor's two halves. */
export function draftFromMonitor(m: Monitor): { steps: StepDraft[]; layout: FlowLayout | null } {
  return {
    steps: (m.steps ?? []) as StepDraft[],
    layout: (m.flow_layout ?? null) as FlowLayout | null,
  };
}
