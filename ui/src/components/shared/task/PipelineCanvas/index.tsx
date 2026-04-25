/**
 * PipelineCanvas — workflowbuilder.io-style three-pane pipeline editor.
 *
 * - Left: Nodes Library (palette of step types, click-to-add).
 * - Center: Canvas (pan / zoom / drag nodes, edges with conditional gates).
 * - Right: Config Panel (selected step / edge fields, reuses step-editor siblings).
 *
 * Round-trips through the same `steps[]` form state as the Visual + JSON tabs.
 * Position metadata lives on `Task.layout`; the runtime never reads it. No
 * autosave — Save commits steps + layout together.
 */
import { useCallback, useMemo, useState } from "react";
import type { StepDef, StepType, TaskLayout } from "@/src/api/hooks/useTasks";
import type { ToolItem } from "@/src/api/hooks/useTools";
import { emptyStep } from "../TaskStepEditorModel";
import { Canvas } from "./Canvas";
import { ConfigPanel } from "./ConfigPanel";
import { NodesLibrary } from "./NodesLibrary";
import { setNodePosition } from "./layout";
import { edgeKey } from "./EdgeLayer";
import { staleWhenStepRefs, type EdgeDescriptor } from "./edges";

interface PipelineCanvasProps {
  steps: StepDef[];
  layout: TaskLayout;
  tools: ToolItem[];
  readOnly?: boolean;
  onChangeSteps: (steps: StepDef[]) => void;
  onChangeLayout: (layout: TaskLayout) => void;
  onJumpToJson: () => void;
}

export function PipelineCanvas({
  steps,
  layout,
  tools,
  readOnly,
  onChangeSteps,
  onChangeLayout,
  onJumpToJson,
}: PipelineCanvasProps) {
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<EdgeDescriptor | null>(null);
  const selectedEdgeKey = useMemo(
    () => (selectedEdge ? edgeKey(selectedEdge) : null),
    [selectedEdge],
  );
  const staleStepIds = useMemo(() => staleWhenStepRefs(steps), [steps]);

  const handleAddStep = useCallback(
    (type: StepType) => {
      if (readOnly) return;
      const fresh = emptyStep(type);
      const camera = layout.camera ?? { x: 0, y: 0, scale: 1 };
      // Place at viewport center — the canvas mounts a transform anchored at
      // (0,0), so "center" in world space is just (camera.x, camera.y) plus
      // half a typical viewport. We don't know the viewport size from here,
      // so use a small offset relative to camera origin; drag is trivial.
      const placeAt = { x: camera.x + 80, y: camera.y + 80 };
      const nextLayout = setNodePosition(layout, fresh.id, placeAt);
      onChangeSteps([...steps, fresh]);
      onChangeLayout(nextLayout);
      setSelectedStepId(fresh.id);
      setSelectedEdge(null);
    },
    [readOnly, layout, steps, onChangeSteps, onChangeLayout],
  );

  const handleUpdateStep = useCallback(
    (id: string, updated: StepDef) => {
      const next = steps.map((s) => (s.id === id ? updated : s));
      onChangeSteps(next);
      // If id changed, propagate to layout + selection.
      if (updated.id !== id && layout.nodes && layout.nodes[id]) {
        const { [id]: oldPos, ...rest } = layout.nodes;
        onChangeLayout({ ...layout, nodes: { ...rest, [updated.id]: oldPos } });
        setSelectedStepId(updated.id);
      }
    },
    [steps, layout, onChangeSteps, onChangeLayout],
  );

  const handleDeleteStep = useCallback(
    (id: string) => {
      onChangeSteps(steps.filter((s) => s.id !== id));
      if (layout.nodes && layout.nodes[id]) {
        const { [id]: _omit, ...rest } = layout.nodes;
        onChangeLayout({ ...layout, nodes: rest });
      }
      if (selectedStepId === id) setSelectedStepId(null);
    },
    [steps, layout, onChangeSteps, onChangeLayout, selectedStepId],
  );

  const handleMoveStep = useCallback(
    (id: string, dir: -1 | 1) => {
      const idx = steps.findIndex((s) => s.id === id);
      const target = idx + dir;
      if (idx < 0 || target < 0 || target >= steps.length) return;
      const next = [...steps];
      [next[idx], next[target]] = [next[target], next[idx]];
      onChangeSteps(next);
    },
    [steps, onChangeSteps],
  );

  return (
    <div
      data-testid="pipeline-canvas-shell"
      className="flex flex-row min-h-[500px] h-[600px] rounded-md border border-surface-border overflow-hidden bg-surface"
    >
      <NodesLibrary onAdd={handleAddStep} disabled={readOnly} />
      <Canvas
        steps={steps}
        layout={layout}
        selectedStepId={selectedStepId}
        selectedEdgeKey={selectedEdgeKey}
        onLayoutChange={onChangeLayout}
        onSelectStep={(id) => {
          setSelectedStepId(id);
          if (id) setSelectedEdge(null);
        }}
        onSelectEdge={(e) => {
          setSelectedEdge(e);
          if (e) setSelectedStepId(null);
        }}
      />
      <div className="w-[320px] shrink-0 border-l border-surface-border bg-surface-raised/30 overflow-hidden flex flex-col">
        <ConfigPanel
          steps={steps}
          selectedStepId={selectedStepId}
          selectedEdge={selectedEdge}
          staleStepIds={staleStepIds}
          tools={tools}
          readOnly={readOnly}
          onUpdateStep={handleUpdateStep}
          onDeleteStep={handleDeleteStep}
          onMoveStep={handleMoveStep}
          onJumpToJson={onJumpToJson}
        />
      </div>
    </div>
  );
}
