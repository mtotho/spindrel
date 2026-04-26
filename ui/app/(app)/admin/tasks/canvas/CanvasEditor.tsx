/**
 * CanvasEditor — tile-based task editor on the canvas plane.
 *
 * Replaces the floating modal-shaped EditorCard. Each piece is a draggable
 * tile: one TaskTile for task-level config, one StepTile per pipeline step
 * (pipeline mode only). Save / delete / add-step controls float at the edges.
 */
import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2, X } from "lucide-react";
import { useTaskFormState } from "@/src/components/shared/task/useTaskFormState";
import type { StepDef, TaskLayout } from "@/src/api/hooks/useTasks";
import { TaskTile } from "./TaskTile";
import { StepTile } from "./StepTile";

const TASK_TILE_ID = "__task__";
const TASK_TILE_X = 32;
const TASK_TILE_Y = 32;
const STEP_COL_X = 480;
const STEP_ROW_Y0 = 32;
const STEP_ROW_DY = 220;

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
  const qc = useQueryClient();
  const isCreate = props.mode === "create";
  const taskId = props.mode === "edit" ? props.taskId : undefined;

  const form = useTaskFormState({
    mode: props.mode,
    taskId,
    onSaved: (createdId) => {
      qc.invalidateQueries({ queryKey: ["admin-tasks-canvas-definitions"] });
      props.onSaved(createdId);
    },
  });

  // Pre-seed steps for pipeline create-mode
  const initialMode = props.mode === "create" ? props.initialMode : null;
  useEffect(() => {
    if (!isCreate) return;
    if (initialMode !== "pipeline") return;
    if (form.steps !== null) return;
    if (!form.botId) return;
    form.setSteps([]);
  }, [isCreate, initialMode, form.botId, form.steps, form]);

  const layout = form.layout || {};
  const nodes = layout.nodes || {};
  const setLayout = form.setLayout;

  const setNodePos = useCallback((id: string, pos: { x: number; y: number }) => {
    setLayout((prev: TaskLayout) => ({
      ...prev,
      nodes: { ...(prev?.nodes || {}), [id]: pos },
    }));
  }, [setLayout]);

  // Auto-place tiles that don't yet have a saved position. Run once per
  // mount and again whenever the step-set changes; gated by a ref so we
  // don't fight the user's drags.
  const placedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const additions: Record<string, { x: number; y: number }> = {};
    if (!nodes[TASK_TILE_ID] && !placedRef.current.has(TASK_TILE_ID)) {
      additions[TASK_TILE_ID] = { x: TASK_TILE_X, y: TASK_TILE_Y };
      placedRef.current.add(TASK_TILE_ID);
    }
    if (form.steps) {
      form.steps.forEach((s, i) => {
        if (!nodes[s.id] && !placedRef.current.has(s.id)) {
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
  }, [form.steps, nodes, setLayout]);

  const addStep = () => {
    const existing = form.steps || [];
    const ids = new Set(existing.map((s) => s.id));
    let n = existing.length + 1;
    let id = `step_${n}`;
    while (ids.has(id)) { n += 1; id = `step_${n}`; }
    const newStep: StepDef = { id, type: "tool", on_failure: "abort" };
    form.setSteps([...existing, newStep]);
  };

  const deleteStep = (id: string) => {
    if (!form.steps) return;
    form.setSteps(form.steps.filter((s) => s.id !== id));
  };

  const updateStep = (id: string, patch: Partial<StepDef>) => {
    if (!form.steps) return;
    form.setSteps(form.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)));
    // If the step's id was renamed, carry its layout entry along.
    if (patch.id && patch.id !== id) {
      const oldPos = (form.layout?.nodes || {})[id];
      if (oldPos) {
        setLayout((prev: TaskLayout) => {
          const next = { ...(prev?.nodes || {}) };
          next[patch.id!] = oldPos;
          delete next[id];
          return { ...prev, nodes: next };
        });
      }
    }
  };

  const handleDelete = async () => {
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
  };

  if (!isCreate && form.loadingTask) {
    return (
      <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
        <div className="chat-spinner" />
      </div>
    );
  }

  return (
    <>
      {/* Floating action bar — top-right */}
      <div className="absolute top-3 right-3 z-30 flex flex-row items-center gap-2 pointer-events-auto">
        {form.error && (
          <div className="px-3 py-1.5 rounded-md bg-danger/[0.08] text-danger text-xs max-w-[280px] truncate">
            {form.error.message || "Error"}
          </div>
        )}
        <button
          onClick={props.onClose}
          title="Close editor"
          className="flex flex-row items-center gap-1.5 px-3 py-[5px] text-xs font-semibold border-none cursor-pointer rounded-md bg-surface-raised/70 text-text-dim hover:text-text hover:bg-surface-raised transition-colors backdrop-blur"
        >
          <X size={14} />
          Close
        </button>
        {!isCreate && (
          <button
            onClick={handleDelete}
            title="Delete task"
            className="flex items-center justify-center w-7 h-7 rounded-md bg-surface-raised/70 text-text-dim hover:text-danger hover:bg-danger/[0.08] border-none cursor-pointer transition-colors backdrop-blur"
          >
            <Trash2 size={14} />
          </button>
        )}
        <button
          onClick={form.handleSave}
          disabled={form.saving || !form.canSave}
          className={`flex flex-row items-center gap-1.5 px-3 py-[5px] text-xs font-semibold border-none rounded-md transition-colors ${
            form.canSave && !form.saving
              ? "bg-accent/15 text-accent hover:bg-accent/25 cursor-pointer"
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
          title="Add step"
          className="absolute bottom-4 right-4 z-30 flex flex-row items-center gap-1.5 px-4 py-2 rounded-full bg-accent text-white text-xs font-semibold border-none cursor-pointer shadow-lg hover:bg-accent/90 transition-colors"
        >
          <Plus size={14} />
          Add Step
        </button>
      )}

      {/* Task tile */}
      <TaskTile
        form={form}
        position={nodes[TASK_TILE_ID] || { x: TASK_TILE_X, y: TASK_TILE_Y }}
        onPositionChange={(pos) => setNodePos(TASK_TILE_ID, pos)}
        isCreate={isCreate}
      />

      {/* Step tiles (pipeline mode) */}
      {form.stepsMode && form.steps && form.steps.map((step, idx) => (
        <StepTile
          key={step.id}
          step={step}
          index={idx}
          form={form}
          position={nodes[step.id] || { x: STEP_COL_X, y: STEP_ROW_Y0 + idx * STEP_ROW_DY }}
          onPositionChange={(pos) => setNodePos(step.id, pos)}
          onUpdate={(patch) => updateStep(step.id, patch)}
          onDelete={() => deleteStep(step.id)}
        />
      ))}
    </>
  );
}
