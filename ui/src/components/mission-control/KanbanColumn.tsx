import { useState } from "react";
import { View, Text, Pressable, ScrollView, Platform } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { MCKanbanCard, MCKanbanColumn } from "@/src/api/hooks/useMissionControl";
import { KanbanCardView } from "./KanbanCard";

// ---------------------------------------------------------------------------
// Column colors for visual distinction
// ---------------------------------------------------------------------------
const COLUMN_COLORS: Record<string, string> = {
  backlog: "#6b7280",
  "in progress": "#3b82f6",
  review: "#f59e0b",
  done: "#22c55e",
};

function columnColor(name: string): string {
  return COLUMN_COLORS[name.toLowerCase()] || "#6b7280";
}

// ---------------------------------------------------------------------------
// Drag state type (shared via parent)
// ---------------------------------------------------------------------------
export interface DragState {
  cardId: string | null;
  channelId: string | null;
  fromColumn: string | null;
  hoverColumn: string | null;
}

// ---------------------------------------------------------------------------
// Desktop column — flex layout, drag-drop
// ---------------------------------------------------------------------------
export function KanbanColumnView({
  column,
  allColumns,
  onMove,
  onUpdate,
  moveDisabled,
  dragState,
  onDragStart,
  onDragEnd,
  onDragHover,
  onDrop,
}: {
  column: MCKanbanColumn;
  allColumns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  moveDisabled?: boolean;
  dragState?: DragState;
  onDragStart?: (cardId: string, channelId: string, fromColumn: string) => void;
  onDragEnd?: () => void;
  onDragHover?: (column: string | null) => void;
  onDrop?: (toColumn: string) => void;
}) {
  const t = useThemeTokens();
  const isWeb = Platform.OS === "web";
  const isHovered = dragState?.hoverColumn === column.name && dragState?.fromColumn !== column.name;
  const cc = columnColor(column.name);

  const dropProps = isWeb && onDrop
    ? {
        onDragOver: (e: any) => {
          e.preventDefault?.();
          onDragHover?.(column.name);
        },
        onDragLeave: () => onDragHover?.(null),
        onDrop: (e: any) => {
          e.preventDefault?.();
          onDrop(column.name);
        },
      }
    : {};

  return (
    <View
      className="bg-surface-card"
      style={{
        flex: 1,
        minWidth: 220,
        borderWidth: isHovered ? 2 : 1,
        borderColor: isHovered ? t.accent : t.surfaceBorder,
        borderRadius: 12,
        backgroundColor: isHovered ? t.accent + "08" : undefined,
        transition: "border-color 0.15s, background-color 0.15s",
      } as any}
      {...dropProps}
    >
      <View
        className="flex-row items-center justify-between px-4 py-3 border-b border-surface-border"
      >
        <View className="flex-row items-center gap-2">
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: cc,
            }}
          />
          <Text className="text-text font-semibold text-sm">{column.name}</Text>
        </View>
        <View
          className="rounded-full px-2 py-0.5"
          style={{ backgroundColor: "rgba(107,114,128,0.1)" }}
        >
          <Text className="text-text-dim text-[10px] font-semibold">
            {column.cards.length}
          </Text>
        </View>
      </View>
      <ScrollView
        style={{ maxHeight: 600, padding: 8 }}
        showsVerticalScrollIndicator={false}
      >
        {column.cards.map((card, idx) => (
          <KanbanCardView
            key={card.meta.id || `${card.channel_id}-${idx}`}
            card={card}
            currentColumn={column.name}
            columns={allColumns}
            onMove={onMove}
            onUpdate={onUpdate}
            moveDisabled={moveDisabled}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            isDragging={dragState?.cardId === card.meta.id}
          />
        ))}
        {column.cards.length === 0 && (
          <Text className="text-text-dim text-xs text-center py-4">
            No cards
          </Text>
        )}
      </ScrollView>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Collapsible Review column (thin vertical strip when collapsed)
