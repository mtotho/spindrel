import { useState, useRef, useEffect } from "react";
import { useDraggable } from "@dnd-kit/core";
import type { TaskCard } from "../lib/types";

const PRIORITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400",
  high: "bg-orange-500/20 text-orange-400",
  medium: "bg-blue-500/20 text-blue-400",
  low: "bg-surface-4/40 text-content-muted",
};

interface KanbanCardProps {
  card: TaskCard;
  isDragging?: boolean;
}

export default function KanbanCardView({ card, isDragging }: KanbanCardProps) {
  const [expanded, setExpanded] = useState(false);
  const didDrag = useRef(false);
  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: card.meta.id || card.title,
  });

  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined;

  // Track whether a drag occurred so we don't open modal on drop
  useEffect(() => {
    if (transform && (Math.abs(transform.x) > 2 || Math.abs(transform.y) > 2)) {
      didDrag.current = true;
    }
  }, [transform]);

  const priority = card.meta.priority;
  const priorityClass = priority ? PRIORITY_COLORS[priority] || "" : "";
  const tags = card.meta.tags?.split(",").map((t) => t.trim()).filter(Boolean) || [];

  const handlePointerUp = () => {
    // Only open modal if we didn't drag
    if (!didDrag.current && !transform) {
      setExpanded(true);
    }
    didDrag.current = false;
  };

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        {...listeners}
        {...attributes}
        onPointerUp={handlePointerUp}
        className={`bg-surface-2 rounded-lg p-3 border border-surface-3 cursor-grab active:cursor-grabbing transition-shadow ${
          isDragging ? "shadow-xl shadow-accent/10 opacity-90" : "hover:border-surface-4"
        }`}
      >
        <h4 className="text-sm font-medium text-content leading-snug">
          {card.title}
        </h4>

        {card.description && (
          <p className="text-xs text-content-dim mt-1 line-clamp-2">
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
              className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-content-muted"
            >
              {tag}
            </span>
          ))}
        </div>

        {card.meta.assigned && (
          <p className="text-[10px] text-content-dim mt-1.5">
            {card.meta.assigned}
          </p>
        )}
      </div>

      {/* Detail modal */}
      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={() => setExpanded(false)}
        >
          <div
            className="bg-surface-1 rounded-xl border border-surface-3 w-full max-w-lg mx-4 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-3">
              <h3 className="text-lg font-semibold text-content pr-4">
                {card.title}
              </h3>
              <button
                onClick={() => setExpanded(false)}
                className="text-content-dim hover:text-content-muted text-lg leading-none flex-shrink-0"
              >
                ✕
              </button>
            </div>

            {/* Metadata grid */}
            <div className="grid grid-cols-2 gap-2 mb-4">
              {Object.entries(card.meta).map(([key, value]) => (
                <div key={key}>
                  <p className="text-[10px] text-content-dim uppercase tracking-wider">{key}</p>
                  <p className="text-sm text-content-muted">{value}</p>
                </div>
              ))}
            </div>

            {/* Tags */}
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-4">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-xs px-2 py-0.5 rounded bg-surface-3 text-content-muted"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}

            {/* Description */}
            {card.description && (
              <div className="bg-surface-0 rounded-lg p-3 border border-surface-3">
                <p className="text-xs text-content-dim uppercase tracking-wider mb-1">Description</p>
                <p className="text-sm text-content-muted whitespace-pre-wrap leading-relaxed">
                  {card.description}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
