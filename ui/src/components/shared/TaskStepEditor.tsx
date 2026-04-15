/**
 * TaskStepEditor — inline pipeline builder for the task editor.
 *
 * Renders an ordered list of step cards (exec/tool/agent) with conditions,
 * reorder controls, and an "Add Step" button. Used inside TaskCreateModal
 * and TaskEditor when the user toggles from single-prompt to steps mode.
 */
import { useState, useCallback } from "react";
import { ChevronUp, ChevronDown, Trash2, Terminal, Wrench, Bot, Plus, AlertCircle } from "lucide-react";
import type { StepDef, StepType, StepState } from "@/src/api/hooks/useTasks";
import { FormRow, SelectInput } from "./FormControls";
import { LlmModelDropdown } from "./LlmModelDropdown";

// ---------------------------------------------------------------------------
// Step type metadata
// ---------------------------------------------------------------------------

const STEP_TYPES: { value: StepType; label: string; icon: typeof Terminal; color: string }[] = [
  { value: "exec", label: "Shell", icon: Terminal, color: "text-amber-400" },
  { value: "tool", label: "Tool", icon: Wrench, color: "text-blue-400" },
  { value: "agent", label: "LLM", icon: Bot, color: "text-purple-400" },
];

function stepMeta(type: StepType) {
  return STEP_TYPES.find((s) => s.value === type) ?? STEP_TYPES[0];
}

let _stepCounter = 0;
function nextStepId(): string {
  return `step_${++_stepCounter}`;
}

function emptyStep(type: StepType): StepDef {
  return {
    id: nextStepId(),
    type,
    label: "",
    prompt: "",
    on_failure: "abort",
  };
}

// ---------------------------------------------------------------------------
// Condition editor (simple)
// ---------------------------------------------------------------------------

type ConditionMode = "always" | "output_contains" | "output_not_contains" | "status_is";

function parseConditionMode(when: StepDef["when"]): { mode: ConditionMode; value: string } {
  if (!when) return { mode: "always", value: "" };
  if (when.output_contains) return { mode: "output_contains", value: when.output_contains };
  if (when.output_not_contains) return { mode: "output_not_contains", value: when.output_not_contains };
  if (when.status) return { mode: "status_is", value: when.status };
  return { mode: "always", value: "" };
}

function buildCondition(mode: ConditionMode, value: string, prevStepId: string): StepDef["when"] {
  if (mode === "always") return null;
  const base: Record<string, any> = { step: prevStepId };
  if (mode === "output_contains") base.output_contains = value;
  else if (mode === "output_not_contains") base.output_not_contains = value;
  else if (mode === "status_is") base.status = value;
  return base;
}

