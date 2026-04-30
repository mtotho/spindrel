/**
 * TaskStepEditor — vertical timeline pipeline builder for the task editor.
 *
 * Renders an ordered list of step cards connected by a vertical timeline line,
 * with numbered circle nodes, colored type badges, and an "Add Step" button.
 *
 * Field-editor components live under `./task/step-editor/` and are reused by
 * the Pipeline Canvas tab's Config Panel.
 */
import { useCallback } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { useTaskMachineAutomationOptions, type StepDef, type StepState, type StepType } from "@/src/api/hooks/useTasks";
import { useTools } from "@/src/api/hooks/useTools";
import { emptyStep, stepMeta, visibleStepTypes } from "./task/TaskStepEditorModel";
import { StepCard } from "./task/step-editor/StepCard";
import { AddStepButton } from "./task/step-editor/AddStepButton";

export interface TaskStepEditorProps {
  steps: StepDef[];
  onChange: (steps: StepDef[]) => void;
  stepStates?: StepState[] | null;
  readOnly?: boolean;
}

export function TaskStepEditor({ steps, onChange, stepStates, readOnly }: TaskStepEditorProps) {
  const { data: allTools } = useTools();
  const { data: machineAutomation } = useTaskMachineAutomationOptions();
  const tools = allTools ?? [];
  const allowedMachineStepTypes = (machineAutomation?.step_types ?? []).map((stepType) => stepType.type);
  const stepTypes = visibleStepTypes(allowedMachineStepTypes);

  const updateStep = useCallback((index: number, updated: StepDef) => {
    const next = [...steps];
    next[index] = updated;
    onChange(next);
  }, [steps, onChange]);

  const deleteStep = useCallback((index: number) => {
    onChange(steps.filter((_, i) => i !== index));
  }, [steps, onChange]);

  const moveStep = useCallback((index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }, [steps, onChange]);

  const addStep = useCallback((type: StepType) => {
    onChange([...steps, emptyStep(type)]);
  }, [steps, onChange]);

  return (
    <div className="flex flex-col">
      {steps.length === 0 && !readOnly && (
        <div className="flex flex-col items-center gap-3 py-10 text-text-dim rounded-md bg-surface-raised/30">
          <div className="text-sm font-medium text-text-muted">Build your pipeline</div>
          <div className="text-xs text-text-dim">Add steps to create a multi-step automation</div>
          <div className="flex flex-row items-center gap-1.5 mt-2">
            {stepTypes.map((t) => {
              const TIcon = t.icon;
              return (
                <button
                  key={t.value}
                  onClick={() => addStep(t.value)}
                  className="flex flex-row items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-surface-raised/60 rounded-md cursor-pointer text-text hover:bg-surface-overlay/60 hover:text-accent transition-colors"
                >
                  <TIcon size={14} className={t.color} />
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Timeline container */}
      {steps.length > 0 && (
        <div className="relative pl-3 sm:pl-5">
          {/* Vertical timeline line */}
          {steps.length > 1 && (
            <div
              className="absolute left-[7px] sm:left-[11px] top-[18px] sm:top-[22px] bottom-[18px] sm:bottom-[22px] w-[2px] bg-surface-border rounded-full"
            />
          )}

          <div className="flex flex-col gap-3">
            {steps.map((step, i) => {
              const meta = stepMeta(step.type);
              const stepState = stepStates?.[i];
              const nodeColor = stepState?.status === "done"
                ? "bg-success/10 text-success"
                : stepState?.status === "failed"
                  ? "bg-danger/10 text-danger"
                  : stepState?.status === "running"
                    ? "bg-accent/10 text-accent"
                    : meta.node;

              return (
                <div key={step.id} className="relative">
                  {/* Timeline node */}
                  <div className={`absolute -left-3 sm:-left-5 top-[11px] flex items-center justify-center w-[18px] h-[18px] sm:w-[22px] sm:h-[22px] rounded-full text-[9px] sm:text-[10px] font-bold z-10 ${nodeColor}`}>
                    {stepState?.status === "done" ? (
                      <CheckCircle2 size={12} />
                    ) : stepState?.status === "failed" ? (
                      <XCircle size={12} />
                    ) : (
                      i + 1
                    )}
                  </div>

                  {/* Step card */}
                  <StepCard
                    step={step}
                    stepIndex={i}
                    steps={steps}
                    stepState={stepState}
                    readOnly={readOnly}
                    tools={tools}
                    onChange={(updated) => updateStep(i, updated)}
                    onDelete={() => deleteStep(i)}
                    onMove={(dir) => moveStep(i, dir)}
                    machineStepTypes={allowedMachineStepTypes}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Add step button */}
      {!readOnly && steps.length > 0 && (
        <div className="mt-3 pl-3 sm:pl-5">
          <AddStepButton onAdd={addStep} machineStepTypes={allowedMachineStepTypes} />
        </div>
      )}

      {/* Hint */}
      {!readOnly && steps.length > 1 && (
        <p className="text-[10px] text-text-dim mt-3 pl-3 sm:pl-5 leading-relaxed">
          Reference prior results: <code className="text-accent/80 bg-accent/5 px-1 py-0.5 rounded text-[10px]">{"{{steps.1.result}}"}</code> in prompts,{" "}
          <code className="text-accent/80 bg-accent/5 px-1 py-0.5 rounded text-[10px]">$STEP_1_RESULT</code> in shell.{" "}
          JSON fields: <code className="text-accent/80 bg-accent/5 px-1 py-0.5 rounded text-[10px]">{"{{steps.1.result.key}}"}</code> or{" "}
          <code className="text-accent/80 bg-accent/5 px-1 py-0.5 rounded text-[10px]">$STEP_1_key</code>.
        </p>
      )}
    </div>
  );
}
