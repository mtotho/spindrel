/**
 * Aggregated cross-channel swimlane kanban board.
 * Rows = channels, columns = stages. HTML5 drag-and-drop.
 */
import { useState, useMemo, useCallback } from "react";
import ReactDOM from "react-dom";
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

  const gridTemplateColumns = `180px repeat(${columns.length}, 1fr)`;

  return (
    <div className="flex-1 overflow-auto relative">
      <div
        className="border-l border-t border-surface-3"
        style={{ display: "grid", gridTemplateColumns, minWidth: "fit-content" }}
      >
        {/* Header row */}
        <div className="sticky top-0 left-0 z-30 bg-surface-1 border-r border-b border-surface-3 p-2 flex items-center">
          <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Channel</span>
        </div>
        {columns.map((col, ci) => (
          <div
            key={col.name}
            className="sticky top-0 z-20 bg-surface-1 border-r border-b border-surface-3 px-2.5 py-2 flex items-center gap-2"
          >
            <span className="w-[7px] h-[7px] rounded-full flex-shrink-0" style={{ backgroundColor: columnColor(col.name) }} />
            <span className="text-xs font-semibold text-gray-200 flex-1">{col.name}</span>
            <span className="text-[10px] font-semibold text-gray-500 bg-surface-3/50 rounded-full px-1.5 py-px">
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
          <div className="border-r border-b border-surface-3 p-8 text-center text-gray-500 text-sm" style={{ gridColumn: "1 / -1" }}>
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
          <div className="text-xs font-semibold text-gray-200 truncate">{row.channelName}</div>
          <div className="text-[10px] text-gray-500 mt-0.5">{row.totalCards} card{row.totalCards !== 1 ? "s" : ""}</div>
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
      className="mb-1 rounded-md border border-surface-3 cursor-pointer hover:border-surface-4 transition-colors"
      style={{
        opacity: isDragging ? 0.4 : 1,
        borderLeftWidth: 3,
        borderLeftColor: pc.fg,
        backgroundColor: "var(--color-surface-2, #1e1e2e)",
      }}
    >
      <div className="px-2 py-1.5">
        <div className="text-xs text-gray-200 truncate">{card.title}</div>
        <div className="flex items-center gap-2 mt-0.5">
          {card.meta?.priority && (
            <span className="text-[9px] px-1.5 py-px rounded-full" style={{ backgroundColor: pc.bg, color: pc.fg }}>
              {card.meta.priority}
            </span>
          )}
          {card.meta?.due && (
            <span className="text-[9px] text-gray-500">{card.meta.due}</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card detail modal (portal)
// ---------------------------------------------------------------------------

const PRIORITY_CYCLE = ["low", "medium", "high", "critical"];

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

  const cyclePriority = () => {
    if (!onUpdate) return;
    const idx = PRIORITY_CYCLE.indexOf(priority);
    const next = PRIORITY_CYCLE[(idx + 1) % PRIORITY_CYCLE.length];
    onUpdate(cardId, card.channel_id, { priority: next });
  };

  const moveToColumn = (toCol: string) => {
    if (toCol !== currentColumn) {
      onMove(cardId, card.channel_id, currentColumn, toCol);
    }
    onClose();
  };

  return ReactDOM.createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="relative bg-surface-1 border border-surface-3 rounded-xl shadow-xl w-full max-w-md mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <div className="p-4 space-y-3">
          {/* Title */}
          <h2 className="text-sm font-semibold text-gray-100">{card.title}</h2>

          {/* Meta grid */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="text-gray-500">Status</div>
            <div className="text-gray-200">{currentColumn}</div>
            <div className="text-gray-500">Channel</div>
            <div className="text-gray-200">{card.channel_name}</div>
            <div className="text-gray-500">Priority</div>
            <button
              onClick={cyclePriority}
              className="text-left px-1.5 py-0.5 rounded-md w-fit transition-colors"
              style={{ backgroundColor: pc.bg, color: pc.fg }}
            >
              {priority}
            </button>
            {card.meta?.assigned && (
              <>
                <div className="text-gray-500">Assigned</div>
                <div className="text-gray-200">{card.meta.assigned}</div>
              </>
            )}
            {card.meta?.due && (
              <>
                <div className="text-gray-500">Due</div>
                <div className="text-gray-200">{card.meta.due}</div>
              </>
            )}
            {card.meta?.tags && (
              <>
                <div className="text-gray-500">Tags</div>
                <div className="text-gray-200">{card.meta.tags}</div>
              </>
            )}
          </div>

          {/* Description */}
          {card.description && (
            <div>
              <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Description</p>
              <p className="text-xs text-gray-300 whitespace-pre-wrap">{card.description}</p>
            </div>
          )}

          {/* Move buttons */}
          <div>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1.5">Move to</p>
            <div className="flex flex-wrap gap-1">
              {columns.map((col) => (
                <button
                  key={col.name}
                  onClick={() => moveToColumn(col.name)}
                  disabled={col.name === currentColumn}
                  className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                    col.name === currentColumn
                      ? "bg-accent/15 text-accent-hover cursor-default"
                      : "border border-surface-3 text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {col.name}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Close */}
        <button
          onClick={onClose}
          className="absolute top-2 right-2 text-gray-500 hover:text-gray-300 text-lg px-2 py-0.5 transition-colors"
        >
          &times;
        </button>
      </div>
    </div>,
    document.body,
  );
}
