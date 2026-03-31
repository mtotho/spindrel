import { useState } from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { channelColor } from "./botColors";
import type { MCKanbanCard, MCKanbanColumn } from "@/src/api/hooks/useMissionControl";
import { KanbanCardModal } from "./KanbanCardModal";
import { Calendar } from "lucide-react";

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
// Professional Card component
// ---------------------------------------------------------------------------
export function KanbanCardView({
  card,
  currentColumn,
  columns,
  onMove,
  onUpdate,
  moveDisabled,
  onDragStart,
  onDragEnd,
  isDragging,
}: {
  card: MCKanbanCard;
  currentColumn: string;
  columns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  moveDisabled?: boolean;
  onDragStart?: (cardId: string, channelId: string, fromColumn: string) => void;
  onDragEnd?: () => void;
  isDragging?: boolean;
}) {
  const t = useThemeTokens();
  const [showModal, setShowModal] = useState(false);
  const priority = card.meta.priority || "medium";
  const pc = PRIORITY_COLORS[priority] || PRIORITY_COLORS.medium;
  const cc = channelColor(card.channel_id);
  const isWeb = Platform.OS === "web";

  const dragProps = isWeb && onDragStart
    ? {
        draggable: true,
        onDragStart: (e: any) => {
          e.dataTransfer?.setData("text/plain", card.meta.id || "");
          onDragStart(card.meta.id, card.channel_id, currentColumn);
        },
        onDragEnd: () => onDragEnd?.(),
      }
    : {};

  return (
    <>
      <Pressable
        onPress={() => setShowModal(true)}
        className="rounded-lg border border-surface-border bg-surface hover:bg-surface-overlay active:bg-surface-overlay"
        style={{
          marginBottom: 8,
          cursor: isWeb ? (isDragging ? "grabbing" : "grab") : undefined,
          opacity: isDragging ? 0.5 : 1,
          overflow: "hidden",
          flexDirection: "row",
        } as any}
        {...dragProps}
      >
        {/* Priority color bar */}
        <View
          style={{
            width: 3,
            backgroundColor: pc.dot,
            borderTopLeftRadius: 8,
            borderBottomLeftRadius: 8,
          }}
        />

        <View style={{ flex: 1, padding: 10, gap: 6 }}>
          {/* Title */}
          <Text
            className="text-text font-semibold"
            numberOfLines={2}
            style={{ fontSize: 13, lineHeight: 18 }}
          >
            {card.title}
          </Text>

          {/* Compact metadata row */}
          <View className="flex-row items-center gap-2 flex-wrap">
            {/* Priority dot */}
            <View
              style={{
                width: 6,
                height: 6,
                borderRadius: 3,
                backgroundColor: pc.dot,
              }}
            />

            {/* Channel name */}
            <Text
              style={{ fontSize: 10, color: cc, fontWeight: "600" }}
              numberOfLines={1}
            >
              {card.channel_name}
            </Text>

            {/* Due date */}
            {card.meta.due && (
              <View className="flex-row items-center gap-0.5">
                <Calendar size={9} color={t.textDim} />
                <Text style={{ fontSize: 10, color: t.textDim }}>
                  {card.meta.due}
                </Text>
              </View>
            )}

            {/* Assigned initial */}
            {card.meta.assigned && (
              <View
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: 9,
                  backgroundColor: cc + "20",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Text style={{ fontSize: 9, fontWeight: "700", color: cc }}>
                  {card.meta.assigned.charAt(0).toUpperCase()}
                </Text>
              </View>
            )}
          </View>
        </View>
      </Pressable>

      {showModal && (
        <KanbanCardModal
          card={card}
          currentColumn={currentColumn}
          columns={columns}
          onMove={onMove}
          onUpdate={onUpdate}
          onClose={() => setShowModal(false)}
          moveDisabled={moveDisabled}
        />
      )}
    </>
  );
}
