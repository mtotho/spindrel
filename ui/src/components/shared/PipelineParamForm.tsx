import { useMemo } from "react";
import { useBots } from "@/src/api/hooks/useBots";
import { BotPicker } from "./BotPicker";

export interface PipelineParamDef {
  name: string;
  required?: boolean;
  description?: string;
}

export interface PipelineParamFormProps {
  schema: PipelineParamDef[];
  values: Record<string, any>;
  onChange: (next: Record<string, any>) => void;
  disabled?: boolean;
}

// Turn `bot_id` / `channel_id` / raw snake_case into human-readable labels.
const PARAM_LABEL_OVERRIDES: Record<string, string> = {
  bot_id: "Bot",
  channel_id: "Channel",
  user_id: "User",
  task_id: "Task",
};

export function humanizeParam(name: string): string {
  if (PARAM_LABEL_OVERRIDES[name]) return PARAM_LABEL_OVERRIDES[name];
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function isFormValid(
  schema: PipelineParamDef[],
  values: Record<string, any>,
): boolean {
  return schema.every((p) => {
    if (!p.required) return true;
    const v = values[p.name];
    return v !== undefined && v !== null && v !== "";
  });
}

/**
 * Renders the inputs for a pipeline's ``params_schema``. Pure form — no
 * modal chrome, no submit button. Shared between the legacy inline
 * ``TaskRunModal`` and the new ``PipelineRunPreRun`` modal pane.
 */
export function PipelineParamForm({
  schema,
  values,
  onChange,
  disabled,
}: PipelineParamFormProps) {
  const { data: bots = [] } = useBots();
  const set = useMemo(() => (k: string, v: any) => onChange({ ...values, [k]: v }), [onChange, values]);

  if (schema.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {schema.map((param) => (
        <div key={param.name} className="flex flex-col gap-1">
          <label className="text-[12px] font-semibold text-text">
            {humanizeParam(param.name)}
            {param.required && <span className="text-accent ml-1">*</span>}
          </label>
          {param.name === "bot_id" ? (
            <BotPicker
              value={values[param.name] ?? ""}
              onChange={(v) => set(param.name, v)}
              bots={bots}
              placeholder="Select a bot..."
              disabled={disabled}
            />
          ) : (
            <input
              type="text"
              value={values[param.name] ?? ""}
              onChange={(e) => set(param.name, e.target.value)}
              disabled={disabled}
              placeholder={param.description}
              className="px-2.5 py-1.5 text-sm bg-surface border border-surface-border
                         rounded-md focus:outline-none focus:border-accent/50
                         text-text placeholder:text-text-dim"
            />
          )}
          {param.description && (
            <span className="text-[10px] text-text-dim">{param.description}</span>
          )}
        </div>
      ))}
    </div>
  );
}
