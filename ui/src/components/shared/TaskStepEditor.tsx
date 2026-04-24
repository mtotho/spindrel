/**
 * TaskStepEditor — vertical timeline pipeline builder for the task editor.
 *
 * Renders an ordered list of step cards connected by a vertical timeline line,
 * with numbered circle nodes, colored type badges, and an "Add Step" button.
 */
import { useState, useCallback, useMemo } from "react";
import { ChevronUp, ChevronDown, Trash2, Terminal, Wrench, Bot, Plus, CheckCircle2, XCircle, Clock, SkipForward, PauseCircle, MessageCircleQuestion, Repeat, AlertCircle, HelpCircle } from "lucide-react";
import type { StepDef, StepType, StepState, ResponseSchema } from "@/src/api/hooks/useTasks";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";
import { LlmModelDropdown } from "./LlmModelDropdown";
import { JsonObjectEditor } from "./task/JsonObjectEditor";
import { SelectDropdown } from "./SelectDropdown";
import { ToolSelector as SharedToolSelector } from "./ToolSelector";

// ---------------------------------------------------------------------------
// Step type metadata
// ---------------------------------------------------------------------------

type StepTypeMeta = { value: StepType; label: string; icon: typeof Terminal; color: string; bgBadge: string; node: string };

const STEP_TYPES: StepTypeMeta[] = [
  { value: "exec",         label: "Shell",       icon: Terminal,               color: "text-amber-300",   bgBadge: "bg-amber-500/10 text-amber-300 border-amber-500/25",       node: "bg-amber-500/15 text-amber-300 border border-amber-500/30" },
  { value: "tool",         label: "Tool",        icon: Wrench,                 color: "text-sky-300",     bgBadge: "bg-sky-500/10 text-sky-300 border-sky-500/25",             node: "bg-sky-500/15 text-sky-300 border border-sky-500/30" },
  { value: "agent",        label: "LLM",         icon: Bot,                    color: "text-violet-300",  bgBadge: "bg-violet-500/10 text-violet-300 border-violet-500/25",    node: "bg-violet-500/15 text-violet-300 border border-violet-500/30" },
  { value: "user_prompt",  label: "User prompt", icon: MessageCircleQuestion,  color: "text-teal-300",    bgBadge: "bg-teal-500/10 text-teal-300 border-teal-500/25",          node: "bg-teal-500/15 text-teal-300 border border-teal-500/30" },
  { value: "foreach",      label: "For each",    icon: Repeat,                 color: "text-fuchsia-300", bgBadge: "bg-fuchsia-500/10 text-fuchsia-300 border-fuchsia-500/25", node: "bg-fuchsia-500/15 text-fuchsia-300 border border-fuchsia-500/30" },
];

const UNKNOWN_STEP_META: StepTypeMeta = {
  value: "exec",
  label: "Unknown",
  icon: HelpCircle,
  color: "text-text-dim",
  bgBadge: "bg-surface-overlay text-text-dim border-surface-border",
  node: "bg-surface-overlay text-text-dim border border-surface-border",
};

function stepMeta(type: string): StepTypeMeta {
  return STEP_TYPES.find((s) => s.value === type) ?? UNKNOWN_STEP_META;
}

function isKnownStepType(type: string): type is StepType {
  return STEP_TYPES.some((s) => s.value === type);
}

let _stepCounter = 0;
function nextStepId(): string {
  return `step_${++_stepCounter}`;
}

function emptyStep(type: StepType): StepDef {
  const base: StepDef = {
    id: nextStepId(),
    type,
    label: "",
    on_failure: "abort",
  };
  if (type === "exec" || type === "agent") {
    base.prompt = "";
  } else if (type === "user_prompt") {
    base.title = "";
    base.response_schema = { type: "binary" };
  } else if (type === "foreach") {
    base.over = "";
    base.on_failure = "continue";
    base.do = [];
  }
  return base;
}

function emptyToolSubStep(): StepDef {
  return {
    id: nextStepId(),
    type: "tool",
    label: "",
    on_failure: "abort",
  };
}

// ---------------------------------------------------------------------------
// Shared compact dropdown wrapper for tight task-editor controls.
// ---------------------------------------------------------------------------

