/**
 * Shared types, constants, and helpers for the Kanban board.
 */
import type { MCKanbanCard, MCKanbanColumn } from "@/src/api/hooks/useMissionControl";

// ---------------------------------------------------------------------------
// Drag state
// ---------------------------------------------------------------------------
export interface DragState {
  cardId: string | null;
  channelId: string | null;
  fromColumn: string | null;
  hoverColumn: string | null;
  hoverChannelId: string | null;
}

export const EMPTY_DRAG: DragState = {
  cardId: null,
  channelId: null,
  fromColumn: null,
  hoverColumn: null,
  hoverChannelId: null,
};

// ---------------------------------------------------------------------------
// Column colors
// ---------------------------------------------------------------------------
export const COLUMN_COLORS: Record<string, string> = {
  backlog: "#6b7280",
  "in progress": "#3b82f6",
  review: "#f59e0b",
  done: "#22c55e",
};

export function columnColor(name: string): string {
  return COLUMN_COLORS[name.toLowerCase()] || "#6b7280";
}

// ---------------------------------------------------------------------------
// Priority colors
// ---------------------------------------------------------------------------
export const PRIORITY_COLORS: Record<string, { bg: string; fg: string; dot: string }> = {
  critical: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444", dot: "#ef4444" },
  high: { bg: "rgba(249,115,22,0.15)", fg: "#f97316", dot: "#f97316" },
  medium: { bg: "rgba(99,102,241,0.12)", fg: "#6366f1", dot: "#6366f1" },
  low: { bg: "rgba(107,114,128,0.10)", fg: "#9ca3af", dot: "#9ca3af" },
};

// ---------------------------------------------------------------------------
// Swimlane types + builder
// ---------------------------------------------------------------------------
export interface SwimlaneRow {
  channelId: string;
  channelName: string;
  /** columnName -> cards in that cell */
  cells: Map<string, MCKanbanCard[]>;
  totalCards: number;
}

/**
 * Pivots column-based kanban data into channel swimlane rows.
 * Each row represents a channel; each cell a column for that channel.
 */
export function buildSwimlanes(
  columns: MCKanbanColumn[],
  filterChannel: string | null,
): SwimlaneRow[] {
  // channelId -> { channelName, cells }
  const map = new Map<string, { channelName: string; cells: Map<string, MCKanbanCard[]> }>();

  for (const col of columns) {
    for (const card of col.cards) {
      if (filterChannel && card.channel_id !== filterChannel) continue;

      let entry = map.get(card.channel_id);
      if (!entry) {
        entry = { channelName: card.channel_name, cells: new Map() };
        map.set(card.channel_id, entry);
      }
      let cell = entry.cells.get(col.name);
      if (!cell) {
        cell = [];
        entry.cells.set(col.name, cell);
      }
      cell.push(card);
    }
  }

  const rows: SwimlaneRow[] = [];
  for (const [channelId, entry] of map) {
    let total = 0;
    for (const cards of entry.cells.values()) total += cards.length;
    rows.push({
      channelId,
      channelName: entry.channelName,
      cells: entry.cells,
      totalCards: total,
    });
  }

  // Sort by channel name
  rows.sort((a, b) => a.channelName.localeCompare(b.channelName));
  return rows;
}
