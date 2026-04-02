/**
 * Aggregated cross-channel swimlane kanban board.
 * Rows = channels, columns = stages. HTML5 drag-and-drop.
 */
import { useState, useMemo, useCallback } from "react";
import ReactDOM from "react-dom";
import { X } from "lucide-react";
import { channelColor } from "../lib/colors";
import type { AggregatedKanbanColumn, KanbanCard } from "../lib/types";

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

const PRIORITY_COLORS: Record<string, { bg: string; fg: string }> = {
  critical: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444" },
  high: { bg: "rgba(249,115,22,0.15)", fg: "#f97316" },
  medium: { bg: "rgba(234,179,8,0.15)", fg: "#eab308" },
  low: { bg: "rgba(107,114,128,0.10)", fg: "#6b7280" },
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

  const gridTemplateColumns = `140px repeat(${columns.length}, 1fr)`;

  return (
    <div className="flex-1 overflow-auto relative">
      <div
        className="border-l border-t border-surface-3"
        style={{ display: "grid", gridTemplateColumns }}
      >
        {/* Header row */}
        <div className="sticky top-0 left-0 z-30 bg-surface-1 border-r border-b border-surface-3 p-2 flex items-center">
          <span className="text-[10px] font-semibold text-content-dim uppercase tracking-wider">Channel</span>
        </div>
        {columns.map((col, ci) => (
          <div
            key={col.name}
            className="sticky top-0 z-20 bg-surface-1 border-r border-b border-surface-3 px-2.5 py-2 flex items-center gap-2"
            style={{ borderTopWidth: 2, borderTopColor: columnColor(col.name) }}
          >
            <span className="text-xs font-semibold text-content flex-1">{col.name}</span>
            <span className="text-[10px] font-semibold text-content-dim bg-surface-3/50 rounded-full px-1.5 py-px">
              {colCounts[ci]}
            </span>
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
          <div className="border-r border-b border-surface-3 p-8 text-center text-content-dim text-sm" style={{ gridColumn: "1 / -1" }}>
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
      <div className="sticky left-0 z-10 bg-surface-0 border-r border-b border-surface-3 px-2.5 py-2 flex items-start gap-1.5" style={{ minHeight: 60 }}>
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
            className="border-r border-b border-surface-3 p-1.5 transition-colors"
            style={{ minHeight: 60, backgroundColor: isDropTarget ? "rgba(99,102,241,0.05)" : "transparent" }}
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
      className="mb-1 rounded-lg bg-surface-2 border border-surface-3 cursor-pointer hover:border-surface-4 transition-colors"
      style={{ opacity: isDragging ? 0.4 : 1 }}
    >
      <div className="px-2 py-1.5">
        <div className="text-xs text-content truncate">{card.title}</div>
        <div className="flex items-center gap-2 mt-0.5">
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
// Card detail modal (portal)
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
  const priority = (card.meta?.priority || "medium").toLowerCase();
  const pc = PRIORITY_COLORS[priority] || PRIORITY_COLORS.medium;

  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(card.title);
  const [editDesc, setEditDesc] = useState(card.description || "");
  const [editPriority, setEditPriority] = useState(priority);
  const [editAssigned, setEditAssigned] = useState(card.meta?.assigned || "");
  const [editTags, setEditTags] = useState(card.meta?.tags || "");
  const [editDue, setEditDue] = useState(card.meta?.due || "");

  const handleSave = () => {
    if (!onUpdate) return;
    const fields: Record<string, string> = {};
    if (editTitle !== card.title) fields.title = editTitle;
    if (editDesc !== (card.description || "")) fields.description = editDesc;
    if (editPriority !== priority) fields.priority = editPriority;
    if (editAssigned !== (card.meta?.assigned || "")) fields.assigned = editAssigned;
    if (editTags !== (card.meta?.tags || "")) fields.tags = editTags;
    if (editDue !== (card.meta?.due || "")) fields.due = editDue;
    if (Object.keys(fields).length > 0) {
      onUpdate(cardId, card.channel_id, fields);
    }
    setEditing(false);
  };

  const handleCancel = () => {
    setEditTitle(card.title);
    setEditDesc(card.description || "");
    setEditPriority(priority);
    setEditAssigned(card.meta?.assigned || "");
    setEditTags(card.meta?.tags || "");
    setEditDue(card.meta?.due || "");
    setEditing(false);
  };

  const moveToColumn = (toCol: string) => {
    if (toCol !== currentColumn) {
      onMove(cardId, card.channel_id, currentColumn, toCol);
    }
    onClose();
  };

  const inputClass = "w-full bg-surface-0 border border-surface-4 rounded px-2 py-1.5 text-xs text-content focus:outline-none focus:border-accent";

  return ReactDOM.createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="relative bg-surface-1 border border-surface-3 rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <div className="p-5 space-y-4">
          {/* Title */}
          {editing ? (
            <input
              type="text"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              className={inputClass + " text-sm font-semibold"}
            />
          ) : (
            <h2 className="text-sm font-semibold text-content pr-8">{card.title}</h2>
          )}

          {/* Description */}
          {editing ? (
            <div>
              <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block">Description</label>
              <textarea
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                rows={4}
                className={inputClass + " resize-none"}
              />
            </div>
          ) : card.description ? (
            <div>
              <p className="text-[10px] text-content-dim uppercase tracking-wider mb-1">Description</p>
              <pre className="text-xs text-content-muted whitespace-pre-wrap font-sans">{card.description}</pre>
            </div>
          ) : null}

          {/* Meta */}
          {editing ? (
            <div className="space-y-3">
              <div>
                <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block">Priority</label>
                <select
                  value={editPriority}
                  onChange={(e) => setEditPriority(e.target.value)}
                  className={inputClass}
                >
                  {PRIORITY_OPTIONS.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block">Assigned</label>
                <input type="text" value={editAssigned} onChange={(e) => setEditAssigned(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block">Tags (comma-separated)</label>
                <input type="text" value={editTags} onChange={(e) => setEditTags(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className="text-[10px] text-content-dim uppercase tracking-wider mb-1 block">Due date</label>
                <input type="date" value={editDue} onChange={(e) => setEditDue(e.target.value)} className={inputClass} />
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
              <div className="text-content-dim">Status</div>
              <div className="text-content">{currentColumn}</div>
              <div className="text-content-dim">Channel</div>
              <div className="text-content">{card.channel_name}</div>
              <div className="text-content-dim">Priority</div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: pc.fg }} />
                <span style={{ color: pc.fg }}>{priority}</span>
              </div>
              {card.meta?.assigned && (
                <>
                  <div className="text-content-dim">Assigned</div>
                  <div className="text-content">{card.meta.assigned}</div>
                </>
              )}
              {card.meta?.due && (
                <>
                  <div className="text-content-dim">Due</div>
                  <div className="text-content">{card.meta.due}</div>
                </>
              )}
              {card.meta?.tags && (
                <>
                  <div className="text-content-dim">Tags</div>
                  <div className="text-content">{card.meta.tags}</div>
                </>
              )}
            </div>
          )}

          {/* Edit / Save / Cancel buttons */}
          {editing ? (
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                className="px-3 py-1.5 text-xs rounded-md bg-accent text-white hover:bg-accent-hover transition-colors"
              >
                Save
              </button>
              <button
                onClick={handleCancel}
                className="px-3 py-1.5 text-xs rounded-md border border-surface-3 text-content-muted hover:text-content transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : onUpdate ? (
            <button
              onClick={() => setEditing(true)}
              className="px-3 py-1.5 text-xs rounded-md border border-surface-3 text-content-muted hover:text-content transition-colors"
            >
              Edit
            </button>
          ) : null}

          {/* Move buttons */}
          {!editing && (
            <div>
              <p className="text-[10px] text-content-dim uppercase tracking-wider mb-1.5">Move to</p>
              <div className="flex flex-wrap gap-1">
                {columns.map((col) => (
                  <button
                    key={col.name}
                    onClick={() => moveToColumn(col.name)}
                    disabled={col.name === currentColumn}
                    className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                      col.name === currentColumn
                        ? "bg-accent/15 text-accent-hover cursor-default"
                        : "border border-surface-3 text-content-muted hover:text-content"
                    }`}
                  >
                    {col.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Close */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 text-content-dim hover:text-content-muted transition-colors"
        >
          <X size={16} />
        </button>
      </div>
    </div>,
    document.body,
  );
}
