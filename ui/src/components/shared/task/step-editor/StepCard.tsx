import { useState } from "react";
import { ChevronUp, ChevronDown, Trash2, CheckCircle2, XCircle, AlertCircle } from "lucide-react";
import type { StepDef, StepState } from "@/src/api/hooks/useTasks";
import type { ToolItem } from "@/src/api/hooks/useTools";
import { LlmModelDropdown } from "../../LlmModelDropdown";
import { ToolSelector as SharedToolSelector } from "../../ToolSelector";
import { isKnownStepType, stepMeta } from "../TaskStepEditorModel";
import { MiniDropdown } from "./MiniDropdown";
import { ON_FAILURE_OPTIONS, StepTypeSelector } from "./StepTypeSelector";
import { StepConditionEditor } from "./StepConditionEditor";
import { StepResultBadge } from "./StepResultBadge";
import { ToolArgsEditor } from "./ToolArgsEditor";
import { UserPromptFields } from "./UserPromptFields";
import { ForeachFields } from "./ForeachFields";
import { scaffoldArgsFromSchema } from "./toolSchemaHelpers";

export function StepCard({ step, stepIndex, steps, stepState, readOnly, tools, onChange, onDelete, onMove, compact }: {
  step: StepDef;
  stepIndex: number;
  steps: StepDef[];
  stepState?: StepState;
  readOnly?: boolean;
  tools: ToolItem[];
  onChange: (updated: StepDef) => void;
  onDelete: () => void;
  onMove: (dir: -1 | 1) => void;
  compact?: boolean;
}) {
  const [conditionOpen, setConditionOpen] = useState(!!step.when);
  const meta = stepMeta(step.type);
  const Icon = meta.icon;
  const isFirst = stepIndex === 0;
  const isLast = stepIndex === steps.length - 1;

  const update = (patch: Partial<StepDef>) => onChange({ ...step, ...patch });

  const headerPad = compact ? "px-2 py-1.5" : "px-2.5 sm:px-3.5 py-2.5";
  const bodyPad = compact ? "px-2 pb-2" : "px-2.5 sm:px-3.5 pb-3";
  const bodyGap = compact ? "gap-2" : "gap-2.5";
  const headerGap = compact ? "gap-2" : "gap-2.5";

  return (
    <div className="rounded-md bg-surface-raised/40 group transition-colors hover:bg-surface-overlay/35">
      {/* Header row */}
      <div className={`flex flex-row items-center ${headerGap} ${headerPad}`}>
        {/* Reorder controls — hidden in canvas (xyflow drag is the reorder affordance) */}
        {!readOnly && !compact && (
          <div className="flex flex-col shrink-0 -my-1 max-sm:opacity-100 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={() => onMove(-1)}
              disabled={isFirst}
              className="p-0.5 bg-transparent border-none cursor-pointer text-text-dim disabled:opacity-20 hover:text-text transition-colors"
            >
              <ChevronUp size={12} />
            </button>
            <button
              onClick={() => onMove(1)}
              disabled={isLast}
              className="p-0.5 bg-transparent border-none cursor-pointer text-text-dim disabled:opacity-20 hover:text-text transition-colors"
            >
              <ChevronDown size={12} />
            </button>
          </div>
        )}

        {/* Type badge */}
        {readOnly ? (
          <span className={`inline-flex flex-row items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded-md ${meta.bgBadge}`}>
            <Icon size={11} />
            {meta.label}
          </span>
        ) : (
          <StepTypeSelector value={step.type} onChange={(v) => update({ type: v })} />
        )}

        {/* Label */}
        {!readOnly ? (
          <input
            type="text"
            value={step.label ?? ""}
            onChange={(e) => update({ label: e.target.value })}
            placeholder="Step label (optional)"
            className="flex-1 bg-transparent border-none text-xs text-text outline-none placeholder:text-text-dim min-w-0"
          />
        ) : (
          step.label && <span className="text-xs text-text-muted flex-1">{step.label}</span>
        )}

        {/* Status badge */}
        {stepState && <StepResultBadge state={stepState} />}

        {/* Actions — always visible on mobile or in compact (canvas) mode; hover-only on desktop linear view */}
        {!readOnly && (
          <div className={`flex flex-row items-center gap-1.5 ml-auto shrink-0 ${
            compact
              ? "opacity-100"
              : "max-sm:opacity-100 opacity-0 group-hover:opacity-100 transition-opacity"
          }`}>
            <MiniDropdown
              value={step.on_failure ?? "abort"}
              options={ON_FAILURE_OPTIONS}
              onChange={(v) => update({ on_failure: v as "abort" | "continue" })}
            />
            <button
              onClick={onDelete}
              className="p-1 bg-transparent border-none cursor-pointer text-text-dim hover:text-danger transition-colors rounded hover:bg-danger/5"
            >
              <Trash2 size={13} />
            </button>
          </div>
        )}
      </div>

      {/* Body — type-specific fields */}
      <div className={`${bodyPad} flex flex-col ${bodyGap}`}>
        {step.type === "exec" && (
          <>
            <textarea
              value={step.prompt ?? ""}
              onChange={(e) => update({ prompt: e.target.value })}
              readOnly={readOnly}
              placeholder="Shell command..."
              rows={2}
              className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none resize-y focus:border-accent/40 w-full"
            />
            {!readOnly && (
              <input
                type="text"
                value={step.working_directory ?? ""}
                onChange={(e) => update({ working_directory: e.target.value || null })}
                placeholder="Working directory (optional)"
                className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs outline-none w-full focus:border-accent/40"
              />
            )}
          </>
        )}

        {step.type === "tool" && (
          <>
            {readOnly ? (
              <div className="text-xs text-text font-mono">{step.tool_name ?? "No tool selected"}</div>
            ) : (
              <SharedToolSelector
                value={step.tool_name ?? null}
                tools={tools}
                onChange={(toolName, tool) => {
                  const scaffold = scaffoldArgsFromSchema(tool);
                  update({
                    tool_name: toolName,
                    label: step.label || toolName,
                    tool_args: Object.keys(scaffold).length > 0 ? scaffold : step.tool_args,
                  });
                }}
              />
            )}
            <ToolArgsEditor
              step={step}
              tools={tools}
              readOnly={readOnly}
              onChange={(args) => update({ tool_args: args })}
            />
          </>
        )}

        {(step.type === "machine_inspect" || step.type === "machine_exec") && (
          <>
            <textarea
              value={step.command ?? step.prompt ?? ""}
              onChange={(e) => update({ command: e.target.value, prompt: undefined })}
              readOnly={readOnly}
              placeholder={step.type === "machine_inspect" ? "Readonly SSH command..." : "SSH shell command..."}
              rows={2}
              className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none resize-y focus:border-accent/40 w-full"
            />
            {step.type === "machine_exec" && !readOnly && (
              <input
                type="text"
                value={step.working_directory ?? ""}
                onChange={(e) => update({ working_directory: e.target.value || null })}
                placeholder="Remote working directory (optional)"
                className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs outline-none w-full focus:border-accent/40"
              />
            )}
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
              className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs outline-none resize-y focus:border-accent/40 w-full"
            />
            {!readOnly && (
              <div className="flex-1">
                <LlmModelDropdown
                  value={step.model ?? ""}
                  onChange={(v) => update({ model: v || null })}
                  placeholder="Inherit model"
                  allowClear
                />
              </div>
            )}
          </>
        )}

        {step.type === "user_prompt" && (
          <UserPromptFields step={step} readOnly={readOnly} onChange={update} />
        )}

        {step.type === "foreach" && (
          <ForeachFields step={step} tools={tools} readOnly={readOnly} onChange={update} />
        )}

        {!isKnownStepType(step.type) && (
          <div className="flex flex-col gap-2">
            <div className="flex flex-row items-start gap-2 text-[11px] text-text-dim bg-surface-overlay/40 border border-surface-border rounded-md p-2">
              <AlertCircle size={12} className="shrink-0 mt-0.5 text-warning-muted" />
              <span>
                Step type <code className="text-accent/80 bg-accent/5 px-1 rounded">{String(step.type)}</code> isn't
                editable in this view — open the JSON view to edit raw fields.
              </span>
            </div>
            <pre className="m-0 p-2 rounded-md bg-surface border border-surface-border text-[11px] font-mono text-text-muted whitespace-pre-wrap max-h-52 overflow-y-auto">
              {JSON.stringify(step, null, 2)}
            </pre>
          </div>
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
        {stepState && stepState.error && (
          <div className="rounded-md bg-danger/10 p-2">
            <div className="flex flex-row items-center gap-1.5 mb-1">
              <XCircle size={11} className="text-danger" />
              <span className="text-[10px] font-semibold text-danger uppercase tracking-wider">Error</span>
            </div>
            <pre className="text-[11px] font-mono text-danger whitespace-pre-wrap max-h-32 overflow-y-auto m-0">
              {stepState.error}
            </pre>
          </div>
        )}
        {stepState && stepState.result != null && !stepState.error && (() => {
          const raw = stepState.result as unknown;
          const resultStr =
            typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
          return (
            <details className="group/result" open={stepState.status === "done" && steps.length <= 3}>
              <summary className="flex flex-row items-center gap-1.5 cursor-pointer text-[10px] font-semibold text-success uppercase tracking-wider transition-colors select-none">
                <CheckCircle2 size={11} />
                Output
                <span className="text-text-dim font-normal normal-case tracking-normal ml-1 truncate max-w-[200px]">
                  {resultStr.slice(0, 60)}{resultStr.length > 60 ? "..." : ""}
                </span>
              </summary>
              <pre className="mt-1.5 p-2 rounded-md bg-surface border border-surface-border text-[11px] font-mono text-text-muted whitespace-pre-wrap max-h-40 overflow-y-auto m-0">
                {resultStr}
              </pre>
            </details>
          );
        })()}
      </div>
    </div>
  );
}
