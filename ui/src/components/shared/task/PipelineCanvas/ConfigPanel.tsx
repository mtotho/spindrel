import { ChevronUp, ChevronDown, Trash2, AlertTriangle, ExternalLink } from "lucide-react";
import type { StepDef, StepType } from "@/src/api/hooks/useTasks";
import type { ToolItem } from "@/src/api/hooks/useTools";
import { isKnownStepType, stepMeta } from "../TaskStepEditorModel";
import { LlmModelDropdown } from "../../LlmModelDropdown";
import { ToolSelector as SharedToolSelector } from "../../ToolSelector";
import { MiniDropdown } from "../step-editor/MiniDropdown";
import { ON_FAILURE_OPTIONS, StepTypeSelector } from "../step-editor/StepTypeSelector";
import { StepConditionEditor } from "../step-editor/StepConditionEditor";
import { ToolArgsEditor } from "../step-editor/ToolArgsEditor";
import { UserPromptFields } from "../step-editor/UserPromptFields";
import { ForeachFields } from "../step-editor/ForeachFields";
import { scaffoldArgsFromSchema } from "../step-editor/toolSchemaHelpers";
import { classifyWhen } from "./edges";
import type { EdgeDescriptor } from "./edges";

interface ConfigPanelProps {
  steps: StepDef[];
  selectedStepId: string | null;
  selectedEdge: EdgeDescriptor | null;
  staleStepIds: Set<string>;
  tools: ToolItem[];
  readOnly?: boolean;
  onUpdateStep: (id: string, updated: StepDef) => void;
  onDeleteStep: (id: string) => void;
  onMoveStep: (id: string, dir: -1 | 1) => void;
  onJumpToJson: () => void;
}

function ComplexConditionSummary({ when, onJumpToJson }: {
  when: Record<string, any> | null;
  onJumpToJson: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 p-2 rounded-md bg-surface-overlay/40 border border-surface-border">
      <div className="flex flex-row items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-dim font-semibold">
        <AlertTriangle size={11} className="text-warning-muted" />
        Complex condition
      </div>
      <pre className="m-0 p-2 rounded bg-surface text-[11px] font-mono text-text-muted whitespace-pre-wrap max-h-40 overflow-y-auto">
        {JSON.stringify(when, null, 2)}
      </pre>
      <button
        onClick={onJumpToJson}
        className="self-start inline-flex items-center gap-1 text-[10px] text-accent bg-transparent border-none cursor-pointer hover:underline"
      >
        Edit as JSON <ExternalLink size={10} />
      </button>
      <p className="m-0 text-[10px] text-text-dim leading-relaxed">
        Combinators (<code>all</code> / <code>any</code> / <code>not</code>) and
        param refs round-trip but aren't editable in the visual builder yet.
      </p>
    </div>
  );
}

