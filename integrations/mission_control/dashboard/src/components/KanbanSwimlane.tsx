/**
 * Aggregated cross-channel swimlane kanban board.
 * Rows = channels, columns = stages. HTML5 drag-and-drop.
 */
import { useState, useMemo, useCallback, lazy, Suspense } from "react";
import ReactDOM from "react-dom";
import { X } from "lucide-react";
import { channelColor } from "../lib/colors";
import type { AggregatedKanbanColumn, KanbanCard } from "../lib/types";

const TiptapEditor = lazy(() => import("./TiptapEditor"));

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DragState {
  cardId: string | null;
  channelId: string | null;
  fromColumn: string | null;
  hoverColumn: string | null;
  hoverChannelId: string | null;
}

interface SwimlaneRow {
  channelId: string;
  channelName: string;
  cells: Map<string, KanbanCard[]>;
  totalCards: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COLUMN_COLORS: Record<string, string> = {
  backlog: "#6b7280",
  "in progress": "#3b82f6",
  review: "#f59e0b",
  done: "#22c55e",
};

const PRIORITY_COLORS: Record<string, { fg: string }> = {
  critical: { fg: "#ef4444" },
  high: { fg: "#f97316" },
  medium: { fg: "#eab308" },
  low: { fg: "#6b7280" },
};

function columnColor(name: string): string {
  return COLUMN_COLORS[name.toLowerCase()] || "#6b7280";
}

// ---------------------------------------------------------------------------
// Build swimlanes from aggregated columns
// ---------------------------------------------------------------------------

function buildSwimlanes(columns: AggregatedKanbanColumn[]): SwimlaneRow[] {
  const rowMap = new Map<string, SwimlaneRow>();
  for (const col of columns) {
    for (const card of col.cards) {
      let row = rowMap.get(card.channel_id);
      if (!row) {
        row = {
          channelId: card.channel_id,
          channelName: card.channel_name,
          cells: new Map(),
          totalCards: 0,
        };
        rowMap.set(card.channel_id, row);
      }
      if (!row.cells.has(col.name)) row.cells.set(col.name, []);
      row.cells.get(col.name)!.push(card);
      row.totalCards++;
    }
  }
  return Array.from(rowMap.values()).sort((a, b) =>
    a.channelName.localeCompare(b.channelName),
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface KanbanSwimlaneProps {
  columns: AggregatedKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  moveDisabled?: boolean;
  channelFilter?: string | null;
}

export default function KanbanSwimlane({
  columns,
  onMove,
  onUpdate,
  moveDisabled,
  channelFilter,
}: KanbanSwimlaneProps) {
  const [dragState, setDragState] = useState<DragState>({
    cardId: null,
    channelId: null,
    fromColumn: null,
    hoverColumn: null,
    hoverChannelId: null,
  });
  const [modalCard, setModalCard] = useState<{ card: KanbanCard; column: string } | null>(null);

  const allSwimlanes = useMemo(() => buildSwimlanes(columns), [columns]);
  const swimlanes = useMemo(
    () => (channelFilter ? allSwimlanes.filter((r) => r.channelId === channelFilter) : allSwimlanes),
    [allSwimlanes, channelFilter],
  );

  const colCounts = useMemo(
    () => columns.map((col) => col.cards.length),
    [columns],
  );

  const handleDragStart = useCallback(
    (cardId: string, channelId: string, fromColumn: string) => {
      setDragState({ cardId, channelId, fromColumn, hoverColumn: null, hoverChannelId: null });
    },
    [],
  );

  const handleDragEnd = useCallback(() => {
    setDragState({ cardId: null, channelId: null, fromColumn: null, hoverColumn: null, hoverChannelId: null });
  }, []);

  const handleDrop = useCallback(
    (toColumn: string) => {
      if (dragState.cardId && dragState.channelId && dragState.fromColumn && dragState.fromColumn !== toColumn) {
        onMove(dragState.cardId, dragState.channelId, dragState.fromColumn, toColumn);
      }
      handleDragEnd();
    },
    [dragState, onMove, handleDragEnd],
  );

  const gridTemplateColumns = `160px repeat(${columns.length}, 1fr)`;

  return (
    <div className="flex-1 overflow-auto">
      <div
        className="border-t border-surface-3"
        style={{ display: "grid", gridTemplateColumns }}
      >
        {/* Header row */}
        <div className="sticky top-0 left-0 z-30 bg-surface-0 border-b border-surface-3 px-4 py-2.5 flex items-center">
          <span className="text-[10px] font-semibold text-content-dim uppercase tracking-wider">Channel</span>
        </div>
        {columns.map((col, ci) => (
          <div
            key={col.name}
            className="sticky top-0 z-20 bg-surface-0 border-b border-l border-surface-3 px-3 py-2.5 flex items-center gap-2"
            style={{ borderTopWidth: 2, borderTopColor: columnColor(col.name) }}
          >
            <span className="text-xs font-semibold text-content flex-1">{col.name}</span>
            <span className="text-[10px] font-medium text-content-dim">{colCounts[ci]}</span>
          </div>
        ))}

        {/* Swimlane rows */}
        {swimlanes.map((row) => {
          const cc = channelColor(row.channelId);
          return (
            <SwimlaneRowCells
              key={row.channelId}
              row={row}
              columns={columns}
              channelDotColor={cc}
              dragState={dragState}
              onDragStart={handleDragStart}
              onDragEnd={handleDragEnd}
              onDragHover={(col, ch) => setDragState((s) => ({ ...s, hoverColumn: col, hoverChannelId: ch }))}
              onDrop={handleDrop}
              onCardClick={(card, column) => setModalCard({ card, column })}
              moveDisabled={moveDisabled}
            />
          );
        })}

        {swimlanes.length === 0 && (
          <div className="p-8 text-center text-content-dim text-sm" style={{ gridColumn: "1 / -1" }}>
            No cards to display
          </div>
        )}
      </div>

      {/* Card detail modal */}
      {modalCard && (
        <CardModal
          card={modalCard.card}
          currentColumn={modalCard.column}
          columns={columns}
          onMove={onMove}
          onUpdate={onUpdate}
          onClose={() => setModalCard(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Swimlane row
// ---------------------------------------------------------------------------

function SwimlaneRowCells({
  row,
  columns,
  channelDotColor,
  dragState,
  onDragStart,
  onDragEnd,
  onDragHover,
  onDrop,
  onCardClick,
  moveDisabled,
}: {
  row: SwimlaneRow;
  columns: AggregatedKanbanColumn[];
  channelDotColor: string;
  dragState: DragState;
  onDragStart: (cardId: string, channelId: string, fromColumn: string) => void;
  onDragEnd: () => void;
  onDragHover: (col: string | null, ch: string | null) => void;
  onDrop: (toColumn: string) => void;
  onCardClick: (card: KanbanCard, column: string) => void;
  moveDisabled?: boolean;
}) {
  return (
    <>
      {/* Channel label */}
      <div className="sticky left-0 z-10 bg-surface-0 border-b border-surface-3 px-4 py-2.5 flex items-start gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1" style={{ backgroundColor: channelDotColor }} />
        <div className="overflow-hidden">
          <div className="text-xs font-semibold text-content truncate">{row.channelName}</div>
          <div className="text-[10px] text-content-dim mt-0.5">{row.totalCards} card{row.totalCards !== 1 ? "s" : ""}</div>
        </div>
      </div>

      {/* Cells */}
      {columns.map((col) => {
        const cards = row.cells.get(col.name) || [];
        const isDropTarget =
          dragState.cardId !== null &&
          dragState.hoverColumn === col.name &&
          dragState.hoverChannelId === row.channelId &&
          dragState.fromColumn !== col.name;

        return (
          <div
            key={col.name}
            className="border-b border-l border-surface-3 px-2 py-2 transition-colors"
            style={{ backgroundColor: isDropTarget ? "rgba(99,102,241,0.08)" : undefined }}
            onDragOver={(e) => { e.preventDefault(); onDragHover(col.name, row.channelId); }}
            onDragLeave={() => onDragHover(null, null)}
            onDrop={(e) => { e.preventDefault(); onDrop(col.name); }}
          >
            {cards.map((card, idx) => {
              const cardId = card.meta?.id || card.title;
              return (
                <SwimlaneCard
                  key={cardId || idx}
                  card={card}
                  cardId={cardId}
                  columnName={col.name}
                  onDragStart={onDragStart}
                  onDragEnd={onDragEnd}
                  onClick={() => onCardClick(card, col.name)}
                  isDragging={dragState.cardId === cardId}
                  moveDisabled={moveDisabled}
                />
              );
            })}
          </div>
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Card in swimlane
// ---------------------------------------------------------------------------

function SwimlaneCard({
  card,
  cardId,
  columnName,
  onDragStart,
  onDragEnd,
  onClick,
  isDragging,
  moveDisabled,
}: {
  card: KanbanCard;
  cardId: string;
  columnName: string;
  onDragStart: (cardId: string, channelId: string, fromColumn: string) => void;
  onDragEnd: () => void;
  onClick: () => void;
  isDragging: boolean;
  moveDisabled?: boolean;
}) {
  const priority = (card.meta?.priority || "medium").toLowerCase();
  const pc = PRIORITY_COLORS[priority] || PRIORITY_COLORS.medium;

  return (
    <div
      draggable={!moveDisabled}
      onDragStart={() => onDragStart(cardId, card.channel_id, columnName)}
      onDragEnd={onDragEnd}
      onClick={onClick}
      className="mb-1.5 rounded-lg bg-surface-0 shadow-sm cursor-pointer hover:shadow transition-shadow"
      style={{ opacity: isDragging ? 0.4 : 1 }}
    >
      <div className="px-2.5 py-2">
        <div className="text-xs text-content leading-snug">{card.title}</div>
        <div className="flex items-center gap-2 mt-1">
          {card.meta?.priority && (
            <>
              <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: pc.fg }} />
              <span className="text-[9px] text-content-muted">{card.meta.priority}</span>
            </>
          )}
          {card.meta?.due && (
            <span className="text-[9px] text-content-dim">{card.meta.due}</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card editor modal (portal) — always editable, tiptap description
// ---------------------------------------------------------------------------

const PRIORITY_OPTIONS = ["low", "medium", "high", "critical"];

function CardModal({
  card,
  currentColumn,
  columns,
  onMove,
  onUpdate,
  onClose,
}: {
  card: KanbanCard;
  currentColumn: string;
  columns: AggregatedKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  onClose: () => void;
}) {
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
      onUpdate(cardId, card.channel_id, fields);
    }
    if (columnChanged) {
      onMove(cardId, card.channel_id, currentColumn, activeColumn);
    }
    onClose();
  };

  const inputClass =
    "w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm text-content placeholder-content-dim focus:outline-none focus:border-accent transition-colors";

  const saveLabel = columnChanged && fieldsDirty
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
            {columns.map((col) => {
              const isActive = col.name === activeColumn;
              return (
                <button
                  key={col.name}
                  onClick={() => setActiveColumn(col.name)}
                  className={`flex-1 px-3 py-2 text-xs font-medium transition-all border-r border-surface-3 last:border-r-0 ${
                    isActive ? "text-white" : "bg-surface-0 text-content-muted hover:bg-surface-2 hover:text-content"
                  }`}
                  style={isActive ? { backgroundColor: columnColor(col.name) } : undefined}
                >
                  {col.name}
                </button>
              );
            })}
          </div>

          {/* Description — tiptap rich editor */}
          <div>
            <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1.5 block font-medium">
              Description
            </label>
            <Suspense fallback={<div className="border border-surface-3 rounded-lg bg-surface-0 px-3 py-8 text-sm text-content-dim text-center">Loading editor...</div>}>
              <TiptapEditor
                content={desc}
                onChange={setDesc}
                placeholder="Add a description..."
              />
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
                  <option key={p} value={p}>{p}</option>
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
              <input type="text" value={assigned} onChange={(e) => setAssigned(e.target.value)} placeholder="—" className={inputClass} />
            </div>
            <div>
              <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block font-medium">
                Tags
              </label>
              <input type="text" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="—" className={inputClass} />
            </div>
          </div>

          {/* Channel — subtle info */}
          <div className="text-[10px] text-content-dim">{card.channel_name}</div>

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
