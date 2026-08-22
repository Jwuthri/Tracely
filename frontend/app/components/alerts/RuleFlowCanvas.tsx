"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeTypes,
} from "@xyflow/react";
import clsx from "clsx";
import { forwardRef, useState } from "react";
import type { AgentRow } from "@/app/lib/api";
import type { Draft } from "@/app/lib/alerts";
import type { RuleFlowHandle, StepType } from "@/app/lib/ruleFlow";
import { InspectorPanel, type CatalogRow } from "./InspectorPanel";
import { TriggerConfigForm } from "./TriggerConfigForm";
import { NodePicker, RuleStepNode, TriggerNode } from "./nodes";
import { useRuleFlow } from "./useRuleFlow";

/** The flow builder: a pan/zoom canvas of nodes over a docked inspector.
 *
 *  `ReactFlowProvider` has to sit OUTSIDE the component that calls `useReactFlow()`, which is the
 *  only reason this file is two components. */

const nodeTypes: NodeTypes = { trigger: TriggerNode, ruleStep: RuleStepNode };

type Props = {
  initialNodes: Node[];
  initialEdges: Edge[];
  /** The trigger half of the rule, edited in the When node's inspector. */
  draft: Draft;
  onDraftChange: (patch: Partial<Draft>) => void;
  agents: AgentRow[];
  scoreNames: string[];
  catalog: CatalogRow[];
  modelOptions: string[];
};

export const RuleFlowCanvas = forwardRef<RuleFlowHandle, Props>(function RuleFlowCanvas(props, ref) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} handleRef={ref} />
    </ReactFlowProvider>
  );
});

function CanvasInner({
  initialNodes,
  initialEdges,
  draft,
  onDraftChange,
  agents,
  scoreNames,
  catalog,
  modelOptions,
  handleRef,
}: Props & { handleRef: React.Ref<RuleFlowHandle | null> }) {
  const c = useRuleFlow({ initialNodes, initialEdges, handleRef });
  const [fullscreen, setFullscreen] = useState(false);

  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-[11.5px] text-fg-muted">
          <span className="font-medium text-fg">
            {c.stepCount} step{c.stepCount === 1 ? "" : "s"}
          </span>
          <span className="hidden sm:inline text-fg-faint">
            · drag from a handle to wire, then use the Prior-steps chips for{" "}
            <span className="font-mono">{"{{ steps[i].result }}"}</span>
          </span>
          {c.error !== null ? (
            <span className="rounded-md border border-fail/30 bg-fail/10 px-2 py-0.5 font-mono text-[10.5px] uppercase tracking-wide text-fail">
              fix the cycle to save
            </span>
          ) : null}
          {c.error === null && c.orphanIds.length > 0 ? (
            <span className="rounded-md border border-warn/30 bg-warn/10 px-2 py-0.5 font-mono text-[10.5px] uppercase tracking-wide text-warn">
              {c.orphanIds.length} parked
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setFullscreen((f) => !f)} className="btn-ghost text-[12px]">
            {fullscreen ? "Shrink" : "Expand"}
          </button>
          <div className="relative">
            <button onClick={() => c.setPickerOpen((p) => !p)} className="btn-primary text-[12.5px]">
              + Add step
            </button>
            {c.pickerOpen ? (
              <NodePicker onClose={() => c.setPickerOpen(false)} onPick={(t: StepType) => c.addStep(t)} />
            ) : null}
          </div>
        </div>
      </div>

      <div
        ref={c.paneRef}
        className={clsx("relative w-full bg-ink-900/50 transition-[height]", fullscreen ? "h-[680px]" : "h-[420px]")}
      >
        <ReactFlow
          nodes={c.nodes}
          edges={c.edges}
          onNodesChange={c.onNodesChange}
          onEdgesChange={c.onEdgesChange}
          onConnect={c.onConnect}
          onSelectionChange={c.onSelectionChange}
          onEdgeClick={c.onEdgeClick}
          onPaneClick={c.onPaneClick}
          nodeTypes={nodeTypes}
          deleteKeyCode={["Backspace", "Delete"]}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          minZoom={0.3}
          maxZoom={1.8}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1.1} color="rgb(var(--c-fg-faint) / 0.35)" />
          <Controls className="!rounded-lg !border !border-line !bg-ink-800 !shadow-panel [&_button]:!border-line [&_button]:!bg-ink-800 [&_button]:!fill-fg-muted [&_button:hover]:!bg-ink-700" />
        </ReactFlow>
      </div>

      <div className="border-t border-line">
        {c.triggerSelected ? (
          <TriggerConfigForm draft={draft} agents={agents} scoreNames={scoreNames} onChange={onDraftChange} />
        ) : c.selectedStep !== undefined && c.selectedId !== null ? (
          <InspectorPanel
            step={c.selectedStep}
            catalog={catalog}
            priorSteps={c.priorSteps}
            runPosition={c.runPosition}
            totalSteps={c.totalSteps}
            isOrphan={c.orphanIds.includes(c.selectedId)}
            modelOptions={modelOptions}
            onChange={c.updateSelected}
            onRemove={c.removeSelected}
          />
        ) : (
          <div className="px-4 py-10 text-center text-[13px] text-fg-faint">
            Select the <span className="text-fg-muted">When</span> node to choose what fires this alert, or a step to
            configure what it does.
          </div>
        )}
      </div>
    </section>
  );
}
