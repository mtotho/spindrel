/**
 * Shared kanban card editor modal — used by both the aggregated
 * swimlane board and the per-channel column board.
 *
 * Always opens in edit mode. Tiptap rich editor for descriptions.
 * Segmented status control for column moves.
 */
import { useState, lazy, Suspense } from "react";
import ReactDOM from "react-dom";
import { X } from "lucide-react";
import type { TaskCard } from "../lib/types";

const TiptapEditor = lazy(() => import("./TiptapEditor"));

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COLUMN_COLORS: Record<string, string> = {
  backlog: "#6b7280",
  "in progress": "#3b82f6",
  review: "#f59e0b",
  done: "#22c55e",
};

const PRIORITY_OPTIONS = ["low", "medium", "high", "critical"];

function columnColor(name: string): string {
  return COLUMN_COLORS[name.toLowerCase()] || "#6b7280";
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CardEditModalProps {
  card: TaskCard;
  currentColumn: string;
  columnNames: string[];
  channelName?: string;
  onMove: (cardId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, fields: Record<string, string>) => void;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CardEditModal({
  card,
  currentColumn,
  columnNames,
  channelName,
  onMove,
  onUpdate,
  onClose,
}: CardEditModalProps) {
  const cardId = card.meta?.id || card.title;
  const origPriority = (card.meta?.priority || "medium").toLowerCase();

  const [title, setTitle] = useState(card.title);
  const [desc, setDesc] = useState(card.description || "");
  const [priority, setPriority] = useState(origPriority);
  const [assigned, setAssigned] = useState(card.meta?.assigned || "");
  const [tags, setTags] = useState(card.meta?.tags || "");
  const [due, setDue] = useState(card.meta?.due || "");
  const [activeColumn, setActiveColumn] = useState(currentColumn);

  const fieldsDirty =
    title !== card.title ||
    desc !== (card.description || "") ||
    priority !== origPriority ||
    assigned !== (card.meta?.assigned || "") ||
    tags !== (card.meta?.tags || "") ||
    due !== (card.meta?.due || "");
  const columnChanged = activeColumn !== currentColumn;
  const canSave = fieldsDirty || columnChanged;

  const handleSave = () => {
    if (onUpdate && fieldsDirty) {
      const fields: Record<string, string> = {};
      if (title !== card.title) fields.title = title;
      if (desc !== (card.description || "")) fields.description = desc;
      if (priority !== origPriority) fields.priority = priority;
      if (assigned !== (card.meta?.assigned || "")) fields.assigned = assigned;
      if (tags !== (card.meta?.tags || "")) fields.tags = tags;
      if (due !== (card.meta?.due || "")) fields.due = due;
      onUpdate(cardId, fields);
    }
    if (columnChanged) {
      onMove(cardId, currentColumn, activeColumn);
    }
    onClose();
  };

  const inputClass =
    "w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm text-content placeholder-content-dim focus:outline-none focus:border-accent transition-colors";

  const saveLabel =
    columnChanged && fieldsDirty
      ? "Save & move"
      : columnChanged
        ? `Move to ${activeColumn}`
        : "Save changes";

  return ReactDOM.createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/20" />
      <div
        className="relative bg-surface-1 rounded-xl shadow-2xl w-full max-w-xl mx-4 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <div className="p-6 space-y-5">
          {/* Title — underline-style input */}
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Card title"
            className="w-full text-base font-semibold text-content bg-transparent border-b border-surface-3 focus:border-accent pb-2 outline-none transition-colors"
          />

          {/* Status — segmented control */}
          <div className="flex rounded-lg overflow-hidden border border-surface-3">
            {columnNames.map((col) => {
              const isActive = col === activeColumn;
              return (
                <button
                  key={col}
                  onClick={() => setActiveColumn(col)}
                  className={`flex-1 px-3 py-2 text-xs font-medium transition-all border-r border-surface-3 last:border-r-0 ${
                    isActive ? "text-white" : "bg-surface-0 text-content-muted hover:bg-surface-2 hover:text-content"
                  }`}
                  style={isActive ? { backgroundColor: columnColor(col) } : undefined}
                >
                  {col}
                </button>
              );
            })}
          </div>

          {/* Description — tiptap rich editor */}
          <div>
            <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1.5 block font-medium">
              Description
            </label>
            <Suspense
              fallback={
                <div className="border border-surface-3 rounded-lg bg-surface-0 px-3 py-8 text-sm text-content-dim text-center">
                  Loading editor...
                </div>
              }
            >
              <TiptapEditor content={desc} onChange={setDesc} placeholder="Add a description..." />
            </Suspense>
          </div>

          {/* Meta — 2×2 grid */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block font-medium">
                Priority
              </label>
              <select value={priority} onChange={(e) => setPriority(e.target.value)} className={inputClass}>
                {PRIORITY_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block font-medium">
                Due date
              </label>
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block font-medium">
                Assigned
              </label>
              <input
                type="text"
                value={assigned}
                onChange={(e) => setAssigned(e.target.value)}
                placeholder="—"
                className={inputClass}
              />
            </div>
            <div>
              <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block font-medium">
                Tags
              </label>
              <input
                type="text"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="—"
                className={inputClass}
              />
            </div>
          </div>

          {/* Channel — only shown for aggregated boards */}
          {channelName && <div className="text-[10px] text-content-dim">{channelName}</div>}

          {/* Save */}
          {(onUpdate || columnChanged) && (
            <button
              onClick={handleSave}
              disabled={!canSave}
              className={`w-full py-2.5 text-sm font-medium rounded-lg transition-colors ${
                canSave
                  ? "bg-accent text-white hover:bg-accent-hover"
                  : "bg-surface-3 text-content-dim cursor-not-allowed"
              }`}
            >
              {saveLabel}
            </button>
          )}
        </div>

        {/* Close */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 rounded-md text-content-dim hover:text-content hover:bg-surface-2 transition-colors"
        >
          <X size={16} />
        </button>
      </div>
    </div>,
    document.body,
  );
}
