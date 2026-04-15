/**
 * TaskStepEditor — vertical timeline pipeline builder for the task editor.
 *
 * Renders an ordered list of step cards connected by a vertical timeline line,
 * with numbered circle nodes, colored type badges, and an "Add Step" button.
 */
import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import { ChevronUp, ChevronDown, Trash2, Terminal, Wrench, Bot, Plus, CheckCircle2, XCircle, Clock, SkipForward, ChevronDown as ChevronDownIcon } from "lucide-react";
import type { StepDef, StepType, StepState } from "@/src/api/hooks/useTasks";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";
import { LlmModelDropdown } from "./LlmModelDropdown";

// ---------------------------------------------------------------------------
// Step type metadata
// ---------------------------------------------------------------------------

const STEP_TYPES: { value: StepType; label: string; icon: typeof Terminal; color: string; bgBadge: string; nodeActive: string; borderAccent: string; cardBg: string }[] = [
  { value: "exec", label: "Shell", icon: Terminal, color: "text-amber-400", bgBadge: "bg-amber-400/10 text-amber-400 border-amber-400/25", nodeActive: "bg-amber-400 text-white", borderAccent: "border-l-amber-400/60", cardBg: "bg-amber-400/[0.03]" },
  { value: "tool", label: "Tool", icon: Wrench, color: "text-blue-400", bgBadge: "bg-blue-400/10 text-blue-400 border-blue-400/25", nodeActive: "bg-blue-400 text-white", borderAccent: "border-l-blue-400/60", cardBg: "bg-blue-400/[0.03]" },
  { value: "agent", label: "LLM", icon: Bot, color: "text-purple-400", bgBadge: "bg-purple-400/10 text-purple-400 border-purple-400/25", nodeActive: "bg-purple-400 text-white", borderAccent: "border-l-purple-400/60", cardBg: "bg-purple-400/[0.03]" },
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
// Custom dropdown (replaces all native <select>)
// ---------------------------------------------------------------------------

function MiniDropdown({ value, options, onChange, className }: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className={`relative ${className ?? ""}`}>
      <button
        onClick={() => setOpen(!open)}
        className="flex flex-row items-center gap-1 bg-surface-overlay/80 border border-surface-border rounded px-2 py-1 text-xs text-text cursor-pointer hover:border-accent/40 transition-colors whitespace-nowrap"
      >
        <span className="truncate">{selected?.label ?? value}</span>
        <ChevronDownIcon size={10} className="text-text-dim shrink-0" />
      </button>
      {open && (
        <div className="absolute top-full right-0 mt-1 bg-surface border border-surface-border rounded-lg shadow-xl z-50 min-w-[140px] py-1 overflow-hidden">
          {options.map((opt) => (
            <button
              key={opt.value}
              onClick={() => { onChange(opt.value); setOpen(false); }}
              className={`flex flex-row w-full px-3 py-1.5 text-xs border-none cursor-pointer text-left transition-colors ${
                opt.value === value ? "bg-accent/10 text-accent font-medium" : "bg-transparent text-text hover:bg-surface-raised"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
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
// Tool selector with search
// ---------------------------------------------------------------------------

function ToolSelector({ value, tools, onChange }: {
  value: string | null;
  tools: ToolItem[];
  onChange: (toolName: string, tool: ToolItem) => void;
}) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 });

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        triggerRef.current && !triggerRef.current.contains(e.target as Node) &&
        dropdownRef.current && !dropdownRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const openDropdown = () => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left, width: rect.width });
    }
    setOpen(!open);
  };

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
        ref={triggerRef}
        onClick={openDropdown}
        className={`flex flex-row items-center gap-2 w-full px-2.5 py-1.5 text-xs rounded-md border cursor-pointer text-left transition-colors ${
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
        <ChevronDownIcon size={12} className="text-text-dim shrink-0" />
      </button>
      {open && ReactDOM.createPortal(
        <div
          ref={dropdownRef}
          className="fixed bg-surface border border-surface-border rounded-lg shadow-xl z-[10001] max-h-[260px] overflow-hidden flex flex-col"
          style={{ top: pos.top, left: pos.left, width: pos.width }}
        >
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
                  <div className="flex flex-row items-center gap-2">
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
        </div>,
        document.body,
      )}
    </div>
  );
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
          className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs outline-none flex-1 min-w-[100px] focus:border-accent"
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
  const config: Record<string, { classes: string; Icon: typeof CheckCircle2 }> = {
    done: { classes: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", Icon: CheckCircle2 },
    failed: { classes: "bg-red-500/10 text-red-400 border-red-500/20", Icon: XCircle },
    skipped: { classes: "bg-surface-overlay text-text-dim border-surface-border", Icon: SkipForward },
    running: { classes: "bg-blue-500/10 text-blue-400 border-blue-500/20 animate-pulse", Icon: Clock },
    pending: { classes: "bg-surface-overlay text-text-dim border-surface-border", Icon: Clock },
  };
  const { classes, Icon } = config[state.status] ?? config.pending;
  return (
    <span className={`inline-flex flex-row items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${classes}`}>
      <Icon size={10} />
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
              className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs font-mono outline-none focus:border-accent w-full"
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
        className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none resize-y focus:border-accent w-full"
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
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const meta = stepMeta(value);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`inline-flex flex-row items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded-full border cursor-pointer transition-colors ${meta.bgBadge} hover:opacity-80`}
      >
        {meta.label}
        <ChevronDownIcon size={9} className="opacity-60" />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-surface border border-surface-border rounded-lg shadow-xl z-50 py-1 min-w-[130px]">
          {STEP_TYPES.map((t) => {
            const TIcon = t.icon;
            return (
              <button
                key={t.value}
                onClick={() => { onChange(t.value); setOpen(false); }}
                className={`flex flex-row items-center gap-2 w-full px-3 py-1.5 text-xs border-none cursor-pointer text-left transition-colors ${
                  t.value === value ? "bg-accent/10 text-accent font-medium" : "bg-transparent text-text hover:bg-surface-raised"
                }`}
              >
                <TIcon size={12} className={t.color} />
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
    <div className={`rounded-lg border border-surface-border ${meta.borderAccent} border-l-[3px] shadow-sm group transition-shadow hover:shadow-md ${meta.cardBg}`}>
      {/* Header row */}
      <div className="flex flex-row items-center gap-2.5 px-3.5 py-2.5">
        {/* Reorder controls */}
        {!readOnly && (
          <div className="flex flex-col shrink-0 -my-1 opacity-0 group-hover:opacity-100 transition-opacity">
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
            className="flex-1 bg-transparent border-none text-xs text-text-muted outline-none placeholder:text-text-dim/40 min-w-0"
          />
        ) : (
          step.label && <span className="text-xs text-text-muted flex-1">{step.label}</span>
        )}

        {/* Status badge */}
        {stepState && <StepResultBadge state={stepState} />}

        {/* Actions — hover revealed */}
        {!readOnly && (
          <div className="flex flex-row items-center gap-1.5 ml-auto shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
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
      <div className="px-3.5 py-3 flex flex-col gap-2.5 border-t border-surface-border/50">
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
        {stepState && stepState.result && !stepState.error && (
          <details className="group/result" open={stepState.status === "done" && steps.length <= 3}>
            <summary className="flex flex-row items-center gap-1.5 cursor-pointer text-[10px] font-semibold text-emerald-400/70 uppercase tracking-wider hover:text-emerald-400 transition-colors select-none">
              <CheckCircle2 size={11} />
              Output
              <span className="text-text-dim font-normal normal-case tracking-normal ml-1 truncate max-w-[200px]">
                {stepState.result.slice(0, 60)}{stepState.result.length > 60 ? "..." : ""}
              </span>
            </summary>
            <pre className="mt-1.5 p-2 rounded-md bg-surface border border-surface-border text-[11px] font-mono text-text-muted whitespace-pre-wrap max-h-40 overflow-y-auto m-0">
              {stepState.result}
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
        <div className="relative pl-5">
          {/* Vertical timeline line */}
          {steps.length > 1 && (
            <div
              className="absolute left-[11px] top-[22px] bottom-[22px] w-[2px] bg-surface-border rounded-full"
            />
          )}

          <div className="flex flex-col gap-3">
            {steps.map((step, i) => {
              const meta = stepMeta(step.type);
              const stepState = stepStates?.[i];
              const nodeColor = stepState?.status === "done"
                ? "bg-emerald-500 text-white"
                : stepState?.status === "failed"
                  ? "bg-red-500 text-white"
                  : stepState?.status === "running"
                    ? "bg-blue-500 text-white animate-pulse"
                    : meta.nodeActive;

              return (
                <div key={step.id} className="relative">
                  {/* Timeline node */}
                  <div className={`absolute -left-5 top-[11px] flex items-center justify-center w-[22px] h-[22px] rounded-full text-[10px] font-bold z-10 ${nodeColor} shadow-sm`}>
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
        <div className="mt-3 pl-5">
          <AddStepButton onAdd={addStep} />
        </div>
      )}

      {/* Hint */}
      {!readOnly && steps.length > 0 && (
        <p className="text-[10px] text-text-dim mt-3 pl-5">
          Prior step results are auto-injected. Use <code className="text-accent/80 bg-accent/5 px-1 py-0.5 rounded text-[10px]">{"{{steps.<id>.result}}"}</code> for explicit references.
        </p>
      )}
    </div>
  );
}
