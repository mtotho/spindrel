/**
 * Single column in the per-channel kanban board.
 * Uses @dnd-kit droppable. Cards use the shared edit modal.
 */
import { useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import type { KanbanColumn, TaskCard } from "../lib/types";
import KanbanCardView from "./KanbanCard";
import NewCardForm from "./NewCardForm";

const COLUMN_COLORS: Record<string, string> = {
  backlog: "#6b7280",
  "in progress": "#3b82f6",
  review: "#f59e0b",
  done: "#22c55e",
};

interface KanbanColumnViewProps {
  column: KanbanColumn;
  columnNames: string[];
  onMove: (cardId: string, fromCol: string, toCol: string) => void;
  onUpdate?: (cardId: string, fields: Record<string, string>) => void;
  onAddCard?: (columnName: string, card: Omit<TaskCard, "meta"> & { priority: string }) => void;
}

export default function KanbanColumnView({
  column,
  columnNames,
  onMove,
  onUpdate,
  onAddCard,
}: KanbanColumnViewProps) {
  const [showForm, setShowForm] = useState(false);
  const { setNodeRef, isOver } = useDroppable({ id: column.name });
  const borderColor = COLUMN_COLORS[column.name.toLowerCase()] || "#6b7280";

  return (
    <div
      ref={setNodeRef}
      className={`flex-shrink-0 w-72 bg-surface-1 rounded-xl flex flex-col ${
        isOver ? "ring-2 ring-accent/30" : ""
      }`}
      style={{ borderTopWidth: 2, borderTopColor: borderColor }}
    >
      <div className="px-3 py-2.5 border-b border-surface-3 flex items-center justify-between">
        <h3 className="text-xs font-semibold text-content">{column.name}</h3>
        <span className="text-[10px] font-medium text-content-dim">{column.cards.length}</span>
      </div>
      <div className="p-2 space-y-1.5 min-h-[100px] flex-1 overflow-y-auto">
        {column.cards.map((card) => (
          <KanbanCardView
            key={card.meta.id || card.title}
            card={card}
            columnName={column.name}
            columnNames={columnNames}
            onMove={onMove}
            onUpdate={onUpdate}
          />
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
