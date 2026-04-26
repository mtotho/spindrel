import { memo, useState } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { FileText, SlidersHorizontal, Clock } from "lucide-react";

const INVISIBLE_HANDLE = "!w-1 !h-1 !min-w-0 !min-h-0 !opacity-0 !border-none !bg-transparent pointer-events-none";
import {
  ContentFields,
  ExecutionFields,
  TriggerFields,
} from "@/src/components/shared/task/TaskFormFields";
import type { TaskFormState } from "@/src/components/shared/task/useTaskFormState";

type Section = "content" | "execution" | "trigger";

const SECTIONS: Array<{ key: Section; label: string; Icon: typeof FileText }> = [
  { key: "content", label: "Content", Icon: FileText },
  { key: "execution", label: "Execution", Icon: SlidersHorizontal },
  { key: "trigger", label: "Trigger", Icon: Clock },
];

export interface TaskNodeData extends Record<string, unknown> {
  form: TaskFormState;
  isCreate: boolean;
}

type TaskNodeType = Node<TaskNodeData, "task">;

function TaskNodeImpl({ data, selected }: NodeProps<TaskNodeType>) {
  const d = data;
  const [section, setSection] = useState<Section>("content");

  const title = d.isCreate
    ? "New Task"
    : d.form.title?.trim() || d.form.existingTask?.title || "Task";
  const modeLabel = d.form.stepsMode ? "Pipeline" : "Prompt";

  const ringClass = selected
    ? "ring-2 ring-accent/60 ring-offset-2 ring-offset-surface"
    : "";

  return (
    <div
      className={`flex flex-col rounded-xl border border-surface-border bg-surface shadow-xl overflow-hidden ${ringClass}`}
      style={{ width: 420, maxHeight: "78vh" }}
    >
      <Handle type="source" position={Position.Right} className={INVISIBLE_HANDLE} isConnectable={false} />

      {/* Header — drag handle */}
      <div className="flex flex-row items-center gap-2 px-3 py-2.5 border-b border-surface-border shrink-0 select-none bg-surface-raised/40 cursor-grab active:cursor-grabbing">
        <span className="text-text text-[13px] font-bold flex-1 tracking-tight truncate">
          {title}
        </span>
        <span className="text-[10.5px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent/10 text-accent shrink-0">
          {modeLabel}
        </span>
      </div>

      {/* Section tabs */}
      <div className="nodrag nowheel flex flex-row items-center gap-0 px-2 pt-2 shrink-0" onPointerDown={(e) => e.stopPropagation()}>
        {SECTIONS.map(({ key, label, Icon }) => (
          <button
            key={key}
            onClick={() => setSection(key)}
            className={`flex flex-row items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium border-none cursor-pointer rounded-md transition-colors ${
              section === key
                ? "bg-accent/10 text-accent"
                : "bg-transparent text-text-dim hover:text-text hover:bg-surface-overlay/50"
            }`}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      {/* Body */}
      <div
        className="nodrag nowheel flex-1 min-h-0 overflow-y-auto px-3 py-3"
        onPointerDown={(e) => e.stopPropagation()}
        onWheelCapture={(e) => e.stopPropagation()}
      >
        {section === "content" && <ContentFields form={d.form} promptRows={4} hideStepEditor />}
        {section === "execution" && <ExecutionFields form={d.form} />}
        {section === "trigger" && <TriggerFields form={d.form} />}
      </div>
    </div>
  );
}

export const TaskNode = memo(TaskNodeImpl);
