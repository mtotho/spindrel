/**
 * DefinitionsSidebar — left rail of task definitions on the canvas page.
 *
 * v1: flat list. Click a row → opens the editor card on the canvas.
 * Spatial-positioning of definitions is parked (see Track - Automations).
 */
import { Plus, Workflow, MessageSquare } from "lucide-react";
import type { TaskItem } from "@/src/components/shared/TaskConstants";

interface DefinitionsSidebarProps {
  definitions: TaskItem[];
  loading: boolean;
  selectedTaskId: string | null;
  onSelect: (taskId: string) => void;
  onNew: () => void;
}

export function DefinitionsSidebar({
  definitions,
  loading,
  selectedTaskId,
  onSelect,
  onNew,
}: DefinitionsSidebarProps) {
  return (
    <div className="flex flex-col w-[280px] shrink-0 border-r border-surface-border bg-surface-raised/30 overflow-hidden">
      <div className="flex flex-row items-center justify-between px-3 py-3 shrink-0">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">
          Definitions
        </span>
        <button
          onClick={onNew}
          title="New Task"
          className="flex items-center justify-center w-6 h-6 rounded-md bg-transparent border-none cursor-pointer text-accent hover:bg-accent/[0.08] transition-colors"
        >
          <Plus size={14} />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-1.5 pb-3">
        {loading && (
          <div className="px-3 py-2 text-[11.5px] text-text-dim">Loading…</div>
        )}
        {!loading && definitions.length === 0 && (
          <div className="px-3 py-6 text-[11.5px] text-text-dim text-center">
            No tasks yet. Click + to create one.
          </div>
        )}
        {definitions.map((t) => {
          const isSelected = selectedTaskId === t.id;
          const isPipeline = (t.steps?.length ?? 0) > 0;
          const Icon = isPipeline ? Workflow : MessageSquare;
          const label = t.title?.trim() || t.prompt?.trim().slice(0, 60) || "(untitled)";
          return (
            <button
              key={t.id}
              onClick={() => onSelect(t.id)}
              className={`flex flex-row items-center gap-2 w-full px-2.5 py-2 text-left rounded-md border-none cursor-pointer transition-colors ${
                isSelected
                  ? "bg-accent/[0.10] text-accent"
                  : "bg-transparent text-text hover:bg-surface-overlay/45"
              }`}
            >
              <Icon size={13} className="shrink-0 opacity-70" />
              <span className="flex-1 min-w-0 truncate text-[12px] font-medium">
                {label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
