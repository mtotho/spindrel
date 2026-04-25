import { useState } from "react";
import type { StepDef } from "@/src/api/hooks/useTasks";
import type { ToolItem } from "@/src/api/hooks/useTools";
import { getParamDescriptions } from "./toolSchemaHelpers";

export function ToolArgsEditor({ step, tools, readOnly, onChange }: {
  step: StepDef;
  tools: ToolItem[];
  readOnly?: boolean;
  onChange: (args: Record<string, any> | null) => void;
}) {
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState("");

  const tool = tools.find((t) => t.tool_name === step.tool_name);
  const paramDescs = tool ? getParamDescriptions(tool) : new Map();
  const currentArgs = step.tool_args ?? {};

  if (!rawMode && tool && paramDescs.size > 0 && !readOnly) {
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-row items-center justify-between">
          <span className="text-[10px] text-text-dim font-semibold uppercase tracking-wider">Parameters</span>
          <button
            onClick={() => { setRawText(JSON.stringify(currentArgs, null, 2)); setRawMode(true); }}
            className="text-[10px] text-text-dim bg-transparent border-none cursor-pointer hover:text-accent"
          >
            Edit JSON
          </button>
        </div>
        {Array.from(paramDescs.entries()).map(([key, desc]) => (
          <div key={key} className="flex flex-col gap-0.5">
            <label className="text-[10px] text-text-dim">
              {key} <span className="opacity-60">({desc})</span>
            </label>
            <input
              type="text"
              value={currentArgs[key] != null ? String(currentArgs[key]) : ""}
              onChange={(e) => {
                const val = e.target.value;
                const updated = { ...currentArgs };
                if (val === "") {
                  updated[key] = "";
                } else if (val === "true" || val === "false") {
                  updated[key] = val === "true";
                } else if (!isNaN(Number(val)) && val.trim() !== "") {
                  updated[key] = Number(val);
                } else {
                  updated[key] = val;
                }
                onChange(updated);
              }}
              className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs font-mono outline-none focus:border-accent/40 w-full"
            />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {paramDescs.size > 0 && !readOnly && (
        <div className="flex flex-row items-center justify-between">
          <span className="text-[10px] text-text-dim font-semibold uppercase tracking-wider">Arguments (JSON)</span>
          <button
            onClick={() => setRawMode(false)}
            className="text-[10px] text-text-dim bg-transparent border-none cursor-pointer hover:text-accent"
          >
            Form view
          </button>
        </div>
      )}
      <textarea
        value={rawMode ? rawText : (step.tool_args ? JSON.stringify(step.tool_args, null, 2) : "")}
        onChange={(e) => {
          if (rawMode) setRawText(e.target.value);
          try {
            const parsed = e.target.value ? JSON.parse(e.target.value) : null;
            onChange(parsed);
          } catch {
            // Allow invalid JSON while typing
          }
        }}
        readOnly={readOnly}
        placeholder='{"key": "value"}'
        rows={3}
        className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none resize-y focus:border-accent/40 w-full"
      />
    </div>
  );
}
