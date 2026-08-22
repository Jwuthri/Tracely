"use client";

import clsx from "clsx";
import { STEP_META, stepOutputs, type StepDraft, type StepNodeData, type StepType } from "@/app/lib/ruleFlow";
import { StepConfigForm } from "./StepConfigForm";
import { STEP_GLYPH } from "./nodes";
import { LABEL, TONE } from "./tone";
import { VariableChip } from "./VariableFields";

/** The inspector, docked under the canvas: input chips │ config form │ declared outputs.
 *  This is where the feature stops being a diagram and starts being a product. */

export type CatalogRow = {
  path: string;
  type: string;
  description: string;
  example?: unknown;
  sample?: unknown;
};

const groupOf = (path: string): string => {
  const dot = path.indexOf(".");
  return dot > 0 ? path.slice(0, dot) : path;
};

function InputPanel({ catalog, priorSteps }: { catalog: CatalogRow[]; priorSteps: StepDraft[] }) {
  const groups = new Map<string, CatalogRow[]>();
  for (const row of catalog) {
    const g = groupOf(row.path);
    groups.set(g, [...(groups.get(g) ?? []), row]);
  }
  return (
    <div className="flex h-full min-h-0 flex-col gap-3.5 overflow-y-auto bg-ink-900/40 p-3">
      <div className={LABEL}>Input</div>
      {catalog.length === 0 ? (
        <p className="text-[11px] text-fg-faint">Loading variables…</p>
      ) : (
        <div className="space-y-1.5">
          {[...groups.entries()].map(([group, rows]) => (
            <details key={group} open className="group rounded-lg border border-line/70 bg-ink-800/40">
              <summary className="flex cursor-pointer list-none items-center gap-1.5 px-2 py-1.5 font-mono text-[11px] text-fg [&::-webkit-details-marker]:hidden">
                <span aria-hidden className="text-fg-faint transition-transform group-open:rotate-90">
                  ›
                </span>
                {group}
                <span className="text-[10px] text-fg-faint">({rows.length})</span>
              </summary>
              <div className="flex flex-wrap gap-1 px-2 pb-2">
                {rows.map((row) => (
                  <VariableChip
                    key={row.path}
                    label={row.type === "array" ? `${row.path} []` : row.path}
                    token={`{{ ${row.path} }}`}
                    title={[
                      row.description,
                      row.sample !== undefined && row.sample !== null
                        ? `now: ${String(row.sample)}`
                        : row.example !== undefined
                          ? `e.g. ${JSON.stringify(row.example)}`
                          : "",
                    ]
                      .filter(Boolean)
                      .join("\n")}
                  />
                ))}
              </div>
            </details>
          ))}
        </div>
      )}

      <div className="space-y-2">
        <div className="text-[11px] font-medium text-fg">Prior steps</div>
        {priorSteps.length === 0 ? (
          <p className="text-[11px] leading-snug text-fg-faint">
            Nothing upstream on this branch. Wire a step before this one to read its output.
          </p>
        ) : (
          priorSteps.map((step, i) => (
            <div key={step.id}>
              <div className="mb-1 text-[11px] text-fg-muted">
                {i + 1}. {step.name}
              </div>
              <div className="flex flex-wrap gap-1">
                {stepOutputs(step.step_type, step.config).map((out) => (
                  <VariableChip
                    key={out.name}
                    label={`steps[${i}].result.${out.name}`}
                    token={`{{ steps[${i}].result.${out.name} }}`}
                    title={out.desc}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>
      <p className="mt-auto text-[11px] text-fg-faint">Drag a chip into any template field.</p>
    </div>
  );
}

function OutputPanel({
  stepType,
  config,
  runPosition,
  totalSteps,
}: {
  stepType: StepType;
  config: Record<string, unknown>;
  runPosition: number;
  totalSteps: number;
}) {
  const meta = STEP_META[stepType];
  const tone = TONE[meta?.tone ?? "info"];
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto bg-ink-900/40 p-3">
      <div className={LABEL}>Output</div>
      <p className="text-[11px] leading-snug text-fg-faint">
        Runs {runPosition} of {totalSteps}. Downstream steps read these with the{" "}
        <span className="font-mono">steps[i].result</span> chips in their own Input panel.
      </p>
      <ul className="space-y-1.5">
        {stepOutputs(stepType, config).map((out) => (
          <li key={out.name} className="rounded-lg border border-line bg-ink-800 px-2.5 py-1.5">
            <span className={clsx("font-mono text-[11px] font-medium", tone.fg)}>{out.name}</span>
            <span className="mt-0.5 block text-[10.5px] text-fg-faint">{out.desc}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function InspectorPanel({
  step,
  catalog,
  priorSteps,
  runPosition,
  totalSteps,
  isOrphan,
  modelOptions,
  onChange,
  onRemove,
}: {
  step: StepNodeData;
  catalog: CatalogRow[];
  priorSteps: StepDraft[];
  runPosition: number;
  totalSteps: number;
  isOrphan: boolean;
  modelOptions: string[];
  onChange: (next: StepNodeData) => void;
  onRemove: () => void;
}) {
  const meta = STEP_META[step.step_type];
  const tone = TONE[meta?.tone ?? "info"];
  return (
    <div className="flex min-h-0 flex-col overflow-hidden">
      <div className={clsx("flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-2.5", tone.tint)}>
        <div className="flex min-w-0 items-center gap-2.5">
          <span className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-md text-[13px]", tone.chip)}>
            {STEP_GLYPH[step.step_type] ?? "•"}
          </span>
          <div className="min-w-0">
            <div className={clsx("font-mono text-[9.5px] font-semibold uppercase tracking-[0.16em]", tone.fg)}>
              Step {runPosition} — {meta?.label ?? step.step_type}
            </div>
            <div className="truncate text-[13px] font-medium text-fg">{step.name || "Untitled step"}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isOrphan ? (
            <span className="rounded-md border border-warn/30 bg-warn/10 px-2 py-1 font-mono text-[10px] uppercase tracking-wide text-warn">
              parked · not wired
            </span>
          ) : null}
          <button
            onClick={onRemove}
            aria-label="Remove step"
            className="rounded-md px-2 py-1 text-[12px] text-fail transition-colors hover:bg-fail/10"
          >
            Delete
          </button>
        </div>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 divide-line lg:grid-cols-[210px_minmax(0,1fr)_230px] lg:divide-x">
        <InputPanel catalog={catalog} priorSteps={priorSteps} />
        <StepConfigForm step={step} modelOptions={modelOptions} onChange={onChange} />
        <OutputPanel
          stepType={step.step_type}
          config={step.config}
          runPosition={runPosition}
          totalSteps={totalSteps}
        />
      </div>
    </div>
  );
}
