import { useState } from "react";
import {
  GripVertical,
  Trash2,
  ChevronRight,
  ChevronDown,
  Code2,
  LayoutList,
  Wrench,
  Bot,
  Terminal,
  MessageCircleQuestion,
  Repeat,
  Box,
} from "lucide-react";
import type { StepDef, StepType } from "@/src/api/hooks/useTasks";
import type { TaskFormState } from "@/src/components/shared/task/useTaskFormState";
import { useDraggableTile, type TilePos } from "./useDraggableTile";

interface StepTileProps {
  step: StepDef;
  index: number;
  form: TaskFormState;
  position: TilePos;
  onPositionChange: (pos: TilePos) => void;
  onUpdate: (patch: Partial<StepDef>) => void;
  onDelete: () => void;
}

const STEP_TYPES: StepType[] = ["exec", "tool", "agent", "user_prompt", "foreach"];

function iconFor(type?: string) {
  switch (type) {
    case "exec": return Terminal;
    case "tool": return Wrench;
    case "agent": return Bot;
    case "user_prompt": return MessageCircleQuestion;
    case "foreach": return Repeat;
    default: return Box;
  }
}

function summaryFor(step: StepDef): string {
  switch (step.type) {
    case "tool": return step.tool_name || "(no tool)";
    case "exec": return step.prompt?.split("\n")[0]?.slice(0, 60) || "(no command)";
    case "agent": return step.prompt?.slice(0, 60) || "(no prompt)";
    case "user_prompt": return step.title || step.prompt?.slice(0, 60) || "(prompt user)";
    case "foreach": return step.over ? `over ${step.over}` : "(foreach)";
    default: return step.type ?? "(unknown)";
  }
}

