/**
 * TaskStepEditor — inline pipeline builder for the task editor.
 *
 * Renders an ordered list of step cards (exec/tool/agent) with conditions,
 * reorder controls, and an "Add Step" button. Used inside TaskCreateModal
 * and TaskEditor when the user toggles from single-prompt to steps mode.
 */
import { useState, useCallback, useMemo } from "react";
import { ChevronUp, ChevronDown, Trash2, Terminal, Wrench, Bot, Plus, AlertCircle } from "lucide-react";
import type { StepDef, StepType, StepState } from "@/src/api/hooks/useTasks";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";
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
// Tool parameter scaffolding from JSON Schema
// ---------------------------------------------------------------------------

function scaffoldArgsFromSchema(tool: ToolItem): Record<string, any> {
  const params = tool.parameters ?? tool.schema_?.parameters;
  if (!params || typeof params !== "object") return {};
  const properties = params.properties ?? params;
  if (!properties || typeof properties !== "object") return {};
  const scaffold: Record<string, any> = {};
  for (const [key, def] of Object.entries(properties)) {
    const d = def as any;
    if (d.default !== undefined) {
      scaffold[key] = d.default;
    } else if (d.type === "string") {
      scaffold[key] = "";
    } else if (d.type === "number" || d.type === "integer") {
      scaffold[key] = 0;
    } else if (d.type === "boolean") {
      scaffold[key] = false;
    } else if (d.type === "array") {
      scaffold[key] = [];
    } else if (d.type === "object") {
      scaffold[key] = {};
    } else {
      scaffold[key] = null;
    }
  }
  return scaffold;
}

function getParamDescriptions(tool: ToolItem): Map<string, string> {
  const descs = new Map<string, string>();
  const params = tool.parameters ?? tool.schema_?.parameters;
  if (!params || typeof params !== "object") return descs;
  const properties = params.properties ?? params;
  if (!properties || typeof properties !== "object") return descs;
  const required = new Set<string>(params.required ?? []);
  for (const [key, def] of Object.entries(properties)) {
    const d = def as any;
    const parts: string[] = [];
    if (d.type) parts.push(d.type);
    if (required.has(key)) parts.push("required");
    if (d.description) parts.push(`— ${d.description}`);
    descs.set(key, parts.join(" "));
  }
  return descs;
}

// ---------------------------------------------------------------------------
// Tool selector with search
// ---------------------------------------------------------------------------

function ToolSelector({ value, tools, onChange }: {
  value: string | null;
  tools: ToolItem[];
  onChange: (toolName: string, tool: ToolItem) => void;
}) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);

  const filtered = useMemo(() => {
    const term = search.toLowerCase();
    return tools
      .filter((t) => !term || t.tool_name.toLowerCase().includes(term) || (t.description ?? "").toLowerCase().includes(term))
      .slice(0, 20);
  }, [tools, search]);

  const selectedTool = tools.find((t) => t.tool_name === value);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2 w-full px-2.5 py-1.5 text-xs rounded-md border cursor-pointer text-left transition-colors ${
          open ? "border-accent bg-surface" : "border-surface-border bg-input hover:border-accent/50"
        }`}
      >
        <Wrench size={12} className="text-blue-400 shrink-0" />
        <span className={`flex-1 truncate ${value ? "text-text" : "text-text-dim"}`}>
          {selectedTool ? selectedTool.tool_name : "Select tool..."}
        </span>
        {selectedTool?.source_integration && (
          <span className="text-[10px] text-text-dim px-1.5 py-0.5 rounded bg-surface-overlay shrink-0">
            {selectedTool.source_integration}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-surface border border-surface-border rounded-lg shadow-xl z-20 max-h-[260px] overflow-hidden flex flex-col">
          <div className="p-2 border-b border-surface-border shrink-0">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search tools..."
              autoFocus
              className="w-full px-2.5 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent"
            />
          </div>
          <div className="overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="px-3 py-3 text-[11px] text-text-dim">No tools found</div>
            ) : (
              filtered.map((tool) => (
                <button
                  key={tool.tool_key}
                  onClick={() => { onChange(tool.tool_name, tool); setOpen(false); setSearch(""); }}
                  className="flex flex-col gap-0.5 w-full px-3 py-2 bg-transparent border-none cursor-pointer text-left transition-colors hover:bg-surface-raised"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-text">{tool.tool_name}</span>
                    {tool.source_integration && (
                      <span className="text-[10px] text-text-dim px-1.5 py-0.5 rounded bg-surface-overlay">
                        {tool.source_integration}
                      </span>
                    )}
                  </div>
                  {tool.description && (
                    <span className="text-[10px] text-text-dim line-clamp-1">{tool.description}</span>
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
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

  if (stepIndex === 0) return null;

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
// Tool args editor with schema hints
// ---------------------------------------------------------------------------

function ToolArgsEditor({ step, tools, readOnly, onChange }: {
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

  // If we have schema, show structured fields; otherwise show raw JSON
  if (!rawMode && tool && paramDescs.size > 0 && !readOnly) {
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
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
                // Try to preserve type from schema
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
              className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs font-mono outline-none focus:border-accent w-full"
            />
          </div>
        ))}
      </div>
    );
  }

  // Raw JSON mode or no schema
  return (
    <div className="flex flex-col gap-1">
      {paramDescs.size > 0 && !readOnly && (
        <div className="flex items-center justify-between">
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
        className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none resize-y focus:border-accent w-full"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Individual step card
// ---------------------------------------------------------------------------

function StepCard({ step, stepIndex, steps, stepState, readOnly, tools, onChange, onDelete, onMove }: {
  step: StepDef;
  stepIndex: number;
  steps: StepDef[];
  stepState?: StepState;
  readOnly?: boolean;
  tools: ToolItem[];
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
            {readOnly ? (
              <div className="text-xs text-text font-mono">{step.tool_name ?? "No tool selected"}</div>
            ) : (
              <ToolSelector
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
// Add step button with inline type picker
// ---------------------------------------------------------------------------

function AddStepButton({ onAdd }: { onAdd: (type: StepType) => void }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative inline-flex">
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-text-muted bg-transparent border border-dashed border-surface-border rounded-lg cursor-pointer hover:border-accent/50 hover:text-accent transition-colors"
        >
          <Plus size={13} />
          Add Step
        </button>
      ) : (
        <div className="flex items-center gap-1">
          {STEP_TYPES.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.value}
                onClick={() => { onAdd(t.value); setOpen(false); }}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-surface-raised border border-surface-border rounded-lg cursor-pointer text-text hover:border-accent/50 hover:text-accent transition-colors"
              >
                <Icon size={13} className={t.color} />
                {t.label}
              </button>
            );
          })}
          <button
            onClick={() => setOpen(false)}
            className="px-2 py-1.5 text-xs text-text-dim bg-transparent border-none cursor-pointer hover:text-text"
          >
            Cancel
          </button>
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
  const { data: allTools } = useTools();
  const tools = allTools ?? [];

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
          tools={tools}
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
