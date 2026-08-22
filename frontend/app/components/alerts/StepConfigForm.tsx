"use client";

import clsx from "clsx";
import {
  STEP_META,
  STEP_ORDER,
  defaultStepConfig,
  type HeaderEntry,
  type OutputField,
  type StepConfig,
  type StepNodeData,
  type StepType,
} from "@/app/lib/ruleFlow";
import { FIELD, LABEL, ROW_FIELD } from "./tone";
import { VariableInput, VariableTextarea } from "./VariableFields";

/** The middle column: step type, name, and the fields for whichever type is selected.
 *  Every string field here is a Jinja template rendered against the Input panel's chips. */

type Patch = (patch: StepConfig) => void;

const str = (c: StepConfig, k: string): string => (typeof c[k] === "string" ? (c[k] as string) : "");
const num = (c: StepConfig, k: string, dflt = 0): number => (typeof c[k] === "number" ? (c[k] as number) : dflt);

export function StepConfigForm({
  step,
  modelOptions,
  onChange,
}: {
  step: StepNodeData;
  modelOptions: string[];
  onChange: (next: StepNodeData) => void;
}) {
  const patch: Patch = (p) => onChange({ ...step, config: { ...step.config, ...p } });
  return (
    <div className="space-y-3.5 overflow-y-auto px-4 py-3.5">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor="step-type" className={LABEL}>
            Step type
          </label>
          <select
            id="step-type"
            value={step.step_type}
            onChange={(e) => {
              const next = e.target.value as StepType;
              // Switching type replaces the config: the old keys mean nothing to the new runner,
              // and leaving them makes a step that looks configured but sends nothing.
              onChange({ name: step.name, step_type: next, config: defaultStepConfig(next) });
            }}
            className={FIELD}
          >
            {STEP_ORDER.map((t) => (
              <option key={t} value={t}>
                {STEP_META[t].label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor="step-name" className={LABEL}>
            Step name
          </label>
          <input
            id="step-name"
            value={step.name}
            onChange={(e) => onChange({ ...step, name: e.target.value })}
            className={FIELD}
          />
        </div>
      </div>
      <p className="text-[11.5px] leading-snug text-fg-muted">{STEP_META[step.step_type]?.blurb}</p>

      {step.step_type === "condition" ? <ConditionFields config={step.config} patch={patch} /> : null}
      {step.step_type === "slack" ? <SlackFields config={step.config} patch={patch} /> : null}
      {step.step_type === "send_email" ? <EmailFields config={step.config} patch={patch} /> : null}
      {step.step_type === "webhook" ? <WebhookFields config={step.config} patch={patch} /> : null}
      {step.step_type === "llm_prompt" ? (
        <LlmFields config={step.config} patch={patch} modelOptions={modelOptions} />
      ) : null}
      {step.step_type === "python_expression" ? <PythonFields config={step.config} patch={patch} /> : null}
    </div>
  );
}

function Examples({ items, onPick }: { items: string[]; onPick: (v: string) => void }) {
  return (
    <div className="space-y-1.5">
      <div className={LABEL}>Examples</div>
      <ul className="space-y-1">
        {items.map((s) => (
          <li key={s}>
            <button
              onClick={() => onPick(s)}
              className="w-full truncate rounded-md border border-line bg-ink-700 px-2 py-1 text-left font-mono text-[11px] text-fg-muted transition-colors hover:border-signal/50 hover:text-fg"
            >
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ConditionFields({ config, patch }: { config: StepConfig; patch: Patch }) {
  return (
    <>
      <VariableTextarea
        id="cond-expr"
        label="Expression"
        value={str(config, "expression")}
        onChange={(v) => patch({ expression: v })}
        rows={3}
        hint="Renders to truthy/falsy. Empty, False, None, 0 or [] → the rest of the flow is skipped."
      />
      <Examples
        items={[
          "{{ 'refund' in failure_reason | lower }}",
          "{{ agent.slug == 'support-bot' }}",
          "{{ gate.pr_number > 0 }}",
          "{{ trace.latency_ms > 5000 }}",
        ]}
        onPick={(v) => patch({ expression: v })}
      />
    </>
  );
}

function SlackFields({ config, patch }: { config: StepConfig; patch: Patch }) {
  return (
    <>
      <VariableInput
        id="slack-url"
        label="Incoming webhook URL"
        value={str(config, "url")}
        onChange={(v) => patch({ url: v })}
        placeholder="https://hooks.slack.com/services/…"
      />
      <VariableTextarea
        id="slack-text"
        label="Message"
        value={str(config, "text_template")}
        onChange={(v) => patch({ text_template: v })}
        rows={5}
        hint="Slack mrkdwn. Drag chips in for the link, the reason, the agent."
      />
    </>
  );
}

function EmailFields({ config, patch }: { config: StepConfig; patch: Patch }) {
  return (
    <>
      <VariableInput
        id="mail-to"
        label="To"
        value={str(config, "to_template")}
        onChange={(v) => patch({ to_template: v })}
        placeholder="oncall@acme.com"
        hint="A comma list, or a chip that renders one — both are accepted."
      />
      <VariableInput
        id="mail-subject"
        label="Subject"
        value={str(config, "subject_template")}
        onChange={(v) => patch({ subject_template: v })}
        placeholder="[Tracely] {{ alert.name }}"
      />
      <VariableTextarea
        id="mail-body"
        label="Body"
        value={str(config, "body_template")}
        onChange={(v) => patch({ body_template: v })}
        rows={6}
      />
      <label className="flex items-center gap-2 text-[12px] text-fg">
        <input
          type="checkbox"
          checked={config.body_is_html === true}
          onChange={(e) => patch({ body_is_html: e.target.checked })}
          className="h-3.5 w-3.5 accent-signal"
        />
        Body is HTML
      </label>
    </>
  );
}

const METHODS = ["POST", "PUT", "PATCH", "GET", "DELETE"];

function WebhookFields({ config, patch }: { config: StepConfig; patch: Patch }) {
  const headers = Array.isArray(config.headers) ? (config.headers as HeaderEntry[]) : [];
  const setHeaders = (next: HeaderEntry[]) => patch({ headers: next });
  return (
    <>
      <VariableInput
        id="hook-url"
        label="URL"
        value={str(config, "url")}
        onChange={(v) => patch({ url: v })}
        placeholder="https://acme.com/hooks/tracely"
      />
      <div className="space-y-1">
        <label htmlFor="hook-method" className={LABEL}>
          Method
        </label>
        <select
          id="hook-method"
          value={str(config, "method") || "POST"}
          onChange={(e) => patch({ method: e.target.value })}
          className={FIELD}
        >
          {METHODS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-2">
        <div className={LABEL}>Headers</div>
        {headers.map((h, i) => (
          <div key={i} className="flex gap-2">
            <input
              aria-label={`Header name ${i + 1}`}
              placeholder="Authorization"
              value={h.key}
              onChange={(e) => setHeaders(headers.map((x, j) => (i === j ? { ...x, key: e.target.value } : x)))}
              className={clsx(ROW_FIELD, "w-[38%]")}
            />
            <input
              aria-label={`Header value ${i + 1}`}
              placeholder="Bearer …"
              value={h.value}
              onChange={(e) => setHeaders(headers.map((x, j) => (i === j ? { ...x, value: e.target.value } : x)))}
              className={clsx(ROW_FIELD, "flex-1")}
            />
            <button
              onClick={() => setHeaders(headers.filter((_, j) => j !== i))}
              aria-label={`Remove header ${i + 1}`}
              className="rounded-md border border-line px-2 text-[12px] text-fg-faint hover:text-fg"
            >
              ×
            </button>
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setHeaders([...headers, { key: "", value: "" }])}
            className="rounded-md border border-line bg-ink-700 px-2 py-1 text-[11px] text-fg transition-colors hover:border-line-bright"
          >
            + Header
          </button>
          {/* The case everyone actually needs, one click instead of typing the two words. */}
          <button
            onClick={() => setHeaders([...headers, { key: "Authorization", value: "Bearer " }])}
            className="rounded-md border border-line bg-ink-700 px-2 py-1 text-[11px] text-fg-muted transition-colors hover:border-signal/50 hover:text-fg"
          >
            + Bearer token
          </button>
        </div>
        <p className="text-[11px] text-fg-faint">
          Header values are templates too — a token from an earlier step works here.
        </p>
      </div>
      <VariableTextarea
        id="hook-body"
        label="Body template"
        value={str(config, "body_template")}
        onChange={(v) => patch({ body_template: v })}
        rows={6}
        hint="Sent as-is with Content-Type: application/json. Leave empty for a body-less request."
      />
      <Examples
        items={[
          '{"text": "{{ alert.summary }}", "url": "{{ alert.url }}"}',
          '{"title": "{{ alert.name }}", "body": "{{ failure_reason }}", "labels": ["tracely"]}',
        ]}
        onPick={(v) => patch({ body_template: v })}
      />
    </>
  );
}

const SCHEMA_TYPES: OutputField["type"][] = ["string", "number", "boolean", "array"];

function LlmFields({
  config,
  patch,
  modelOptions,
}: {
  config: StepConfig;
  patch: Patch;
  modelOptions: string[];
}) {
  const schema = Array.isArray(config.output_schema) ? (config.output_schema as OutputField[]) : [];
  const model = str(config, "model");
  const options = model && !modelOptions.includes(model) ? [model, ...modelOptions] : modelOptions;
  return (
    <>
      <div className="space-y-1">
        <label htmlFor="llm-model" className={LABEL}>
          Model
        </label>
        <select id="llm-model" value={model} onChange={(e) => patch({ model: e.target.value })} className={FIELD}>
          <option value="">workspace default</option>
          {options.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <p className="text-[11px] text-fg-faint">Runs on this workspace&apos;s OpenRouter key.</p>
      </div>
      <VariableTextarea
        id="llm-system"
        label="System prompt"
        value={str(config, "system_prompt")}
        onChange={(v) => patch({ system_prompt: v })}
        rows={3}
      />
      <VariableTextarea
        id="llm-user"
        label="Prompt"
        value={str(config, "user_prompt_template")}
        onChange={(v) => patch({ user_prompt_template: v })}
        rows={6}
        hint="Drag chips in — the failing turn's input/output and the judges' reason are the useful ones."
      />
      <div className="space-y-1">
        <label htmlFor="llm-temp" className={LABEL}>
          Temperature
        </label>
        <input
          id="llm-temp"
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={num(config, "temperature")}
          onChange={(e) => patch({ temperature: Number(e.target.value) })}
          className={FIELD}
        />
      </div>
      <div className="space-y-2">
        <div className={LABEL}>Structured output</div>
        {schema.map((row, i) => (
          <div key={i} className="flex gap-2">
            <input
              aria-label={`Field name ${i + 1}`}
              placeholder="severity"
              value={row.name}
              onChange={(e) =>
                patch({ output_schema: schema.map((x, j) => (i === j ? { ...x, name: e.target.value } : x)) })
              }
              className={clsx(ROW_FIELD, "w-[30%]")}
            />
            <select
              aria-label={`Field type ${i + 1}`}
              value={row.type}
              onChange={(e) =>
                patch({
                  output_schema: schema.map((x, j) =>
                    i === j ? { ...x, type: e.target.value as OutputField["type"] } : x,
                  ),
                })
              }
              className={clsx(ROW_FIELD, "w-[22%]")}
            >
              {SCHEMA_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <input
              aria-label={`Field description ${i + 1}`}
              placeholder="how bad is it"
              value={row.description}
              onChange={(e) =>
                patch({
                  output_schema: schema.map((x, j) => (i === j ? { ...x, description: e.target.value } : x)),
                })
              }
              className={clsx(ROW_FIELD, "flex-1")}
            />
            <button
              onClick={() => patch({ output_schema: schema.filter((_, j) => j !== i) })}
              aria-label={`Remove field ${i + 1}`}
              className="rounded-md border border-line px-2 text-[12px] text-fg-faint hover:text-fg"
            >
              ×
            </button>
          </div>
        ))}
        <button
          onClick={() => patch({ output_schema: [...schema, { name: "", type: "string", description: "" }] })}
          className="rounded-md border border-line bg-ink-700 px-2 py-1 text-[11px] text-fg transition-colors hover:border-line-bright"
        >
          + Field
        </button>
        <p className="text-[11px] text-fg-faint">
          Declare fields and the next step reads them as{" "}
          <span className="font-mono">steps[i].result.&lt;field&gt;</span>. With none, the answer arrives as{" "}
          <span className="font-mono">.text</span>.
        </p>
      </div>
    </>
  );
}

function PythonFields({ config, patch }: { config: StepConfig; patch: Patch }) {
  return (
    <>
      <div className="space-y-1">
        <label htmlFor="py-expr" className={LABEL}>
          Expression
        </label>
        <input
          id="py-expr"
          spellCheck={false}
          value={str(config, "expression")}
          onChange={(e) => patch({ expression: e.target.value })}
          placeholder="len(failing_evaluators) > 1"
          className={FIELD}
        />
        <p className="text-[11px] leading-snug text-fg-faint">
          One expression, evaluated against the context by name (no <span className="font-mono">{"{{ }}"}</span>).
          Comprehensions and arithmetic yes; <span className="font-mono">import</span>,{" "}
          <span className="font-mono">def</span> and dunder access are blocked. The value becomes{" "}
          <span className="font-mono">steps[i].result</span>.
        </p>
      </div>
      <Examples
        items={[
          "len(failing_evaluators)",
          "round((metric.get('value') or 0) * 100)",
          "[s['name'] for s in scores if s['verdict'] == 'FAIL']",
        ]}
        onPick={(v) => patch({ expression: v })}
      />
    </>
  );
}
