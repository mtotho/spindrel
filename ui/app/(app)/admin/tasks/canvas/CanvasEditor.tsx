/**
 * CanvasEditor — xyflow-powered task editor.
 *
 * One TaskNode for task-level config, one StepNode per pipeline step
 * (pipeline mode only). Pan/zoom, snap-to-grid, multi-select, marquee,
 * minimap, and undo/redo are provided by React Flow v12. Save/Delete
 * remain top-right actions; positions persist via `Task.layout.nodes`.
 */
import "@xyflow/react/dist/style.css";
import "./CanvasTheme.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeChange,
  type Viewport,
  useReactFlow,
} from "@xyflow/react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2, X, Map as MapIcon } from "lucide-react";
import { useTools } from "@/src/api/hooks/useTools";
import { useTaskFormState } from "@/src/components/shared/task/useTaskFormState";
import { emptyStep } from "@/src/components/shared/task/TaskStepEditorModel";
import type { StepDef, TaskLayout } from "@/src/api/hooks/useTasks";
import { TaskNode } from "./TaskNode";
import { StepNode } from "./StepNode";
import {
  AnchorEdge,
  ConditionalEdge,
  SecondaryEdge,
  SequentialEdge,
} from "./CanvasEdges";
import { buildEdges, TASK_NODE_ID_CONST } from "./edges";
import { useDirtyGate } from "./useDirtyGate";

const TASK_NODE_X = 32;
const TASK_NODE_Y = 32;
const STEP_COL_X = 520;
const STEP_ROW_Y0 = 32;
const STEP_ROW_DY = 220;

const NODE_TYPES = { task: TaskNode, step: StepNode };
const EDGE_TYPES = {
  anchor: AnchorEdge,
  sequential: SequentialEdge,
  conditional: ConditionalEdge,
  secondary: SecondaryEdge,
};

interface CommonProps {
  onClose: () => void;
  onSaved: (createdTaskId?: string) => void;
}
interface CreateProps extends CommonProps {
  mode: "create";
  initialMode: "prompt" | "pipeline";
}
interface EditProps extends CommonProps {
  mode: "edit";
  taskId: string;
  onDeleted: () => void;
}
type CanvasEditorProps = CreateProps | EditProps;

export function CanvasEditor(props: CanvasEditorProps) {
  return (
    <ReactFlowProvider>
      <CanvasEditorInner {...props} />
    </ReactFlowProvider>
  );
}

