/**
 * Aggregated cross-channel swimlane kanban board.
 * Rows = channels, columns = stages. HTML5 drag-and-drop.
 */
import { useState, useMemo, useCallback } from "react";
import { channelColor } from "../lib/colors";
import type { AggregatedKanbanColumn, KanbanCard } from "../lib/types";
import CardEditModal from "./CardEditModal";

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

const PRIORITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#eab308",
  low: "#6b7280",
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

  const colNames = useMemo(() => columns.map((c) => c.name), [columns]);
  const colCounts = useMemo(() => columns.map((col) => col.cards.length), [columns]);

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
      <div className="border-t border-surface-3" style={{ display: "grid", gridTemplateColumns }}>
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
        {swimlanes.map((row) => (
          <SwimlaneRowCells
            key={row.channelId}
            row={row}
            columns={columns}
            channelDotColor={channelColor(row.channelId)}
            dragState={dragState}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            onDragHover={(col, ch) => setDragState((s) => ({ ...s, hoverColumn: col, hoverChannelId: ch }))}
            onDrop={handleDrop}
            onCardClick={(card, column) => setModalCard({ card, column })}
            moveDisabled={moveDisabled}
          />
        ))}

        {swimlanes.length === 0 && (
          <div className="p-8 text-center text-content-dim text-sm" style={{ gridColumn: "1 / -1" }}>
            No cards to display
          </div>
        )}
      </div>

      {/* Shared card edit modal */}
      {modalCard && (
        <CardEditModal
          card={modalCard.card}
          currentColumn={modalCard.column}
          columnNames={colNames}
          channelName={modalCard.card.channel_name}
          onMove={(cardId, from, to) => onMove(cardId, modalCard.card.channel_id, from, to)}
          onUpdate={onUpdate ? (cardId, fields) => onUpdate(cardId, modalCard.card.channel_id, fields) : undefined}
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
          <div className="text-[10px] text-content-dim mt-0.5">
            {row.totalCards} card{row.totalCards !== 1 ? "s" : ""}
          </div>
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
            onDragOver={(e) => {
              e.preventDefault();
              onDragHover(col.name, row.channelId);
            }}
            onDragLeave={() => onDragHover(null, null)}
            onDrop={(e) => {
              e.preventDefault();
              onDrop(col.name);
            }}
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
              <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: pc }} />
              <span className="text-[9px] text-content-muted">{card.meta.priority}</span>
            </>
          )}
          {card.meta?.due && <span className="text-[9px] text-content-dim">{card.meta.due}</span>}
        </div>
      </div>
    </div>
  );
}