function StepBody({ step, tools, readOnly, onUpdate }: {
  step: StepDef;
  tools: ToolItem[];
  readOnly?: boolean;
  onUpdate: (patch: Partial<StepDef>) => void;
}) {
  if (!isKnownStepType(step.type)) {
    return (
      <div className="flex flex-col gap-2">
        <div className="text-[11px] text-text-dim bg-surface-overlay/40 border border-surface-border rounded-md p-2">
          Step type <code className="text-accent/80 bg-accent/5 px-1 rounded">{String(step.type)}</code> isn't
          editable here — open the JSON tab to edit raw fields.
        </div>
        <pre className="m-0 p-2 rounded-md bg-surface border border-surface-border text-[11px] font-mono text-text-muted whitespace-pre-wrap max-h-52 overflow-y-auto">
          {JSON.stringify(step, null, 2)}
        </pre>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {step.type === "exec" && (
        <>
          <textarea
            value={step.prompt ?? ""}
            onChange={(e) => onUpdate({ prompt: e.target.value })}
            readOnly={readOnly}
            placeholder="Shell command..."
            rows={3}
            className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none resize-y focus:border-accent/40 w-full"
          />
          {!readOnly && (
            <input
              type="text"
              value={step.working_directory ?? ""}
              onChange={(e) => onUpdate({ working_directory: e.target.value || null })}
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
                onUpdate({
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
            onChange={(args) => onUpdate({ tool_args: args })}
          />
        </>
      )}

      {step.type === "agent" && (
        <>
          <textarea
            value={step.prompt ?? ""}
            onChange={(e) => onUpdate({ prompt: e.target.value })}
            readOnly={readOnly}
            placeholder="LLM prompt — prior step results are auto-injected..."
            rows={4}
            className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs outline-none resize-y focus:border-accent/40 w-full"
          />
          {!readOnly && (
            <LlmModelDropdown
              value={step.model ?? ""}
              onChange={(v) => onUpdate({ model: v || null })}
              placeholder="Inherit model"
              allowClear
            />
          )}
        </>
      )}

      {step.type === "user_prompt" && (
        <UserPromptFields step={step} readOnly={readOnly} onChange={onUpdate} />
      )}

      {step.type === "foreach" && (
        <ForeachFields step={step} tools={tools} readOnly={readOnly} onChange={onUpdate} />
      )}
    </div>
  );
}

export function ConfigPanel({
  steps,
  selectedStepId,
  selectedEdge,
  staleStepIds,
  tools,
  readOnly,
  onUpdateStep,
  onDeleteStep,
  onMoveStep,
  onJumpToJson,
}: ConfigPanelProps) {
  // Edge mode wins over step mode if both are technically set.
  if (selectedEdge) {
    const target = steps.find((s) => s.id === selectedEdge.toId);
    if (!target) return <EmptyPanel />;
    const idx = steps.findIndex((s) => s.id === target.id);
    const kind = classifyWhen(target.when);

    return (
      <div className="p-3 flex flex-col gap-3">
        <div className="text-[10px] font-bold uppercase tracking-wider text-text-dim">
          Edge → {target.label || target.id}
        </div>
        {kind === "unconditional" && (
          <p className="m-0 text-xs text-text-dim">
            Unconditional. Runs whenever the previous step finishes. Add a condition below.
          </p>
        )}
        {kind === "complex" && (
          <ComplexConditionSummary
            when={(target.when ?? null) as Record<string, any> | null}
            onJumpToJson={onJumpToJson}
          />
        )}
        {kind !== "complex" && (
          <StepConditionEditor
            step={target}
            stepIndex={idx}
            steps={steps}
            onChange={(when) => onUpdateStep(target.id, { ...target, when })}
          />
        )}
      </div>
    );
  }

  if (!selectedStepId) {
    return <EmptyPanel />;
  }

  const idx = steps.findIndex((s) => s.id === selectedStepId);
  if (idx < 0) return <EmptyPanel />;
  const step = steps[idx];
  const meta = stepMeta(step.type);
  const Icon = meta.icon;
  const isFirst = idx === 0;
  const isLast = idx === steps.length - 1;

  const update = (patch: Partial<StepDef>) =>
    onUpdateStep(step.id, { ...step, ...patch });

  return (
    <div className="p-3 flex flex-col gap-3 overflow-y-auto">
      <div className="flex flex-row items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${meta.bgBadge}`}
        >
          <Icon size={11} />
          {meta.label}
        </span>
        {!readOnly && (
          <div className="ml-auto flex flex-row items-center gap-1">
            <button
              onClick={() => onMoveStep(step.id, -1)}
              disabled={isFirst}
              title="Move up in execution order"
              className="p-1 rounded text-text-dim hover:text-text disabled:opacity-30 bg-transparent border-none cursor-pointer disabled:cursor-not-allowed"
            >
              <ChevronUp size={14} />
            </button>
            <button
              onClick={() => onMoveStep(step.id, 1)}
              disabled={isLast}
              title="Move down in execution order"
              className="p-1 rounded text-text-dim hover:text-text disabled:opacity-30 bg-transparent border-none cursor-pointer disabled:cursor-not-allowed"
            >
              <ChevronDown size={14} />
            </button>
            <button
              onClick={() => onDeleteStep(step.id)}
              title="Delete step"
              className="p-1 rounded text-text-dim hover:text-danger bg-transparent border-none cursor-pointer"
            >
              <Trash2 size={13} />
            </button>
          </div>
        )}
      </div>

      {staleStepIds.has(step.id) && (
        <div className="flex flex-row items-start gap-2 text-[11px] text-warning-muted bg-warning/5 border border-warning/30 rounded-md p-2">
          <AlertTriangle size={12} className="shrink-0 mt-0.5" />
          <span>
            Condition references <code>{(step.when as any)?.step}</code> which no longer
            runs before this step. Edit in the JSON tab to fix.
          </span>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <label className="text-[10px] font-bold uppercase tracking-wider text-text-dim">
          Type
        </label>
        {readOnly ? (
          <div className="text-xs text-text">{meta.label}</div>
        ) : (
          <StepTypeSelector
            value={isKnownStepType(step.type) ? (step.type as StepType) : "exec"}
            onChange={(v) => update({ type: v })}
          />
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-bold uppercase tracking-wider text-text-dim">ID</label>
        <input
          type="text"
          value={step.id}
          onChange={(e) => update({ id: e.target.value })}
          readOnly={readOnly}
          className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs font-mono outline-none focus:border-accent/40 w-full"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-bold uppercase tracking-wider text-text-dim">Label</label>
        <input
          type="text"
          value={step.label ?? ""}
          onChange={(e) => update({ label: e.target.value })}
          readOnly={readOnly}
          placeholder="Optional human-readable name"
          className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs outline-none focus:border-accent/40 w-full"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-bold uppercase tracking-wider text-text-dim">
          On failure
        </label>
        {readOnly ? (
          <div className="text-xs text-text">{step.on_failure ?? "abort"}</div>
        ) : (
          <MiniDropdown
            value={step.on_failure ?? "abort"}
            options={ON_FAILURE_OPTIONS}
            onChange={(v) => update({ on_failure: v as "abort" | "continue" })}
          />
        )}
      </div>

      <StepBody step={step} tools={tools} readOnly={readOnly} onUpdate={update} />
    </div>
  );
}

function EmptyPanel() {
  return (
    <div className="p-4 text-xs text-text-dim leading-relaxed">
      Click a step or edge on the canvas to edit it. Drag the canvas to pan,
      wheel to zoom.
    </div>
  );
}