function CanvasEditorInner(props: CanvasEditorProps) {
  const qc = useQueryClient();
  const isCreate = props.mode === "create";
  const taskId = props.mode === "edit" ? props.taskId : undefined;
  const { data: allTools } = useTools();
  const tools = allTools ?? [];

  const form = useTaskFormState({
    mode: props.mode,
    taskId,
    onSaved: (createdId) => {
      qc.invalidateQueries({ queryKey: ["admin-tasks-canvas-definitions"] });
      props.onSaved(createdId);
    },
  });

  const dirty = useDirtyGate(form, isCreate);

  // Pre-seed steps for pipeline create-mode
  const initialMode = props.mode === "create" ? props.initialMode : null;
  useEffect(() => {
    if (!isCreate) return;
    if (initialMode !== "pipeline") return;
    if (form.steps !== null) return;
    if (!form.botId) return;
    form.setSteps([]);
  }, [isCreate, initialMode, form.botId, form.steps, form]);

  const layout: TaskLayout = form.layout || {};
  const layoutNodes = layout.nodes || {};
  const setLayout = form.setLayout;

  const setNodePos = useCallback((id: string, pos: { x: number; y: number }) => {
    setLayout((prev: TaskLayout) => ({
      ...prev,
      nodes: { ...(prev?.nodes || {}), [id]: pos },
    }));
  }, [setLayout]);

  // Auto-place tiles that lack a saved position
  const placedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const additions: Record<string, { x: number; y: number }> = {};
    if (!layoutNodes[TASK_NODE_ID_CONST] && !placedRef.current.has(TASK_NODE_ID_CONST)) {
      additions[TASK_NODE_ID_CONST] = { x: TASK_NODE_X, y: TASK_NODE_Y };
      placedRef.current.add(TASK_NODE_ID_CONST);
    }
    if (form.steps) {
      form.steps.forEach((s, i) => {
        if (!layoutNodes[s.id] && !placedRef.current.has(s.id)) {
          additions[s.id] = { x: STEP_COL_X, y: STEP_ROW_Y0 + i * STEP_ROW_DY };
          placedRef.current.add(s.id);
        }
      });
    }
    if (Object.keys(additions).length > 0) {
      setLayout((prev: TaskLayout) => ({
        ...prev,
        nodes: { ...(prev?.nodes || {}), ...additions },
      }));
    }
  }, [form.steps, layoutNodes, setLayout]);

  // Per-step expansion state
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const toggleExpand = useCallback((id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  // Step manipulation
  const addStep = useCallback(() => {
    const existing = form.steps || [];
    const ids = new Set(existing.map((s) => s.id));
    let n = existing.length + 1;
    let id = `step_${n}`;
    while (ids.has(id)) { n += 1; id = `step_${n}`; }
    const fresh: StepDef = { ...emptyStep("tool"), id };
    form.setSteps([...existing, fresh]);
  }, [form]);

  const deleteStep = useCallback((id: string) => {
    if (!form.steps) return;
    form.setSteps(form.steps.filter((s) => s.id !== id));
    setLayout((prev: TaskLayout) => {
      const next = { ...(prev?.nodes || {}) };
      delete next[id];
      return { ...prev, nodes: next };
    });
  }, [form, setLayout]);

  const updateStep = useCallback((index: number, updated: StepDef) => {
    if (!form.steps) return;
    const oldId = form.steps[index]?.id;
    const next = [...form.steps];
    next[index] = updated;
    form.setSteps(next);
    if (oldId && updated.id && oldId !== updated.id) {
      setLayout((prev: TaskLayout) => {
        const ns = { ...(prev?.nodes || {}) };
        if (ns[oldId]) {
          ns[updated.id] = ns[oldId];
          delete ns[oldId];
        }
        return { ...prev, nodes: ns };
      });
    }
  }, [form, setLayout]);

  const moveStep = useCallback((index: number, dir: -1 | 1) => {
    if (!form.steps) return;
    const target = index + dir;
    if (target < 0 || target >= form.steps.length) return;
    const next = [...form.steps];
    [next[index], next[target]] = [next[target], next[index]];
    form.setSteps(next);
  }, [form]);

  // Build the xyflow nodes from form state. We sync these to local
  // useNodesState so xyflow can manage drag + selection.
  const computedNodes = useMemo<Node[]>(() => {
    const list: Node[] = [];
    const taskPos = layoutNodes[TASK_NODE_ID_CONST] || { x: TASK_NODE_X, y: TASK_NODE_Y };
    list.push({
      id: TASK_NODE_ID_CONST,
      type: "task",
      position: taskPos,
      data: { form, isCreate },
      selectable: true,
      deletable: false,
    });
    if (form.steps) {
      form.steps.forEach((step, idx) => {
        const pos = layoutNodes[step.id] || { x: STEP_COL_X, y: STEP_ROW_Y0 + idx * STEP_ROW_DY };
        list.push({
          id: step.id,
          type: "step",
          position: pos,
          data: {
            step,
            stepIndex: idx,
            steps: form.steps!,
            stepState: form.existingTask?.parent_task_id ? form.existingTask?.step_states?.[idx] : undefined,
            tools,
            expanded: !!expanded[step.id],
            onChange: (u: StepDef) => updateStep(idx, u),
            onDelete: () => deleteStep(step.id),
            onMove: (dir: -1 | 1) => moveStep(idx, dir),
            onToggleExpand: () => toggleExpand(step.id),
          },
        });
      });
    }
    return list;
  }, [form, isCreate, layoutNodes, expanded, tools, updateStep, deleteStep, moveStep, toggleExpand]);

  // Transient drag overrides — keyed by node id. While a drag is in flight we
  // apply the live cursor position locally; on drop we commit to layout and
  // clear the override.
  const [dragOverrides, setDragOverrides] = useState<Record<string, { x: number; y: number }>>({});

  const rfNodes = useMemo<Node[]>(() => {
    if (Object.keys(dragOverrides).length === 0) return computedNodes;
    return computedNodes.map((n) =>
      dragOverrides[n.id] ? { ...n, position: dragOverrides[n.id] } : n,
    );
  }, [computedNodes, dragOverrides]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    let pendingOverrides: Record<string, { x: number; y: number } | null> | null = null;
    for (const c of changes) {
      if (c.type === "position" && c.position) {
        if (!pendingOverrides) pendingOverrides = {};
        if (c.dragging) {
          pendingOverrides[c.id] = { x: c.position.x, y: c.position.y };
        } else {
          // Drop: commit to layout, then clear the override.
          setNodePos(c.id, { x: c.position.x, y: c.position.y });
          pendingOverrides[c.id] = null;
        }
      }
    }
    if (pendingOverrides) {
      const apply = pendingOverrides;
      setDragOverrides((prev) => {
        const next = { ...prev };
        for (const [id, val] of Object.entries(apply)) {
          if (val === null) delete next[id];
          else next[id] = val;
        }
        return next;
      });
    }
  }, [setNodePos]);

  // Edges — derived directly, no local mirror.
  const rfEdges = useMemo<Edge[]>(() => {
    if (!form.steps) return [];
    return buildEdges(form.steps);
  }, [form.steps]);

  // Camera persistence
  const onMoveEnd = useCallback((_: unknown, vp: Viewport) => {
    setLayout((prev: TaskLayout) => ({ ...prev, camera: { x: vp.x, y: vp.y, scale: vp.zoom } }));
  }, [setLayout]);

  const initialViewport = useMemo<Viewport>(() => {
    const cam = layout.camera;
    if (cam) return { x: cam.x, y: cam.y, zoom: cam.scale };
    return { x: 0, y: 0, zoom: 0.95 };
  }, [layout.camera]);

  // Save flow updates dirty baseline
  const handleSave = useCallback(async () => {
    await form.handleSave();
    dirty.markClean();
  }, [form, dirty]);

  // Delete confirm
  const handleDelete = useCallback(async () => {
    if (props.mode !== "edit") return;
    const ok = typeof window !== "undefined" && window.confirm("Delete this task?");
    if (!ok) return;
    try {
      await form.handleDelete();
      qc.invalidateQueries({ queryKey: ["admin-tasks-canvas-definitions"] });
      props.onDeleted();
    } catch {
      /* surfaced via form.error */
    }
  }, [form, qc, props]);

  // Esc → guard then close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (!dirty.guard()) {
        e.preventDefault();
        return;
      }
      props.onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty, props]);

  const guardedClose = useCallback(() => {
    if (dirty.guard()) props.onClose();
  }, [dirty, props]);

  // Double-click empty canvas → add a step at click point (pipeline mode only)
  const flowApi = useReactFlow();
  const onPaneClick = useCallback((e: React.MouseEvent) => {
    if (!form.stepsMode) return;
    if (!e.detail || e.detail < 2) return;
    const point = flowApi.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const existing = form.steps || [];
    const ids = new Set(existing.map((s) => s.id));
    let n = existing.length + 1;
    let id = `step_${n}`;
    while (ids.has(id)) { n += 1; id = `step_${n}`; }
    const fresh: StepDef = { ...emptyStep("tool"), id };
    form.setSteps([...existing, fresh]);
    setLayout((prev: TaskLayout) => ({
      ...prev,
      nodes: { ...(prev?.nodes || {}), [id]: { x: point.x, y: point.y } },
    }));
    placedRef.current.add(id);
  }, [form, flowApi, setLayout]);

  const [minimapVisible, setMinimapVisible] = useState(true);

  if (!isCreate && form.loadingTask) {
    return (
      <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
        <div className="chat-spinner" />
      </div>
    );
  }

  return (
    <div className="spindrel-canvas absolute inset-0 z-[1] bg-surface">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        defaultViewport={initialViewport}
        minZoom={0.4}
        maxZoom={1.5}
        snapToGrid
        snapGrid={[16, 16]}
        onNodesChange={onNodesChange}
        onMoveEnd={onMoveEnd}
        onPaneClick={onPaneClick}
        nodesConnectable={false}
        deleteKeyCode={null}
        selectionOnDrag
        panOnDrag={[1, 2]}
        panOnScroll
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1.4} />
        <Controls position="bottom-left" showInteractive={false} />
        {minimapVisible && (
          <MiniMap
            position="bottom-right"
            pannable
            zoomable
            nodeStrokeWidth={1}
            nodeColor={(n) => (n.type === "task" ? "rgb(var(--color-accent))" : "rgb(var(--color-text-dim))")}
          />
        )}
      </ReactFlow>

      {/* Floating action bar — top-right */}
      <div className="absolute top-3 right-3 z-30 flex flex-row items-center gap-2 pointer-events-auto">
        {dirty.isDirty && !form.saving && (
          <span className="px-2 py-1 rounded-md bg-warning-muted/15 text-warning-muted text-[10.5px] font-semibold uppercase tracking-wider">
            Unsaved
          </span>
        )}
        {form.error && (
          <div className="px-3 py-1.5 rounded-md bg-danger/15 text-danger text-xs max-w-[280px] truncate">
            {form.error.message || "Error"}
          </div>
        )}
        <button
          onClick={() => setMinimapVisible((v) => !v)}
          title={minimapVisible ? "Hide minimap" : "Show minimap"}
          className="flex items-center justify-center w-7 h-7 rounded-md bg-surface-raised border border-surface-border text-text-dim hover:text-text hover:bg-surface-overlay cursor-pointer transition-colors"
        >
          <MapIcon size={13} />
        </button>
        <button
          onClick={guardedClose}
          title="Close editor (Esc)"
          className="flex flex-row items-center gap-1.5 px-3 py-[6px] text-xs font-semibold border border-surface-border bg-surface-raised text-text hover:bg-surface-overlay cursor-pointer rounded-md transition-colors"
        >
          <X size={14} />
          Close
        </button>
        {!isCreate && (
          <button
            onClick={handleDelete}
            title="Delete task"
            className="flex items-center justify-center w-7 h-7 rounded-md bg-surface-raised border border-surface-border text-text-dim hover:text-danger hover:bg-danger/10 cursor-pointer transition-colors"
          >
            <Trash2 size={14} />
          </button>
        )}
        <button
          onClick={handleSave}
          disabled={form.saving || !form.canSave}
          className={`flex flex-row items-center gap-1.5 px-3 py-[6px] text-xs font-semibold border-none rounded-md transition-colors ${
            form.canSave && !form.saving
              ? "bg-accent text-white hover:bg-accent/90 cursor-pointer"
              : "bg-surface-border text-text-dim cursor-not-allowed"
          }`}
        >
          <Save size={14} />
          {form.saving ? "Saving..." : isCreate ? "Create" : "Save"}
        </button>
      </div>

      {/* Add-step floating button (pipeline mode only) */}
      {form.stepsMode && (
        <button
          onClick={addStep}
          title="Add step (or double-click empty canvas)"
          className="absolute bottom-4 right-4 z-30 flex flex-row items-center gap-1.5 px-4 py-2 rounded-full bg-accent text-white text-xs font-semibold border-none cursor-pointer shadow-lg hover:bg-accent/90 transition-colors"
        >
          <Plus size={14} />
          Add Step
        </button>
      )}
    </div>
  );
}
