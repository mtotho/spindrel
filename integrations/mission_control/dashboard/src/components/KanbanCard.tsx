/**
 * Card component for the per-channel kanban column view.
 * Uses @dnd-kit draggable + shared CardEditModal.
 */
import { useState, useRef, useEffect } from "react";
import { useDraggable } from "@dnd-kit/core";
import type { TaskCard } from "../lib/types";
import CardEditModal from "./CardEditModal";

const PRIORITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#eab308",
  low: "#6b7280",
};

interface KanbanCardProps {
  card: TaskCard;
  isDragging?: boolean;
  columnName: string;
  columnNames: string[];
  onMove: (cardId: string, fromCol: string, toCol: string) => void;
  onUpdate?: (cardId: string, fields: Record<string, string>) => void;
}

export default function KanbanCardView({
  card,
  isDragging,
  columnName,
  columnNames,
  onMove,
  onUpdate,
}: KanbanCardProps) {
  const [expanded, setExpanded] = useState(false);
  const didDrag = useRef(false);
  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: card.meta.id || card.title,
  });

  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined;

  useEffect(() => {
    if (transform && (Math.abs(transform.x) > 2 || Math.abs(transform.y) > 2)) {
      didDrag.current = true;
    }
  }, [transform]);

  const priority = (card.meta.priority || "medium").toLowerCase();
  const pc = PRIORITY_COLORS[priority] || PRIORITY_COLORS.medium;

  const handlePointerUp = () => {
    if (!didDrag.current && !transform) {
      setExpanded(true);
    }
    didDrag.current = false;
  };

  return (
    <>
      <div
        ref={setNodeRef}
        style={{ ...style, opacity: isDragging ? 0.4 : 1 }}
        {...listeners}
        {...attributes}
        onPointerUp={handlePointerUp}
        className={`rounded-lg bg-surface-0 shadow-sm cursor-grab active:cursor-grabbing transition-shadow ${
          isDragging ? "shadow-lg" : "hover:shadow"
        }`}
      >
        <div className="px-2.5 py-2">
          <div className="text-xs text-content leading-snug">{card.title}</div>
          {card.description && (
            <p className="text-[10px] text-content-dim mt-1 line-clamp-2">{card.description}</p>
          )}
          <div className="flex items-center gap-2 mt-1">
            {card.meta.priority && (
              <>
                <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: pc }} />
                <span className="text-[9px] text-content-muted">{card.meta.priority}</span>
              </>
            )}
            {card.meta.due && <span className="text-[9px] text-content-dim">{card.meta.due}</span>}
            {card.meta.assigned && (
              <span className="text-[9px] text-content-dim ml-auto">{card.meta.assigned}</span>
            )}
          </div>
        </div>
      </div>

      {/* Shared edit modal */}
      {expanded && (
        <CardEditModal
          card={card}
          currentColumn={columnName}
          columnNames={columnNames}
          onMove={onMove}
          onUpdate={onUpdate}
          onClose={() => setExpanded(false)}
        />
      )}
    </>
  );
}
