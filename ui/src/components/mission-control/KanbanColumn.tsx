import { useState } from "react";
import { View, Text, Pressable, ScrollView } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { channelColor } from "./botColors";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { MCKanbanCard, MCKanbanColumn } from "@/src/api/hooks/useMissionControl";

// ---------------------------------------------------------------------------
// Priority colors
// ---------------------------------------------------------------------------
const PRIORITY_COLORS: Record<string, { bg: string; fg: string }> = {
  critical: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444" },
  high: { bg: "rgba(249,115,22,0.15)", fg: "#f97316" },
  medium: { bg: "rgba(99,102,241,0.12)", fg: "#6366f1" },
  low: { bg: "rgba(107,114,128,0.10)", fg: "#9ca3af" },
};

// ---------------------------------------------------------------------------
// Card component
// ---------------------------------------------------------------------------
function KanbanCardView({
  card,
  currentColumn,
  columns,
  onMove,
  moveDisabled,
}: {
  card: MCKanbanCard;
  currentColumn: string;
  columns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  moveDisabled?: boolean;
}) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const priority = card.meta.priority || "medium";
  const pc = PRIORITY_COLORS[priority] || PRIORITY_COLORS.medium;
  const cc = channelColor(card.channel_id);

  return (
    <Pressable
      onPress={() => setExpanded(!expanded)}
      className="rounded-lg border border-surface-border p-3 bg-surface hover:bg-surface-overlay"
      style={{ marginBottom: 8 }}
    >
      <Text className="text-text font-medium text-sm" numberOfLines={expanded ? undefined : 2}>
        {card.title}
      </Text>

      <View className="flex-row items-center gap-2 mt-2 flex-wrap">
        {/* Priority badge */}
        <View className="rounded-full px-2 py-0.5" style={{ backgroundColor: pc.bg }}>
          <Text style={{ fontSize: 10, color: pc.fg, fontWeight: "600" }}>
            {priority}
          </Text>
        </View>

        {/* Channel tag */}
        <View
          className="rounded-full px-2 py-0.5"
          style={{ backgroundColor: `${cc}20` }}
        >
          <Text style={{ fontSize: 10, color: cc, fontWeight: "600" }} numberOfLines={1}>
            {card.channel_name}
          </Text>
        </View>

        {card.meta.assigned && (
          <Text className="text-text-dim text-[10px]">{card.meta.assigned}</Text>
        )}

        {card.meta.due && (
          <Text className="text-text-dim text-[10px]">{card.meta.due}</Text>
        )}
      </View>

      {expanded && (
        <View className="mt-3 pt-3 border-t border-surface-border">
          {card.description ? (
            <Text className="text-text-muted text-xs mb-3">{card.description}</Text>
          ) : null}

          {/* Move actions */}
          <View className="flex-row flex-wrap gap-2">
            {columns
              .filter((col) => col.name !== currentColumn)
              .map((col) => (
              <Pressable
                key={col.name}
                onPress={() => onMove(card.meta.id, card.channel_id, currentColumn, col.name)}
                className="rounded px-2 py-1 border border-surface-border hover:bg-surface-overlay"
                disabled={moveDisabled}
                style={moveDisabled ? { opacity: 0.5 } : undefined}
              >
                <Text className="text-text-muted text-[10px]">
                  {moveDisabled ? "Moving..." : `Move to ${col.name}`}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>
      )}
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Column component
// ---------------------------------------------------------------------------
export function KanbanColumnView({
  column,
  allColumns,
  onMove,
  moveDisabled,
}: {
  column: MCKanbanColumn;
  allColumns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  moveDisabled?: boolean;
}) {
  const t = useThemeTokens();
  return (
    <View
      style={{ width: 300, flexShrink: 0 }}
      className="bg-surface-card rounded-xl border border-surface-border"
    >
      <View className="flex-row items-center justify-between px-4 py-3 border-b border-surface-border">
        <Text className="text-text font-semibold text-sm">{column.name}</Text>
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
            moveDisabled={moveDisabled}
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
// Mobile accordion column
// ---------------------------------------------------------------------------
export function KanbanAccordionColumn({
  column,
  allColumns,
  onMove,
  moveDisabled,
}: {
  column: MCKanbanColumn;
  allColumns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  moveDisabled?: boolean;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(column.cards.length > 0);

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
