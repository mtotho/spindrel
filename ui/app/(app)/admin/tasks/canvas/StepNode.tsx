import { memo } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { StepDef, StepState } from "@/src/api/hooks/useTasks";
import type { ToolItem } from "@/src/api/hooks/useTools";
import { stepMeta } from "@/src/components/shared/task/TaskStepEditorModel";
import { StepCard } from "@/src/components/shared/task/step-editor/StepCard";

const INVISIBLE_HANDLE = "!w-1 !h-1 !min-w-0 !min-h-0 !opacity-0 !border-none !bg-transparent pointer-events-none";

export interface StepNodeData extends Record<string, unknown> {
  step: StepDef;
  stepIndex: number;
  steps: StepDef[];
  stepState?: StepState | null;
  tools: ToolItem[];
  expanded: boolean;
  readOnly?: boolean;
  onChange: (updated: StepDef) => void;
  onDelete: () => void;
  onMove: (dir: -1 | 1) => void;
  onToggleExpand: () => void;
}

function summary(step: StepDef): string {
  switch (step.type) {
    case "tool": return step.tool_name || "—";
    case "exec": return step.prompt?.split("\n")[0]?.slice(0, 60) || "—";
    case "agent": return step.prompt?.slice(0, 60) || "—";
    case "user_prompt": return step.title || step.prompt?.slice(0, 60) || "—";
    case "foreach": return step.over ? `over ${step.over}` : "—";
    default: return step.type ?? "—";
  }
}

type StepNodeType = Node<StepNodeData, "step">;

function StepNodeImpl({ data, selected }: NodeProps<StepNodeType>) {
  const d = data;
  const meta = stepMeta(d.step.type);

  const ringClass = selected
    ? "ring-2 ring-accent/60 ring-offset-2 ring-offset-surface"
    : "";

  return (
    <div
      className={`flex flex-col rounded-xl border border-surface-border bg-surface shadow-lg overflow-hidden ${ringClass}`}
      style={{ width: d.expanded ? 380 : 260 }}
    >
      <Handle type="target" position={Position.Left} className={INVISIBLE_HANDLE} isConnectable={false} />
      <Handle type="source" position={Position.Right} className={INVISIBLE_HANDLE} isConnectable={false} />

      {/* Header — index + label + expand. Drag handle. */}
      <div className="flex flex-row items-center gap-2 px-2.5 py-1.5 bg-surface-raised/40 border-b border-surface-border select-none cursor-grab active:cursor-grabbing">
        <span className="text-[10px] font-mono text-text-dim shrink-0">#{d.stepIndex + 1}</span>
        <span className="text-[11.5px] font-semibold text-text flex-1 truncate">
          {d.step.label?.trim() || d.step.id}
        </span>
        <button
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); d.onToggleExpand(); }}
          aria-label={d.expanded ? "Collapse" : "Expand"}
          className="flex items-center justify-center w-5 h-5 rounded bg-transparent border-none cursor-pointer text-text-dim hover:text-text hover:bg-surface-overlay/50 transition-colors nodrag"
        >
          {d.expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
      </div>

      {/* Collapsed summary */}
      {!d.expanded && (
        <div className="px-2.5 py-2 text-[11px] text-text-dim truncate">
          <span className="text-[9.5px] font-semibold uppercase tracking-wider mr-1.5 text-text-muted">
            {meta.label}
          </span>
          <span className="text-text-muted">{summary(d.step)}</span>
        </div>
      )}

      {/* Expanded — full StepCard inline (compact = canvas variant) */}
      {d.expanded && (
        <div className="nodrag nowheel" onPointerDown={(e) => e.stopPropagation()}>
          <StepCard
            step={d.step}
            stepIndex={d.stepIndex}
            steps={d.steps}
            stepState={d.stepState ?? undefined}
            readOnly={d.readOnly}
            tools={d.tools}
            onChange={d.onChange}
            onDelete={d.onDelete}
            onMove={d.onMove}
            compact
          />
        </div>
      )}
    </div>
  );
}

export const StepNode = memo(StepNodeImpl);
