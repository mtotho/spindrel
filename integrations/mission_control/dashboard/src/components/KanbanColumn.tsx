import { useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import type { KanbanColumn, TaskCard } from "../lib/types";
import KanbanCardView from "./KanbanCard";
import NewCardForm from "./NewCardForm";

const COLUMN_COLORS: Record<string, string> = {
  backlog: "border-surface-4",
  "in progress": "border-status-blue",
  review: "border-status-yellow",
  done: "border-status-green",
};

interface KanbanColumnViewProps {
  column: KanbanColumn;
  onAddCard?: (columnName: string, card: Omit<TaskCard, "meta"> & { priority: string }) => void;
}

export default function KanbanColumnView({ column, onAddCard }: KanbanColumnViewProps) {
  const [showForm, setShowForm] = useState(false);
  const { setNodeRef, isOver } = useDroppable({ id: column.name });
  const borderColor = COLUMN_COLORS[column.name.toLowerCase()] || "border-surface-4";

  return (
    <div
      ref={setNodeRef}
      className={`flex-shrink-0 w-72 bg-surface-1 rounded-xl border-t-2 flex flex-col ${borderColor} ${
        isOver ? "ring-2 ring-accent/30" : ""
      }`}
    >
      <div className="p-3 border-b border-surface-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-content">{column.name}</h3>
        <span className="text-xs text-content-dim bg-surface-3 px-1.5 py-0.5 rounded">
          {column.cards.length}
        </span>
      </div>
      <div className="p-2 space-y-2 min-h-[100px] flex-1 overflow-y-auto">
        {column.cards.map((card) => (
          <KanbanCardView key={card.meta.id || card.title} card={card} />
        ))}
        {column.cards.length === 0 && !showForm && (
          <p className="text-xs text-content-dim text-center py-4">Drop tasks here</p>
        )}
      </div>
      {/* Add card section */}
      <div className="p-2 border-t border-surface-3">
        {showForm ? (
          <NewCardForm
            columnName={column.name}
            onSubmit={(data) => {
              onAddCard?.(column.name, {
                title: data.title,
                description: data.description,
                priority: data.priority,
              });
              setShowForm(false);
            }}
            onCancel={() => setShowForm(false)}
          />
        ) : (
          <button
            onClick={() => setShowForm(true)}
            className="w-full text-left px-2 py-1.5 text-xs text-content-dim hover:text-content-muted hover:bg-surface-2 rounded transition-colors"
          >
            + Add card
          </button>
        )}
      </div>
    </div>
  );
}