export function StepTile({ step, index, form, position, onPositionChange, onUpdate, onDelete }: StepTileProps) {
  const [expanded, setExpanded] = useState(false);
  const [jsonMode, setJsonMode] = useState(false);
  const { dragHandleProps, tileStyle } = useDraggableTile({ position, onChange: onPositionChange });

  const Icon = iconFor(step.type);
  const summary = summaryFor(step);

  return (
    <div
      data-canvas-tile
      style={tileStyle}
      className="flex flex-col rounded-xl border border-surface-border bg-surface shadow-lg w-[300px] overflow-hidden"
    >
      {/* Header — drag handle + delete */}
      <div
        {...dragHandleProps}
        className="flex flex-row items-center gap-2 px-2.5 py-2 border-b border-surface-border shrink-0 select-none bg-surface-raised/30"
      >
        <GripVertical size={12} className="text-text-dim shrink-0" />
        <span className="text-[10px] font-mono text-text-dim shrink-0">#{index + 1}</span>
        <Icon size={13} className="text-accent shrink-0" />
        <span className="text-[11.5px] font-semibold text-text flex-1 truncate">
          {step.label?.trim() || step.id}
        </span>
        <button
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); setExpanded((x) => !x); }}
          aria-label={expanded ? "Collapse" : "Expand"}
          className="flex items-center justify-center w-5 h-5 rounded bg-transparent border-none cursor-pointer text-text-dim hover:text-text hover:bg-surface-overlay/50 transition-colors"
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        <button
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          aria-label="Delete step"
          className="flex items-center justify-center w-5 h-5 rounded bg-transparent border-none cursor-pointer text-text-dim hover:text-danger hover:bg-danger/[0.08] transition-colors"
        >
          <Trash2 size={11} />
        </button>
      </div>

      {/* Collapsed summary */}
      {!expanded && (
        <div className="px-2.5 py-2 text-[11px] text-text-dim truncate">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-text-dim mr-1.5">
            {step.type}
          </span>
          <span className="text-text-muted">{summary}</span>
        </div>
      )}

      {/* Expanded body */}
      {expanded && (
        <div className="flex flex-col gap-2.5 px-2.5 py-2.5">
          {/* Visual / JSON toggle */}
          <div className="flex flex-row items-center gap-0 bg-surface-raised/40 rounded-md p-0.5 w-fit">
            <button
              onClick={() => setJsonMode(false)}
              className={`flex flex-row items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded border-none cursor-pointer transition-colors ${
                !jsonMode ? "bg-surface-overlay text-text" : "bg-transparent text-text-dim hover:text-text"
              }`}
            >
              <LayoutList size={10} />
              Fields
            </button>
            <button
              onClick={() => setJsonMode(true)}
              className={`flex flex-row items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded border-none cursor-pointer transition-colors ${
                jsonMode ? "bg-surface-overlay text-text" : "bg-transparent text-text-dim hover:text-text"
              }`}
            >
              <Code2 size={10} />
              JSON
            </button>
          </div>

          {jsonMode ? (
            <StepJsonEditor step={step} onUpdate={onUpdate} />
          ) : (
            <StepFieldEditor step={step} form={form} onUpdate={onUpdate} />
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field editor — per-type form fields
// ---------------------------------------------------------------------------

function StepFieldEditor({ step, form, onUpdate }: {
  step: StepDef;
  form: TaskFormState;
  onUpdate: (patch: Partial<StepDef>) => void;
}) {
  return (
    <>
      <FieldRow label="ID">
        <input
          type="text"
          value={step.id}
          onChange={(e) => onUpdate({ id: e.target.value })}
          className="bg-input border border-surface-border rounded px-2 py-1 text-text text-[11.5px] font-mono outline-none w-full focus:border-accent/40"
        />
      </FieldRow>

      <FieldRow label="Type">
        <select
          value={step.type}
          onChange={(e) => onUpdate({ type: e.target.value as StepType })}
          className="bg-input border border-surface-border rounded px-2 py-1 text-text text-[11.5px] outline-none w-full focus:border-accent/40 cursor-pointer"
        >
          {STEP_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </FieldRow>

      <FieldRow label="Label">
        <input
          type="text"
          value={step.label || ""}
          onChange={(e) => onUpdate({ label: e.target.value })}
          placeholder="(optional)"
          className="bg-input border border-surface-border rounded px-2 py-1 text-text text-[11.5px] outline-none w-full focus:border-accent/40"
        />
      </FieldRow>

      {/* Type-specific fields */}
      {step.type === "tool" && (
        <>
          <FieldRow label="Tool">
            <select
              value={step.tool_name || ""}
              onChange={(e) => onUpdate({ tool_name: e.target.value || null })}
              className="bg-input border border-surface-border rounded px-2 py-1 text-text text-[11.5px] outline-none w-full focus:border-accent/40 cursor-pointer"
            >
              <option value="">— Select tool —</option>
              {form.allTools.map((t) => (
                <option key={t.tool_key} value={t.tool_name}>{t.tool_name}</option>
              ))}
            </select>
          </FieldRow>
          <FieldRow label="Args (JSON)">
            <JsonInput
              value={step.tool_args ?? null}
              onChange={(v) => onUpdate({ tool_args: v })}
              rows={3}
            />
          </FieldRow>
        </>
      )}

      {(step.type === "agent" || step.type === "exec" || step.type === "user_prompt") && (
        <FieldRow label={step.type === "exec" ? "Command" : "Prompt"}>
          <textarea
            value={step.prompt || ""}
            onChange={(e) => onUpdate({ prompt: e.target.value })}
            rows={3}
            placeholder={step.type === "exec" ? "Shell command..." : "Prompt..."}
            className="bg-input border border-surface-border rounded px-2 py-1.5 text-text text-[11.5px] outline-none w-full font-mono focus:border-accent/40 resize-y"
          />
        </FieldRow>
      )}

      {step.type === "exec" && (
        <FieldRow label="Working dir">
          <input
            type="text"
            value={step.working_directory || ""}
            onChange={(e) => onUpdate({ working_directory: e.target.value || null })}
            placeholder="(optional)"
            className="bg-input border border-surface-border rounded px-2 py-1 text-text text-[11.5px] font-mono outline-none w-full focus:border-accent/40"
          />
        </FieldRow>
      )}

      {step.type === "user_prompt" && (
        <FieldRow label="Title">
          <input
            type="text"
            value={step.title || ""}
            onChange={(e) => onUpdate({ title: e.target.value })}
            placeholder="Prompt title"
            className="bg-input border border-surface-border rounded px-2 py-1 text-text text-[11.5px] outline-none w-full focus:border-accent/40"
          />
        </FieldRow>
      )}

      {step.type === "foreach" && (
        <FieldRow label="Over">
          <input
            type="text"
            value={step.over || ""}
            onChange={(e) => onUpdate({ over: e.target.value })}
            placeholder="step_1.items"
            className="bg-input border border-surface-border rounded px-2 py-1 text-text text-[11.5px] font-mono outline-none w-full focus:border-accent/40"
          />
          <span className="text-[10px] text-text-dim mt-1 block">
            Sub-steps editable in JSON view.
          </span>
        </FieldRow>
      )}

      {/* When (condition) — simple JSON for now */}
      <FieldRow label="When (JSON)" description="Run only when this condition matches">
        <JsonInput
          value={step.when ?? null}
          onChange={(v) => onUpdate({ when: v })}
          rows={2}
          placeholder='{"step":"step_1","status":"done"}'
        />
      </FieldRow>

      <FieldRow label="On failure">
        <select
          value={step.on_failure || "abort"}
          onChange={(e) => onUpdate({ on_failure: e.target.value as "abort" | "continue" })}
          className="bg-input border border-surface-border rounded px-2 py-1 text-text text-[11.5px] outline-none w-full focus:border-accent/40 cursor-pointer"
        >
          <option value="abort">abort</option>
          <option value="continue">continue</option>
        </select>
      </FieldRow>
    </>
  );
}

// ---------------------------------------------------------------------------
// JSON editor — raw step
// ---------------------------------------------------------------------------

function StepJsonEditor({ step, onUpdate }: { step: StepDef; onUpdate: (patch: Partial<StepDef>) => void }) {
  const [text, setText] = useState(() => JSON.stringify(step, null, 2));
  const [err, setErr] = useState<string | null>(null);

  const apply = () => {
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== "object" || parsed === null) {
        setErr("Must be a JSON object");
        return;
      }
      setErr(null);
      onUpdate(parsed as Partial<StepDef>);
    } catch (e: any) {
      setErr(e?.message ?? "Invalid JSON");
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={apply}
        rows={10}
        spellCheck={false}
        className="bg-input border border-surface-border rounded px-2 py-1.5 text-text text-[11px] font-mono outline-none w-full focus:border-accent/40 resize-y"
      />
      {err && <span className="text-[10.5px] text-danger">{err}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function FieldRow({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] font-semibold uppercase tracking-wider text-text-dim">{label}</label>
      {children}
      {description && <span className="text-[10px] text-text-dim">{description}</span>}
    </div>
  );
}

function JsonInput({ value, onChange, rows, placeholder }: {
  value: any;
  onChange: (v: any) => void;
  rows?: number;
  placeholder?: string;
}) {
  const [text, setText] = useState(() => (value == null ? "" : JSON.stringify(value, null, 2)));
  const [err, setErr] = useState<string | null>(null);

  const commit = () => {
    if (!text.trim()) { setErr(null); onChange(null); return; }
    try {
      const parsed = JSON.parse(text);
      setErr(null);
      onChange(parsed);
    } catch (e: any) {
      setErr(e?.message ?? "Invalid JSON");
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        rows={rows ?? 2}
        placeholder={placeholder}
        spellCheck={false}
        className="bg-input border border-surface-border rounded px-2 py-1.5 text-text text-[11px] font-mono outline-none w-full focus:border-accent/40 resize-y"
      />
      {err && <span className="text-[10.5px] text-danger">{err}</span>}
    </div>
  );
}