function StepConditionEditor({ step, stepIndex, steps, onChange }: {
  step: StepDef;
  stepIndex: number;
  steps: StepDef[];
  onChange: (when: StepDef["when"]) => void;
}) {
  const { mode, value } = parseConditionMode(step.when);
  const prevStep = stepIndex > 0 ? steps[stepIndex - 1] : null;
  const prevStepId = prevStep?.id ?? "step_0";

  if (stepIndex === 0) return null; // First step can't have conditions

  return (
    <div className="flex flex-row items-center gap-2 text-xs">
      <span className="text-text-dim shrink-0">Run</span>
      <select
        value={mode}
        onChange={(e) => {
          const m = e.target.value as ConditionMode;
          onChange(buildCondition(m, m === "status_is" ? "done" : "", prevStepId));
        }}
        className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs outline-none focus:border-accent"
      >
        <option value="always">Always</option>
        <option value="output_contains">If prev output contains</option>
        <option value="output_not_contains">If prev output does NOT contain</option>
        <option value="status_is">If prev step status is</option>
      </select>
      {(mode === "output_contains" || mode === "output_not_contains") && (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(buildCondition(mode, e.target.value, prevStepId))}
          placeholder="text to match..."
          className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs outline-none flex-1 focus:border-accent"
        />
      )}
      {mode === "status_is" && (
        <select
          value={value}
          onChange={(e) => onChange(buildCondition(mode, e.target.value, prevStepId))}
          className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs outline-none focus:border-accent"
        >
          <option value="done">Done</option>
          <option value="failed">Failed</option>
          <option value="skipped">Skipped</option>
        </select>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step result display (read-only, for completed pipelines)
// ---------------------------------------------------------------------------

function StepResultBadge({ state }: { state: StepState }) {
  const colors: Record<string, string> = {
    done: "bg-success/10 text-success border-success/20",
    failed: "bg-danger/10 text-danger border-danger/20",
    skipped: "bg-surface-overlay text-text-dim border-surface-border",
    running: "bg-accent/10 text-accent border-accent/20",
    pending: "bg-surface-overlay text-text-dim border-surface-border",
  };
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${colors[state.status] ?? colors.pending}`}>
      {state.status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Individual step card
// ---------------------------------------------------------------------------

function StepCard({ step, stepIndex, steps, stepState, readOnly, onChange, onDelete, onMove }: {
  step: StepDef;
  stepIndex: number;
  steps: StepDef[];
  stepState?: StepState;
  readOnly?: boolean;
  onChange: (updated: StepDef) => void;
  onDelete: () => void;
  onMove: (dir: -1 | 1) => void;
}) {
  const [conditionOpen, setConditionOpen] = useState(!!step.when);
  const meta = stepMeta(step.type);
  const Icon = meta.icon;
  const isFirst = stepIndex === 0;
  const isLast = stepIndex === steps.length - 1;

  const update = (patch: Partial<StepDef>) => onChange({ ...step, ...patch });

  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised overflow-hidden">
      {/* Header row */}
      <div className="flex flex-row items-center gap-2 px-3 py-2 bg-surface-overlay/50">
        {!readOnly && (
          <div className="flex flex-col gap-0.5 shrink-0">
            <button
              onClick={() => onMove(-1)}
              disabled={isFirst}
              className="p-0 bg-transparent border-none cursor-pointer text-text-dim disabled:opacity-20 hover:text-text"
            >
              <ChevronUp size={12} />
            </button>
            <button
              onClick={() => onMove(1)}
              disabled={isLast}
              className="p-0 bg-transparent border-none cursor-pointer text-text-dim disabled:opacity-20 hover:text-text"
            >
              <ChevronDown size={12} />
            </button>
          </div>
        )}
        <span className="text-text-dim text-[11px] font-mono shrink-0">{stepIndex + 1}.</span>
        <Icon size={14} className={meta.color} />
        {readOnly ? (
          <span className="text-xs font-semibold text-text">{meta.label}</span>
        ) : (
          <select
            value={step.type}
            onChange={(e) => update({ type: e.target.value as StepType })}
            className="bg-transparent border-none text-xs font-semibold text-text outline-none cursor-pointer"
          >
            {STEP_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        )}
        {!readOnly && (
          <input
            type="text"
            value={step.label ?? ""}
            onChange={(e) => update({ label: e.target.value })}
            placeholder="Step label (optional)"
            className="flex-1 bg-transparent border-none text-xs text-text-muted outline-none placeholder:text-text-dim"
          />
        )}
        {readOnly && step.label && (
          <span className="text-xs text-text-muted flex-1">{step.label}</span>
        )}
        {stepState && <StepResultBadge state={stepState} />}
        {!readOnly && (
          <div className="flex items-center gap-1 ml-auto">
            <select
              value={step.on_failure ?? "abort"}
              onChange={(e) => update({ on_failure: e.target.value as "abort" | "continue" })}
              className="bg-transparent border-none text-[10px] text-text-dim outline-none cursor-pointer"
              title="On failure"
            >
              <option value="abort">Stop on fail</option>
              <option value="continue">Continue on fail</option>
            </select>
            <button
              onClick={onDelete}
              className="p-1 bg-transparent border-none cursor-pointer text-text-dim hover:text-danger transition-colors"
            >
              <Trash2 size={13} />
            </button>
          </div>
        )}
      </div>

      {/* Body — type-specific fields */}
      <div className="px-3 py-2.5 flex flex-col gap-2">
        {step.type === "exec" && (
          <>
            <textarea
              value={step.prompt ?? ""}
              onChange={(e) => update({ prompt: e.target.value })}
              readOnly={readOnly}
              placeholder="Shell command..."
              rows={2}
              className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none resize-y focus:border-accent w-full"
            />
            {!readOnly && (
              <input
                type="text"
                value={step.working_directory ?? ""}
                onChange={(e) => update({ working_directory: e.target.value || null })}
                placeholder="Working directory (optional)"
                className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs outline-none w-full focus:border-accent"
              />
            )}
          </>
        )}

        {step.type === "tool" && (
          <>
            <input
              type="text"
              value={step.tool_name ?? ""}
              onChange={(e) => update({ tool_name: e.target.value || null })}
              readOnly={readOnly}
              placeholder="Tool name (e.g., exec, web_search)"
              className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs outline-none w-full focus:border-accent"
            />
            <textarea
              value={step.tool_args ? JSON.stringify(step.tool_args, null, 2) : ""}
              onChange={(e) => {
                try {
                  update({ tool_args: e.target.value ? JSON.parse(e.target.value) : null });
                } catch {
                  // Allow invalid JSON while typing
                }
              }}
              readOnly={readOnly}
              placeholder='{"key": "value"}'
              rows={2}
              className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none resize-y focus:border-accent w-full"
            />
          </>
        )}

        {step.type === "agent" && (
          <>
            <textarea
              value={step.prompt ?? ""}
              onChange={(e) => update({ prompt: e.target.value })}
              readOnly={readOnly}
              placeholder="LLM prompt — prior step results are auto-injected..."
              rows={3}
              className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs outline-none resize-y focus:border-accent w-full"
            />
            {!readOnly && (
              <div className="flex flex-row gap-2">
                <div className="flex-1">
                  <LlmModelDropdown
                    value={step.model ?? ""}
                    onChange={(v) => update({ model: v || null })}
                    placeholder="Inherit model"
                    allowClear
                  />
                </div>
              </div>
            )}
          </>
        )}

        {/* Condition row */}
        {!readOnly && stepIndex > 0 && (
          <div>
            {!conditionOpen ? (
              <button
                onClick={() => setConditionOpen(true)}
                className="text-[10px] text-text-dim bg-transparent border-none cursor-pointer hover:text-accent transition-colors"
              >
                + Add condition
              </button>
            ) : (
              <StepConditionEditor
                step={step}
                stepIndex={stepIndex}
                steps={steps}
                onChange={(when) => update({ when })}
              />
            )}
          </div>
        )}

        {/* Result display for completed steps */}
        {stepState && (stepState.result || stepState.error) && (
          <details className="text-xs">
            <summary className="cursor-pointer text-text-dim hover:text-text">
              {stepState.error ? "Error" : "Result"}
            </summary>
            <pre className="mt-1 p-2 rounded bg-surface text-text-muted text-[11px] font-mono whitespace-pre-wrap max-h-40 overflow-y-auto border border-surface-border">
              {stepState.error ?? stepState.result}
            </pre>
          </details>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add step button with type picker
// ---------------------------------------------------------------------------

function AddStepButton({ onAdd }: { onAdd: (type: StepType) => void }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-text-muted bg-transparent border border-dashed border-surface-border rounded-lg cursor-pointer hover:border-accent/50 hover:text-accent transition-colors"
      >
        <Plus size={13} />
        Add Step
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-surface border border-surface-border rounded-lg shadow-xl z-10 min-w-[140px]">
          {STEP_TYPES.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.value}
                onClick={() => { onAdd(t.value); setOpen(false); }}
                className="flex items-center gap-2 w-full px-3 py-2 text-xs bg-transparent border-none cursor-pointer text-text hover:bg-surface-raised transition-colors text-left"
              >
                <Icon size={13} className={t.color} />
                {t.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main editor
// ---------------------------------------------------------------------------

export interface TaskStepEditorProps {
  steps: StepDef[];
  onChange: (steps: StepDef[]) => void;
  stepStates?: StepState[] | null;
  readOnly?: boolean;
}

export function TaskStepEditor({ steps, onChange, stepStates, readOnly }: TaskStepEditorProps) {
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
    <div className="flex flex-col gap-2">
      {steps.length === 0 && !readOnly && (
        <div className="flex flex-col items-center gap-2 py-6 text-text-dim">
          <AlertCircle size={20} className="opacity-40" />
          <span className="text-xs">No steps yet. Add your first step below.</span>
        </div>
      )}
      {steps.map((step, i) => (
        <StepCard
          key={step.id}
          step={step}
          stepIndex={i}
          steps={steps}
          stepState={stepStates?.[i]}
          readOnly={readOnly}
          onChange={(updated) => updateStep(i, updated)}
          onDelete={() => deleteStep(i)}
          onMove={(dir) => moveStep(i, dir)}
        />
      ))}
      {!readOnly && <AddStepButton onAdd={addStep} />}
      {!readOnly && steps.length > 0 && (
        <p className="text-[10px] text-text-dim mt-1">
          Prior step results are auto-injected. Use <code className="text-accent/80">{"{{steps.<id>.result}}"}</code> for explicit references.
        </p>
      )}
    </div>
  );
}
