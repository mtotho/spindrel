/**
 * Per-channel kanban board with @dnd-kit drag-and-drop.
 * Uses shared CardEditModal and consistent card styling.
 */
import { useState, useCallback, useMemo } from "react";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import type { KanbanColumn, TaskCard } from "../lib/types";
import KanbanColumnView from "./KanbanColumn";
import KanbanCardView from "./KanbanCard";

interface KanbanBoardProps {
  columns: KanbanColumn[];
  onMove: (cardId: string, fromCol: string, toCol: string) => void;
  onUpdate?: (cardId: string, fields: Record<string, string>) => void;
  onAddCard?: (columnName: string, card: { title: string; priority: string; description: string }) => void;
  isSaving: boolean;
}

export default function KanbanBoard({ columns, onMove, onUpdate, onAddCard, isSaving }: KanbanBoardProps) {
  const [activeCard, setActiveCard] = useState<{ card: TaskCard; column: string } | null>(null);
  const columnNames = useMemo(() => columns.map((c) => c.name), [columns]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const cardId = event.active.id as string;
      for (const col of columns) {
        const card = col.cards.find((c) => (c.meta.id || c.title) === cardId);
        if (card) {
          setActiveCard({ card, column: col.name });
          break;
        }
      }
    },
    [columns],
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveCard(null);
      const { active, over } = event;
      if (!over) return;

      const cardId = active.id as string;
      const overId = over.id as string;

      // Resolve target column
      let targetColName: string | null = null;
      if (columnNames.includes(overId)) {
        targetColName = overId;
      } else {
        for (const col of columns) {
          if (col.cards.some((c) => (c.meta.id || c.title) === overId)) {
            targetColName = col.name;
            break;
          }
        }
      }
      if (!targetColName) return;

      // Find source column
      let sourceCol: string | null = null;
      for (const col of columns) {
        if (col.cards.some((c) => (c.meta.id || c.title) === cardId)) {
          sourceCol = col.name;
          break;
        }
      }

      if (sourceCol && sourceCol !== targetColName) {
        onMove(cardId, sourceCol, targetColName);
      }
    },
    [columns, columnNames, onMove],
  );

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="flex gap-4 overflow-x-auto pb-4 min-h-[400px]">
        {columns.map((col) => (
          <KanbanColumnView
            key={col.name}
            column={col}
            columnNames={columnNames}
            onMove={onMove}
            onUpdate={onUpdate}
            onAddCard={onAddCard}
          />
        ))}
      </div>
      <DragOverlay>
        {activeCard ? (
          <KanbanCardView
            card={activeCard.card}
            isDragging
            columnName={activeCard.column}
            columnNames={columnNames}
            onMove={onMove}
          />
        ) : null}
      </DragOverlay>
      {isSaving && (
        <div className="fixed bottom-4 right-4 bg-accent/90 text-white text-xs px-3 py-1.5 rounded-full animate-pulse">
          Saving...
        </div>
      )}
    </DndContext>
  );
}
