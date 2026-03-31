import { useState, useCallback } from "react";
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
  isSaving: boolean;
}

export default function KanbanBoard({ columns, onMove, isSaving }: KanbanBoardProps) {
  const [activeCard, setActiveCard] = useState<TaskCard | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const cardId = event.active.id as string;
      for (const col of columns) {
        const card = col.cards.find((c) => c.meta.id === cardId);
        if (card) {
          setActiveCard(card);
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
      const targetColName = over.id as string;

      // Find source column
      let sourceCol: string | null = null;
      for (const col of columns) {
        if (col.cards.some((c) => c.meta.id === cardId)) {
          sourceCol = col.name;
          break;
        }
      }

      if (sourceCol && sourceCol !== targetColName) {
        onMove(cardId, sourceCol, targetColName);
      }
    },
    [columns, onMove],
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
          <KanbanColumnView key={col.name} column={col} />
        ))}
      </div>
      <DragOverlay>
        {activeCard ? <KanbanCardView card={activeCard} isDragging /> : null}
      </DragOverlay>
      {isSaving && (
        <div className="fixed bottom-4 right-4 bg-accent/90 text-white text-xs px-3 py-1.5 rounded-full">
          Saving...
        </div>
      )}
    </DndContext>
  );
}
