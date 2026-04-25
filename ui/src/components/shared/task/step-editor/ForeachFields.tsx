import { Plus, Trash2, Wrench } from "lucide-react";
import type { StepDef } from "@/src/api/hooks/useTasks";
import type { ToolItem } from "@/src/api/hooks/useTools";
import { ToolSelector as SharedToolSelector } from "../../ToolSelector";
import { emptyToolSubStep } from "../TaskStepEditorModel";
import { ToolArgsEditor } from "./ToolArgsEditor";
import { scaffoldArgsFromSchema } from "./toolSchemaHelpers";

function ForeachSubStepCard({ sub, tools, readOnly, onChange, onDelete }: {
  sub: StepDef;
  tools: ToolItem[];
  readOnly?: boolean;
  onChange: (next: StepDef) => void;
  onDelete: () => void;
}) {
  const update = (patch: Partial<StepDef>) => onChange({ ...sub, ...patch });

  return (
    <div className="rounded-md bg-surface-raised/45 group">
      <div className="flex flex-row items-center gap-2 px-2.5 py-2">
        <span className="inline-flex flex-row items-center gap-1 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider rounded-full bg-surface-overlay text-text-muted">
          <Wrench size={10} />
          Tool
        </span>
        {!readOnly ? (
          <input
            type="text"
            value={sub.label ?? ""}
            onChange={(e) => update({ label: e.target.value })}
            placeholder="Sub-step label (optional)"
            className="flex-1 bg-transparent border-none text-xs text-text outline-none placeholder:text-text-dim min-w-0"
          />
        ) : (
          sub.label && <span className="text-xs text-text-muted flex-1">{sub.label}</span>
        )}
        {!readOnly && (
          <button
            onClick={onDelete}
            className="p-1 bg-transparent border-none cursor-pointer text-text-dim hover:text-danger transition-colors rounded hover:bg-danger/5 opacity-0 group-hover:opacity-100 max-sm:opacity-100 transition-opacity"
            title="Delete sub-step"
          >
            <Trash2 size={12} />
          </button>
        )}
      </div>

      <div className="px-2.5 pb-2 flex flex-col gap-2">
        {readOnly ? (
          <div className="text-xs text-text font-mono">{sub.tool_name ?? "No tool selected"}</div>
        ) : (
          <SharedToolSelector
            value={sub.tool_name ?? null}
            tools={tools}
            onChange={(toolName, tool) => {
              const scaffold = scaffoldArgsFromSchema(tool);
              update({
                tool_name: toolName,
                label: sub.label || toolName,
                tool_args: Object.keys(scaffold).length > 0 ? scaffold : sub.tool_args,
              });
            }}
          />
        )}
        <ToolArgsEditor
          step={sub}
          tools={tools}
          readOnly={readOnly}
          onChange={(args) => update({ tool_args: args })}
        />
      </div>
    </div>
  );
}

export function ForeachFields({ step, tools, readOnly, onChange }: {
  step: StepDef;
  tools: ToolItem[];
  readOnly?: boolean;
  onChange: (patch: Partial<StepDef>) => void;
}) {
  const subSteps = step.do ?? [];

  const updateSub = (idx: number, next: StepDef) => {
    const out = subSteps.slice();
    out[idx] = next;
    onChange({ do: out });
  };
  const deleteSub = (idx: number) => {
    onChange({ do: subSteps.filter((_, i) => i !== idx) });
  };
  const addSub = () => onChange({ do: [...subSteps, emptyToolSubStep()] });

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">Iterate over</label>
        <input
          type="text"
          value={step.over ?? ""}
          onChange={(e) => onChange({ over: e.target.value })}
          readOnly={readOnly}
          placeholder="{{steps.analyze.result.proposals}}"
          className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none focus:border-accent/40 w-full"
        />
        <span className="text-[10px] text-text-dim opacity-70">
          A <code className="text-accent/80 bg-accent/5 px-1 rounded">{"{{steps.*}}"}</code> or{" "}
          <code className="text-accent/80 bg-accent/5 px-1 rounded">{"{{params.*}}"}</code> expression resolving to a list.
        </span>
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex flex-row items-center">
          <label className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">For each item, run</label>
          <span className="ml-2 text-[10px] text-text-dim opacity-70">
            v1 supports only <code className="text-accent/80 bg-accent/5 px-1 rounded">tool</code> sub-steps.
          </span>
        </div>
        <div className="flex flex-col gap-2 rounded-md bg-surface-raised/25 p-2">
          {subSteps.length === 0 && !readOnly && (
            <div className="text-[11px] text-text-dim italic py-1">No sub-steps yet.</div>
          )}
          {subSteps.map((sub, idx) => (
            <ForeachSubStepCard
              key={sub.id || idx}
              sub={sub}
              tools={tools}
              readOnly={readOnly}
              onChange={(next) => updateSub(idx, next)}
              onDelete={() => deleteSub(idx)}
            />
          ))}
          {!readOnly && (
            <button
              onClick={addSub}
              className="self-start flex flex-row items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold text-text-muted bg-transparent border border-transparent rounded-md cursor-pointer hover:bg-accent/[0.08] hover:text-accent transition-colors"
            >
              <Plus size={11} />
              Add tool sub-step
            </button>
          )}
        </div>
      </div>

      <div className="text-[10px] text-text-dim opacity-70 leading-relaxed">
        Inside sub-steps, reference the current item with{" "}
        <code className="text-accent/80 bg-accent/5 px-1 rounded">{"{{item.field}}"}</code>,{" "}
        <code className="text-accent/80 bg-accent/5 px-1 rounded">{"{{item_index}}"}</code>, or{" "}
        <code className="text-accent/80 bg-accent/5 px-1 rounded">{"{{item_count}}"}</code>. Per-outer-step gating
        via <code className="text-accent/80 bg-accent/5 px-1 rounded">when</code> is supported — edit via the JSON view.
      </div>
    </div>
  );
}