// ---------------------------------------------------------------------------
export function KanbanReviewColumn({
  column,
  allColumns,
  onMove,
  onUpdate,
  moveDisabled,
  dragState,
  onDragStart,
  onDragEnd,
  onDragHover,
  onDrop,
}: {
  column: MCKanbanColumn;
  allColumns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  moveDisabled?: boolean;
  dragState?: DragState;
  onDragStart?: (cardId: string, channelId: string, fromColumn: string) => void;
  onDragEnd?: () => void;
  onDragHover?: (column: string | null) => void;
  onDrop?: (toColumn: string) => void;
}) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(column.cards.length > 0);
  const isHovered = dragState?.hoverColumn === column.name;
  const isWeb = Platform.OS === "web";

  // Auto-expand when dragging over
  const shouldExpand = expanded || isHovered;

  const dropProps = isWeb && onDrop
    ? {
        onDragOver: (e: any) => {
          e.preventDefault?.();
          onDragHover?.(column.name);
        },
        onDragLeave: () => onDragHover?.(null),
        onDrop: (e: any) => {
          e.preventDefault?.();
          onDrop(column.name);
        },
      }
    : {};

  if (!shouldExpand) {
    // Collapsed: thin vertical strip
    return (
      <Pressable
        onPress={() => setExpanded(true)}
        style={{
          width: 48,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          borderRadius: 12,
          backgroundColor: t.surface,
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
          paddingVertical: 16,
        } as any}
        {...dropProps}
      >
        <Text
          style={{
            fontSize: 11,
            fontWeight: "600",
            color: "#f59e0b",
            writingMode: "vertical-rl",
            textOrientation: "mixed",
            transform: [{ rotate: "180deg" }],
          } as any}
        >
          Review ({column.cards.length})
        </Text>
      </Pressable>
    );
  }

  return (
    <KanbanColumnView
      column={column}
      allColumns={allColumns}
      onMove={onMove}
      onUpdate={onUpdate}
      moveDisabled={moveDisabled}
      dragState={dragState}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragHover={onDragHover}
      onDrop={onDrop}
    />
  );
}

// ---------------------------------------------------------------------------
// Mobile accordion column
// ---------------------------------------------------------------------------
export function KanbanAccordionColumn({
  column,
  allColumns,
  onMove,
  onUpdate,
  moveDisabled,
}: {
  column: MCKanbanColumn;
  allColumns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  moveDisabled?: boolean;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(column.cards.length > 0);
  const cc = columnColor(column.name);

  return (
    <View className="rounded-xl border border-surface-border overflow-hidden bg-surface-card">
      <Pressable
        onPress={() => setOpen(!open)}
        className="flex-row items-center justify-between px-4 py-3 border-b border-surface-border hover:bg-surface-overlay"
      >
        <View className="flex-row items-center gap-2">
          {open ? (
            <ChevronDown size={14} color={t.textDim} />
          ) : (
            <ChevronRight size={14} color={t.textDim} />
          )}
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: cc,
            }}
          />
          <Text className="text-text font-semibold text-sm">{column.name}</Text>
        </View>
        <View
          className="rounded-full px-2 py-0.5"
          style={{ backgroundColor: "rgba(107,114,128,0.1)" }}
        >
          <Text className="text-text-dim text-[10px] font-semibold">
            {column.cards.length}
          </Text>
        </View>
      </Pressable>
      {open && (
        <View style={{ padding: 8 }}>
          {column.cards.map((card, idx) => (
            <KanbanCardView
              key={card.meta.id || `${card.channel_id}-${idx}`}
              card={card}
              currentColumn={column.name}
              columns={allColumns}
              onMove={onMove}
              onUpdate={onUpdate}
              moveDisabled={moveDisabled}
            />
          ))}
          {column.cards.length === 0 && (
            <Text className="text-text-dim text-xs text-center py-4">
              No cards
            </Text>
          )}
        </View>
      )}
    </View>
  );
}
