import { useDroppable } from "@dnd-kit/core";
import type { KanbanColumn } from "../lib/types";
import KanbanCardView from "./KanbanCard";

const COLUMN_COLORS: Record<string, string> = {
  backlog: "border-gray-600",
  "in progress": "border-status-blue",
  review: "border-status-yellow",
  done: "border-status-green",
};

interface KanbanColumnViewProps {
  column: KanbanColumn;
}

export default function KanbanColumnView({ column }: KanbanColumnViewProps) {
  const { setNodeRef, isOver } = useDroppable({ id: column.name });
  const borderColor = COLUMN_COLORS[column.name.toLowerCase()] || "border-surface-4";

  return (
    <div
      ref={setNodeRef}
      className={`flex-shrink-0 w-72 bg-surface-1 rounded-xl border-t-2 ${borderColor} ${
        isOver ? "ring-2 ring-accent/30" : ""
      }`}
    >
      <div className="p-3 border-b border-surface-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-200">{column.name}</h3>
        <span className="text-xs text-gray-500 bg-surface-3 px-1.5 py-0.5 rounded">
          {column.cards.length}
        </span>
      </div>
      <div className="p-2 space-y-2 min-h-[100px]">
        {column.cards.map((card) => (
          <KanbanCardView key={card.meta.id || card.title} card={card} />
        ))}
        {column.cards.length === 0 && (
          <p className="text-xs text-gray-600 text-center py-4">No tasks</p>
        )}
      </div>
    </div>
  );
}
