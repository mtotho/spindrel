import { useState } from "react";
import { GripVertical, FileText, SlidersHorizontal, Clock } from "lucide-react";
import {
  ContentFields,
  ExecutionFields,
  TriggerFields,
} from "@/src/components/shared/task/TaskFormFields";
import type { TaskFormState } from "@/src/components/shared/task/useTaskFormState";
import { useDraggableTile, type TilePos } from "./useDraggableTile";

type Section = "content" | "execution" | "trigger";

interface TaskTileProps {
  form: TaskFormState;
  position: TilePos;
  onPositionChange: (pos: TilePos) => void;
  isCreate: boolean;
}

const SECTIONS: Array<{ key: Section; label: string; Icon: typeof FileText }> = [
  { key: "content", label: "Content", Icon: FileText },
  { key: "execution", label: "Execution", Icon: SlidersHorizontal },
  { key: "trigger", label: "Trigger", Icon: Clock },
];

export function TaskTile({ form, position, onPositionChange, isCreate }: TaskTileProps) {
  const [section, setSection] = useState<Section>("content");
  const { dragHandleProps, tileStyle } = useDraggableTile({ position, onChange: onPositionChange });

  const title = isCreate ? "New Task" : form.title?.trim() || form.existingTask?.title || "Task";
  const modeLabel = form.stepsMode ? "Pipeline" : "Prompt";

  return (
    <div
      data-canvas-tile
      style={tileStyle}
      className="flex flex-col rounded-xl border border-surface-border bg-surface shadow-xl w-[420px] max-h-[80vh] overflow-hidden"
    >
      {/* Header — drag handle */}
      <div
        {...dragHandleProps}
        className="flex flex-row items-center gap-2 px-3 py-2.5 border-b border-surface-border shrink-0 select-none bg-surface-raised/40"
      >
        <GripVertical size={14} className="text-text-dim shrink-0" />
        <span className="text-text text-[13px] font-bold flex-1 tracking-tight truncate">
          {title}
        </span>
        <span className="text-[10.5px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent/10 text-accent shrink-0">
          {modeLabel}
        </span>
      </div>

      {/* Section tabs */}
      <div className="flex flex-row items-center gap-0 px-2 pt-2 shrink-0">
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
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3">
        {section === "content" && <ContentFields form={form} promptRows={4} hideStepEditor />}
        {section === "execution" && <ExecutionFields form={form} />}
        {section === "trigger" && <TriggerFields form={form} />}
      </div>
    </div>
  );
}
