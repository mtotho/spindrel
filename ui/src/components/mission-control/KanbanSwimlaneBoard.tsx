/**
 * TFS/Azure DevOps–style CSS grid swimlane board for desktop.
 *
 * Rows = channels, columns = kanban stages.
 * Uses native <div> for working HTML5 drag-and-drop.
 */
import { useThemeTokens } from "@/src/theme/tokens";
import { channelColor } from "./botColors";
import { KanbanCardView } from "./KanbanCard";
import {
  columnColor,
  type DragState,
  type SwimlaneRow,
} from "./kanbanTypes";
import type { MCKanbanColumn } from "@/src/api/hooks/useMissionControl";

interface Props {
  columns: MCKanbanColumn[];
  swimlanes: SwimlaneRow[];
  dragState: DragState;
  onDragStart: (cardId: string, channelId: string, fromColumn: string) => void;
  onDragEnd: () => void;
  onDragHover: (column: string | null, channelId: string | null) => void;
  onDrop: (toColumn: string) => void;
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  moveDisabled?: boolean;
}

export function KanbanSwimlaneBoard({
  columns,
  swimlanes,
  dragState,
  onDragStart,
  onDragEnd,
  onDragHover,
  onDrop,
  onMove,
  onUpdate,
  moveDisabled,
}: Props) {
  const t = useThemeTokens();
  const colCount = columns.length;

  const gridTemplateColumns = `180px repeat(${colCount}, 1fr)`;

  // Column card counts
  const colCounts = columns.map((col) => col.cards.length);

  return (
    <div
      style={{
        flex: 1,
        overflow: "auto",
        position: "relative",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns,
          borderLeft: `1px solid ${t.surfaceBorder}`,
          borderTop: `1px solid ${t.surfaceBorder}`,
          minWidth: "fit-content",
        }}
      >
        {/* ── Header row ── */}
        {/* Corner cell */}
        <div
          style={{
            position: "sticky",
            top: 0,
            left: 0,
            zIndex: 3,
            backgroundColor: t.surfaceRaised,
            borderRight: `1px solid ${t.surfaceBorder}`,
            borderBottom: `1px solid ${t.surfaceBorder}`,
            padding: 8,
            display: "flex",
            alignItems: "center",
          }}
        >
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: t.textDim,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            Channel
          </span>
        </div>

        {/* Column headers */}
        {columns.map((col, ci) => {
          const cc = columnColor(col.name);
          return (
            <div
              key={col.name}
              style={{
                position: "sticky",
                top: 0,
                zIndex: 2,
                backgroundColor: t.surfaceRaised,
                borderRight: `1px solid ${t.surfaceBorder}`,
                borderBottom: `1px solid ${t.surfaceBorder}`,
                padding: "8px 10px",
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                gap: 8,
              }}
            >
              <div
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  backgroundColor: cc,
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: t.text,
                  flex: 1,
                }}
              >
                {col.name}
              </span>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: t.textDim,
                  backgroundColor: "rgba(107,114,128,0.1)",
                  borderRadius: 10,
                  padding: "1px 7px",
                }}
              >
                {colCounts[ci]}
              </span>
            </div>
          );
        })}

        {/* ── Swimlane rows ── */}
        {swimlanes.map((row) => {
          const cc = channelColor(row.channelId);
          return (
            <SwimlaneRowCells
              key={row.channelId}
              row={row}
              columns={columns}
              channelDotColor={cc}
              t={t}
              dragState={dragState}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              onDragHover={onDragHover}
              onDrop={onDrop}
              onMove={onMove}
              onUpdate={onUpdate}
              moveDisabled={moveDisabled}
            />
          );
        })}

        {/* Empty state */}
        {swimlanes.length === 0 && (
          <div
            style={{
              gridColumn: `1 / -1`,
              padding: 32,
              textAlign: "center",
              color: t.textDim,
              fontSize: 13,
              borderRight: `1px solid ${t.surfaceBorder}`,
              borderBottom: `1px solid ${t.surfaceBorder}`,
            }}
          >
            No cards to display
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single swimlane row (channel label + cells)
// ---------------------------------------------------------------------------
function SwimlaneRowCells({
  row,
  columns,
  channelDotColor,
  t,
  dragState,
  onDragStart,
  onDragEnd,
  onDragHover,
  onDrop,
  onMove,
  onUpdate,
  moveDisabled,
}: {
  row: SwimlaneRow;
  columns: MCKanbanColumn[];
  channelDotColor: string;
  t: ReturnType<typeof useThemeTokens>;
  dragState: DragState;
  onDragStart: (cardId: string, channelId: string, fromColumn: string) => void;
  onDragEnd: () => void;
  onDragHover: (column: string | null, channelId: string | null) => void;
  onDrop: (toColumn: string) => void;
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  moveDisabled?: boolean;
}) {
  return (
    <>
      {/* Channel label cell — sticky left */}
      <div
        style={{
          position: "sticky",
          left: 0,
          zIndex: 1,
          backgroundColor: t.surface,
          borderRight: `1px solid ${t.surfaceBorder}`,
          borderBottom: `1px solid ${t.surfaceBorder}`,
          padding: "8px 10px",
          display: "flex",
          flexDirection: "row",
          alignItems: "flex-start",
          gap: 6,
          minHeight: 60,
        }}
      >
        <div
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            backgroundColor: channelDotColor,
            marginTop: 3,
            flexShrink: 0,
          }}
        />
        <div style={{ overflow: "hidden" }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: t.text,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {row.channelName}
          </div>
          <div style={{ fontSize: 10, color: t.textDim, marginTop: 1 }}>
            {row.totalCards} card{row.totalCards !== 1 ? "s" : ""}
          </div>
        </div>
      </div>

      {/* Data cells */}
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
            onDragOver={(e) => {
              e.preventDefault();
              onDragHover(col.name, row.channelId);
            }}
            onDragLeave={() => onDragHover(null, null)}
            onDrop={(e) => {
              e.preventDefault();
              onDrop(col.name);
            }}
            style={{
              borderRight: `1px solid ${t.surfaceBorder}`,
              borderBottom: `1px solid ${t.surfaceBorder}`,
              padding: 8,
              minHeight: 60,
              backgroundColor: isDropTarget ? `${t.accent}0D` : "transparent",
              transition: "background-color 0.12s",
            }}
          >
            {cards.map((card, idx) => (
              <KanbanCardView
                key={card.meta.id || `${card.channel_id}-${idx}`}
                card={card}
                currentColumn={col.name}
                columns={columns}
                onMove={onMove}
                onUpdate={onUpdate}
                moveDisabled={moveDisabled}
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
                isDragging={dragState.cardId === card.meta.id}
              />
            ))}
          </div>
        );
      })}
    </>
  );
}
