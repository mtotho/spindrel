/**
 * EditorCard — task editor as a floating card on the automations canvas.
 *
 * Replaces the modal/wizard surface for the canvas-mode UX. Tabs across
 * Content / Execution / Trigger; reuses the same field components as the
 * modal, so behavior parity is automatic.
 *
 * Save / Delete share the existing useTaskFormState mutations.
 */
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { X, Trash2 } from "lucide-react";
import { useTaskFormState } from "@/src/components/shared/task/useTaskFormState";
import {
  ContentFields,
  ExecutionFields,
  TriggerFields,
} from "@/src/components/shared/task/TaskFormFields";
import { WizardStepIndicator } from "@/src/components/shared/task/WizardStepIndicator";

type EditorTab = 0 | 1 | 2;

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

type EditorCardProps = CreateProps | EditProps;

export function EditorCard(props: EditorCardProps) {
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

  // Pre-seed stepsMode for create flow when the user picked "pipeline" on the
  // mode-picker card. (For "prompt" we leave steps null.)
  const initialMode = props.mode === "create" ? props.initialMode : null;
  useEffect(() => {
    if (!isCreate) return;
    if (initialMode !== "pipeline") return;
    if (form.steps !== null) return;
    if (!form.botId) return; // wait for defaults effect to run first
    form.setSteps([]);
  }, [isCreate, initialMode, form.botId, form.steps, form]);

  const [tab, setTab] = useState<EditorTab>(0);
  const [visited, setVisited] = useState<Set<number>>(() => new Set([0]));

  const goTo = (next: EditorTab) => {
    setTab(next);
    setVisited((prev) => new Set([...prev, next]));
  };

  const validSteps = (() => {
    const s = new Set<number>();
    if (form.hasPromptOrWorkflow) s.add(0);
    if (form.botId) s.add(1);
    s.add(2);
    return s;
  })();

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

  const title = isCreate
    ? "New Task"
    : form.title?.trim() || form.existingTask?.title || "Task";

  return (
    <div className="flex flex-col rounded-xl border border-surface-border bg-surface shadow-2xl w-[min(95vw,720px)] max-h-[85vh] overflow-hidden">
      {/* Header */}
      <div className="flex flex-row items-center px-5 py-3 border-b border-surface-border shrink-0 gap-2.5">
        <button
          onClick={props.onClose}
          aria-label="Close"
          className="flex items-center justify-center bg-transparent border-none cursor-pointer p-1 shrink-0 rounded-md hover:bg-surface-overlay transition-colors"
        >
          <X size={18} className="text-text-muted" />
        </button>
        <span className="text-text text-[15px] font-bold flex-1 tracking-tight truncate">
          {title}
        </span>
        {!isCreate && (
          <button
            onClick={handleDelete}
            aria-label="Delete task"
            className="flex items-center justify-center bg-transparent border-none cursor-pointer p-1 shrink-0 rounded-md text-text-dim hover:text-danger hover:bg-danger/[0.08] transition-colors"
          >
            <Trash2 size={16} />
          </button>
        )}
        <button
          onClick={form.handleSave}
          disabled={form.saving || !form.canSave}
          className={`px-5 py-1.5 text-[13px] font-semibold border-none rounded-lg shrink-0 transition-all duration-150 ${
            form.canSave
              ? "bg-transparent text-accent cursor-pointer hover:bg-accent/[0.08]"
              : "bg-surface-border text-text-dim cursor-not-allowed"
          } ${form.saving ? "opacity-70" : ""}`}
        >
          {form.saving ? "Saving..." : isCreate ? "Create" : "Save"}
        </button>
      </div>

      {/* Tabs */}
      <WizardStepIndicator
        currentStep={tab}
        visitedSteps={visited}
        validSteps={validSteps}
        onStepClick={(s) => goTo(s as EditorTab)}
      />

      {form.error && (
        <div className="px-5 py-2 bg-danger/[0.08] text-danger text-xs shrink-0">
          {form.error?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      {!isCreate && form.loadingTask ? (
        <div className="flex flex-1 items-center justify-center p-10">
          <div className="chat-spinner" />
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-5">
          {tab === 0 && <ContentFields form={form} promptRows={6} />}
          {tab === 1 && <ExecutionFields form={form} />}
          {tab === 2 && <TriggerFields form={form} />}
        </div>
      )}
    </div>
  );
}
