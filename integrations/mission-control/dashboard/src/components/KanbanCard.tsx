import { useDraggable } from "@dnd-kit/core";
import type { TaskCard } from "../lib/types";

const PRIORITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400",
  high: "bg-orange-500/20 text-orange-400",
  medium: "bg-blue-500/20 text-blue-400",
  low: "bg-gray-500/20 text-gray-400",
};

interface KanbanCardProps {
  card: TaskCard;
  isDragging?: boolean;
}

export default function KanbanCardView({ card, isDragging }: KanbanCardProps) {
  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: card.meta.id || card.title,
  });

  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined;

  const priority = card.meta.priority;
  const priorityClass = priority ? PRIORITY_COLORS[priority] || "" : "";
  const tags = card.meta.tags?.split(",").map((t) => t.trim()).filter(Boolean) || [];

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`bg-surface-2 rounded-lg p-3 border border-surface-3 cursor-grab active:cursor-grabbing transition-shadow ${
        isDragging ? "shadow-xl shadow-accent/10 opacity-90" : "hover:border-surface-4"
      }`}
    >
      <h4 className="text-sm font-medium text-gray-100 leading-snug">
        {card.title}
      </h4>

      {card.description && (
        <p className="text-xs text-gray-500 mt-1 line-clamp-2">
          {card.description}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-1.5 mt-2">
        {priority && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${priorityClass}`}>
            {priority}
          </span>
        )}
        {tags.map((tag) => (
          <span
            key={tag}
            className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-gray-400"
          >
            {tag}
          </span>
        ))}
      </div>

      {card.meta.assigned && (
        <p className="text-[10px] text-gray-600 mt-1.5">
          {card.meta.assigned}
        </p>
      )}
    </div>
  );
}
