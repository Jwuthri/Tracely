"use client";

import {
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import { useImperativeHandle, useRef, useState } from "react";
import {
  EDGE_DEFAULTS,
  RULE_TRIGGER_NODE_ID,
  applyEdgeDefaults,
  defaultStepConfig,
  flowToStepDrafts,
  newStepId,
  priorStepsOrdered,
  readStepNodeData,
  type RuleFlowHandle,
  type StepNodeData,
  type StepType,
} from "@/app/lib/ruleFlow";

/** All canvas state and every handler. The components above this are markup.
 *
 *  The canvas is the source of truth while you edit and hands the page a save payload on demand —
 *  no store, no debounced autosave, one imperative handle. */
export function useRuleFlow({
  initialNodes,
  initialEdges,
  handleRef,
}: {
  initialNodes: Node[];
  initialEdges: Edge[];
  handleRef: React.Ref<RuleFlowHandle | null>;
}) {
  const { screenToFlowPosition } = useReactFlow();
  const [nodes, setNodes, onNodesChangeBase] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges.map(applyEdgeDefaults));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const paneRef = useRef<HTMLDivElement>(null);

  useImperativeHandle(handleRef, () => ({
    getSavePayload: () => {
      const { drafts, error } = flowToStepDrafts(nodes, edges);
      return {
        steps: drafts,
        flow_layout: { nodes: structuredClone(nodes), edges: structuredClone(edges) },
        error,
      };
    },
    replaceFlow: (nextNodes, nextEdges) => {
      setNodes(() => structuredClone(nextNodes) as Node[]);
      setEdges(() => nextEdges.map((e) => applyEdgeDefaults(structuredClone(e) as Edge)));
      setSelectedId(null);
      setPickerOpen(false);
    },
  }));

  const stepIds = new Set(nodes.filter((n) => n.type === "ruleStep").map((n) => n.id));
  const pack = flowToStepDrafts(nodes, edges);
  const drafts = pack.error !== null ? [] : pack.drafts;
  const selectedNode = selectedId !== null ? nodes.find((n) => n.id === selectedId) : undefined;
  const selectedStep = selectedNode?.type === "ruleStep" ? readStepNodeData(selectedNode.data) : undefined;
  const priorSteps =
    selectedId !== null && pack.error === null ? priorStepsOrdered(selectedId, drafts, edges, stepIds) : [];
  const runPos = selectedId !== null ? drafts.findIndex((d) => d.id === selectedId) : -1;

  return {
    nodes,
    edges,
    // The trigger node is undeletable, and filtering the CHANGE is what makes that true — the
    // `deletable: false` flag alone doesn't survive every path into a remove.
    onNodesChange: (changes: NodeChange[]) =>
      onNodesChangeBase(changes.filter((c) => !(c.type === "remove" && "id" in c && c.id === RULE_TRIGGER_NODE_ID))),
    onEdgesChange,
    onConnect: (params: Connection) => {
      if (!params.source || !params.target) return;
      if (params.target === RULE_TRIGGER_NODE_ID) return; // nothing connects INTO the trigger
      setEdges((eds) =>
        addEdge({ ...EDGE_DEFAULTS, ...params, id: `e-${params.source}-${params.target}` }, eds),
      );
    },
    onSelectionChange: (p: { nodes: Node[]; edges: Edge[] }) => {
      if (p.edges.length > 0 && p.nodes.length === 0) {
        setSelectedId(null);
        return;
      }
      setSelectedId(p.nodes[0]?.id ?? null);
    },
    onEdgeClick: () => {
      // Blur first: otherwise Backspace deletes a character in the inspector instead of the edge.
      const active = typeof document !== "undefined" ? document.activeElement : null;
      if (active instanceof HTMLElement) active.blur();
    },
    onPaneClick: () => {
      setSelectedId(null);
      setPickerOpen(false);
    },
    selectedId,
    selectedStep,
    triggerSelected: selectedId === RULE_TRIGGER_NODE_ID,
    priorSteps,
    runPosition: runPos >= 0 ? runPos + 1 : 1,
    totalSteps: drafts.length,
    orphanIds: pack.orphanIds,
    error: pack.error,
    stepCount: stepIds.size,
    pickerOpen,
    setPickerOpen,
    setSelectedId,
    paneRef,
    addStep: (stepType: StepType) => {
      const id = newStepId();
      const count = stepIds.size;
      // Land at the centre of the PANE, not the window, with a small offset per add so repeated
      // adds fan out instead of stacking.
      const rect = paneRef.current?.getBoundingClientRect();
      const base = screenToFlowPosition({
        x: rect ? rect.left + rect.width / 2 : 400,
        y: rect ? rect.top + rect.height / 2 : 240,
      });
      setNodes((ns) => [
        ...ns,
        {
          id,
          type: "ruleStep",
          position: { x: base.x + (count % 5) * 30, y: base.y + (count % 4) * 26 },
          data: {
            name: `Step ${count + 1}`,
            step_type: stepType,
            config: defaultStepConfig(stepType),
          } as unknown as Record<string, unknown>,
        },
      ]);
      setSelectedId(id);
      setPickerOpen(false);
    },
    removeSelected: () => {
      if (selectedId === null || selectedId === RULE_TRIGGER_NODE_ID) return;
      setNodes((ns) => ns.filter((n) => n.id !== selectedId));
      setEdges((es) => es.filter((e) => e.source !== selectedId && e.target !== selectedId));
      setSelectedId(null);
    },
    updateSelected: (next: StepNodeData) => {
      if (selectedId === null) return;
      setNodes((ns) =>
        ns.map((n) => (n.id === selectedId ? { ...n, data: { ...next } as unknown as Record<string, unknown> } : n)),
      );
    },
    setTriggerLabel: (label: string, filters: string) => {
      setNodes((ns) =>
        ns.map((n) =>
          n.id === RULE_TRIGGER_NODE_ID ? { ...n, data: { ...(n.data ?? {}), label, filters } } : n,
        ),
      );
    },
  };
}