function MiniDropdown({ value, options, onChange, className }: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <div className={className ?? ""}>
      <SelectDropdown
        value={value}
        options={options}
        onChange={(next) => onChange(next)}
        size="compact"
        popoverWidth="content"
        triggerClassName="min-h-[26px] border-surface-border/70 bg-surface-overlay/40 text-xs"
      />
    </div>
  );
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
// Condition editor
// ---------------------------------------------------------------------------

type ConditionMode = "always" | "output_contains" | "output_not_contains" | "status_is";

const CONDITION_OPTIONS: { value: ConditionMode; label: string }[] = [
  { value: "always", label: "Always" },
  { value: "output_contains", label: "If prev output contains" },
  { value: "output_not_contains", label: "If prev output NOT contains" },
  { value: "status_is", label: "If prev step status is" },
];

const STATUS_OPTIONS = [
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Skipped" },
];

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
    <div className="flex flex-row items-center gap-2 text-xs flex-wrap">
      <span className="text-text-dim shrink-0">Run</span>
      <MiniDropdown
        value={mode}
        options={CONDITION_OPTIONS}
        onChange={(m) => {
          onChange(buildCondition(m as ConditionMode, m === "status_is" ? "done" : "", prevStepId));
        }}
      />
      {(mode === "output_contains" || mode === "output_not_contains") && (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(buildCondition(mode, e.target.value, prevStepId))}
          placeholder="text to match..."
          className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs outline-none flex-1 min-w-[100px] focus:border-accent/40"
        />
      )}
      {mode === "status_is" && (
        <MiniDropdown
          value={value || "done"}
          options={STATUS_OPTIONS}
          onChange={(v) => onChange(buildCondition(mode, v, prevStepId))}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step result badge
// ---------------------------------------------------------------------------

function StepResultBadge({ state }: { state: StepState }) {
  const config: Record<string, { classes: string; Icon: typeof CheckCircle2; label: string }> = {
    done: { classes: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", Icon: CheckCircle2, label: "done" },
    failed: { classes: "bg-red-500/10 text-red-400 border-red-500/20", Icon: XCircle, label: "failed" },
    skipped: { classes: "bg-surface-overlay text-text-dim border-surface-border", Icon: SkipForward, label: "skipped" },
    running: { classes: "bg-blue-500/10 text-blue-400 border-blue-500/20 animate-pulse", Icon: Clock, label: "running" },
    pending: { classes: "bg-surface-overlay text-text-dim border-surface-border", Icon: Clock, label: "pending" },
    awaiting_user_input: { classes: "bg-accent/10 text-accent border-accent/25 animate-pulse", Icon: PauseCircle, label: "awaiting input" },
  };
  const { classes, Icon, label } = config[state.status] ?? config.pending;
  return (
    <span className={`inline-flex flex-row items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${classes}`}>
      <Icon size={10} />
      {label}
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

// ---------------------------------------------------------------------------
// Step type selector (custom dropdown)
// ---------------------------------------------------------------------------

const ON_FAILURE_OPTIONS = [
  { value: "abort", label: "Stop on fail" },
  { value: "continue", label: "Continue on fail" },
];

function StepTypeSelector({ value, onChange }: { value: StepType; onChange: (v: StepType) => void }) {
  const meta = stepMeta(value);
  const Icon = meta.icon;

  return (
    <div className="w-[126px] shrink-0">
      <SelectDropdown
        value={value}
        options={STEP_TYPES.map((stepType) => {
          const StepIcon = stepType.icon;
          return {
            value: stepType.value,
            label: stepType.label,
            icon: <StepIcon size={12} className={stepType.color} />,
          };
        })}
        onChange={(next) => {
          if (isKnownStepType(next)) onChange(next);
        }}
        size="compact"
        popoverWidth="content"
        renderValue={() => (
          <span className="inline-flex min-w-0 items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider">
            <Icon size={11} />
            <span className="truncate">{meta.label}</span>
          </span>
        )}
        triggerClassName={`min-h-[26px] rounded-full px-2.5 ${meta.bgBadge} hover:opacity-80`}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// user_prompt + foreach field renderers
// ---------------------------------------------------------------------------

const RESPONSE_SCHEMA_OPTIONS = [
  { value: "binary", label: "Approve / Reject" },
  { value: "multi_item", label: "Per-item approve/reject" },
];

const WIDGET_TEMPLATE_SKELETON = {
  kind: "approval_review",
  title: "Proposed changes",
  proposals_ref: "{{steps.analyze.result.proposals}}",
};

function UserPromptFields({ step, readOnly, onChange }: {
  step: StepDef;
  readOnly?: boolean;
  onChange: (patch: Partial<StepDef>) => void;
}) {
  const schemaType = step.response_schema?.type ?? "binary";
  const itemsRef =
    step.response_schema && step.response_schema.type === "multi_item"
      ? step.response_schema.items_ref ?? ""
      : "";

  const setSchema = (next: ResponseSchema) => onChange({ response_schema: next });

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">Title</label>
        <input
          type="text"
          value={step.title ?? ""}
          onChange={(e) => onChange({ title: e.target.value })}
          readOnly={readOnly}
          placeholder="Shown above the widget"
          className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs outline-none focus:border-accent/40 w-full"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">Response</label>
        <div className="flex flex-row items-center gap-2 flex-wrap">
          {readOnly ? (
            <span className="text-xs text-text-muted font-mono">{schemaType}</span>
          ) : (
            <MiniDropdown
              value={schemaType}
              options={RESPONSE_SCHEMA_OPTIONS}
              onChange={(v) => {
                if (v === "binary") setSchema({ type: "binary" });
                else setSchema({ type: "multi_item", items_ref: itemsRef });
              }}
            />
          )}
          {schemaType === "multi_item" && (
            <input
              type="text"
              value={itemsRef}
              onChange={(e) => setSchema({ type: "multi_item", items_ref: e.target.value })}
              readOnly={readOnly}
              placeholder="{{steps.analyze.result.proposals}}"
              className="flex-1 min-w-[200px] bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none focus:border-accent/40"
            />
          )}
        </div>
      </div>

      <JsonObjectEditor
        label="Widget template"
        hint="kind + args"
        value={step.widget_template ?? null}
        onChange={(next) => onChange({ widget_template: next })}
        readOnly={readOnly}
        schemaSkeleton={WIDGET_TEMPLATE_SKELETON}
        schemaLabel="Insert skeleton"
        placeholder='{"kind": "approval_review", ...}'
      />

      <JsonObjectEditor
        label="Widget args (optional)"
        hint="extra substitutions"
        value={step.widget_args ?? null}
        onChange={(next) => onChange({ widget_args: next })}
        readOnly={readOnly}
        placeholder="{}"
        minHeight={80}
        maxHeight={200}
      />
    </div>
  );
}

function ForeachFields({ step, tools, readOnly, onChange }: {
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
        <div className="flex flex-col gap-2 pl-2 border-l-2 border-dashed border-surface-border">
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
              className="self-start flex flex-row items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold text-text-muted bg-transparent border border-dashed border-surface-border rounded-md cursor-pointer hover:border-accent/50 hover:text-accent transition-colors"
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

function ForeachSubStepCard({ sub, tools, readOnly, onChange, onDelete }: {
  sub: StepDef;
  tools: ToolItem[];
  readOnly?: boolean;
  onChange: (next: StepDef) => void;
  onDelete: () => void;
}) {
  const update = (patch: Partial<StepDef>) => onChange({ ...sub, ...patch });

  return (
    <div className="rounded-md border border-surface-border bg-surface-raised/30 group">
      <div className="flex flex-row items-center gap-2 px-2.5 py-2">
        <span className="inline-flex flex-row items-center gap-1 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider rounded-full border bg-sky-500/10 text-sky-300 border-sky-500/25">
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

      <div className="px-2.5 py-2 flex flex-col gap-2 border-t border-surface-border/50">
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

// ---------------------------------------------------------------------------
// Timeline step card
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
    <div className="rounded-lg border border-surface-border bg-surface-raised/40 group transition-colors hover:border-surface-border/80">
      {/* Header row */}
      <div className="flex flex-row items-center gap-2.5 px-2.5 sm:px-3.5 py-2.5">
        {/* Reorder controls */}
        {!readOnly && (
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
          <span className={`inline-flex flex-row items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded-full border ${meta.bgBadge}`}>
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

        {/* Actions — always visible on mobile, hover on desktop */}
        {!readOnly && (
          <div className="flex flex-row items-center gap-1.5 ml-auto shrink-0 max-sm:opacity-100 opacity-0 group-hover:opacity-100 transition-opacity">
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
      <div className="px-2.5 sm:px-3.5 py-3 flex flex-col gap-2.5 border-t border-surface-border/50">
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
              <AlertCircle size={12} className="shrink-0 mt-0.5 text-amber-400" />
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
          <div className="rounded-md border border-red-500/20 bg-red-500/5 p-2">
            <div className="flex flex-row items-center gap-1.5 mb-1">
              <XCircle size={11} className="text-red-400" />
              <span className="text-[10px] font-semibold text-red-400 uppercase tracking-wider">Error</span>
            </div>
            <pre className="text-[11px] font-mono text-red-300/80 whitespace-pre-wrap max-h-32 overflow-y-auto m-0">
              {stepState.error}
            </pre>
          </div>
        )}
        {stepState && stepState.result != null && !stepState.error && (() => {
          // Some step types (user_prompt, resolve-endpoint responses) persist
          // `result` as a JSON object / dict — the step runner writes dicts
          // for user_prompt auto-skip and the resolve endpoint stores the
          // response map verbatim. Coerce to string for display.
          const raw = stepState.result as unknown;
          const resultStr =
            typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
          return (
            <details className="group/result" open={stepState.status === "done" && steps.length <= 3}>
              <summary className="flex flex-row items-center gap-1.5 cursor-pointer text-[10px] font-semibold text-emerald-400/70 uppercase tracking-wider hover:text-emerald-400 transition-colors select-none">
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

// ---------------------------------------------------------------------------
// Add step button with inline type picker
// ---------------------------------------------------------------------------

function AddStepButton({ onAdd }: { onAdd: (type: StepType) => void }) {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex flex-row items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-text-muted bg-transparent border border-dashed border-surface-border rounded-lg cursor-pointer hover:border-accent/50 hover:text-accent transition-colors"
      >
        <Plus size={14} />
        Add Step
      </button>
    );
  }

  return (
    <div className="flex flex-row items-center gap-1.5">
      {STEP_TYPES.map((t) => {
        const TIcon = t.icon;
        return (
          <button
            key={t.value}
            onClick={() => { onAdd(t.value); setOpen(false); }}
            className="flex flex-row items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-surface-raised border border-surface-border rounded-lg cursor-pointer text-text hover:border-accent/50 hover:text-accent transition-colors"
          >
            <TIcon size={14} className={t.color} />
            {t.label}
          </button>
        );
      })}
      <button
        onClick={() => setOpen(false)}
        className="px-2.5 py-2 text-xs text-text-dim bg-transparent border-none cursor-pointer hover:text-text"
      >
        Cancel
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main editor — vertical timeline layout
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
    <div className="flex flex-col">
      {steps.length === 0 && !readOnly && (
        <div className="flex flex-col items-center gap-3 py-10 text-text-dim rounded-xl border border-dashed border-surface-border bg-surface-raised/20">
          <div className="text-sm font-medium text-text-muted">Build your pipeline</div>
          <div className="text-xs text-text-dim">Add steps to create a multi-step automation</div>
          <div className="flex flex-row items-center gap-1.5 mt-2">
            {STEP_TYPES.map((t) => {
              const TIcon = t.icon;
              return (
                <button
                  key={t.value}
                  onClick={() => addStep(t.value)}
                  className="flex flex-row items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-surface border border-surface-border rounded-lg cursor-pointer text-text hover:border-accent/50 hover:text-accent transition-colors"
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
                ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                : stepState?.status === "failed"
                  ? "bg-red-500/15 text-red-300 border border-red-500/30"
                  : stepState?.status === "running"
                    ? "bg-blue-500/15 text-blue-300 border border-blue-500/30 animate-pulse"
                    : meta.node;

              return (
                <div key={step.id} className="relative">
                  {/* Timeline node */}
                  <div className={`absolute -left-3 sm:-left-5 top-[11px] flex items-center justify-center w-[18px] h-[18px] sm:w-[22px] sm:h-[22px] rounded-full text-[9px] sm:text-[10px] font-bold z-10 ${nodeColor} shadow-sm`}>
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
          <AddStepButton onAdd={addStep} />
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
