import { useState } from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { Calendar } from "lucide-react";
import type { MCKanbanCard, MCKanbanColumn } from "@/src/api/hooks/useMissionControl";
import { KanbanCardModal } from "./KanbanCardModal";
import { PRIORITY_COLORS } from "./kanbanTypes";

// ---------------------------------------------------------------------------
// TFS-style flat card
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
  const isWeb = Platform.OS === "web";

  const cardContent = (
    <>
      {/* 3px left priority bar */}
      <div
        style={{
          width: 3,
          alignSelf: "stretch",
          backgroundColor: pc.dot,
          borderRadius: "2px 0 0 2px",
          flexShrink: 0,
        }}
      />
      <div style={{ flex: 1, padding: 6, paddingLeft: 8, overflow: "hidden" }}>
        {/* Title — single line, truncated */}
        <div
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: t.text,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            lineHeight: "16px",
          }}
        >
          {card.title}
        </div>
        {/* Metadata row: priority dot + due date */}
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            marginTop: 3,
          }}
        >
          <div
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              backgroundColor: pc.dot,
              flexShrink: 0,
            }}
          />
          {card.meta.due && (
            <div
              style={{
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                gap: 2,
                fontSize: 10,
                color: t.textDim,
              }}
            >
              <Calendar size={8} color={t.textDim} />
              <span>{card.meta.due}</span>
            </div>
          )}
        </div>
      </div>
    </>
  );

  // On web: native <div> for working HTML5 drag-and-drop
  if (isWeb) {
    return (
      <>
        <div
          draggable={!!onDragStart}
          onDragStart={(e) => {
            e.dataTransfer?.setData("text/plain", card.meta.id || "");
            onDragStart?.(card.meta.id, card.channel_id, currentColumn);
          }}
          onDragEnd={() => onDragEnd?.()}
          onClick={() => setShowModal(true)}
          style={{
            display: "flex",
            flexDirection: "row",
            borderRadius: 2,
            border: `1px solid ${t.surfaceBorder}`,
            backgroundColor: t.surface,
            marginBottom: 6,
            cursor: isDragging ? "grabbing" : "grab",
            opacity: isDragging ? 0.4 : 1,
            overflow: "hidden",
            transition: "opacity 0.15s",
          }}
        >
          {cardContent}
        </div>
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

  // Native: Pressable (no drag)
  return (
    <>
      <Pressable
        onPress={() => setShowModal(true)}
        style={{
          flexDirection: "row",
          borderRadius: 2,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          backgroundColor: t.surface,
          marginBottom: 6,
          overflow: "hidden",
        }}
      >
        <View style={{ width: 3, backgroundColor: pc.dot }} />
        <View style={{ flex: 1, padding: 6, paddingLeft: 8 }}>
          <Text
            numberOfLines={1}
            style={{ fontSize: 12, fontWeight: "600", color: t.text, lineHeight: 16 }}
          >
            {card.title}
          </Text>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 3 }}>
            <View
              style={{
                width: 5,
                height: 5,
                borderRadius: 2.5,
                backgroundColor: pc.dot,
              }}
            />
            {card.meta.due && (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 2 }}>
                <Calendar size={8} color={t.textDim} />
                <Text style={{ fontSize: 10, color: t.textDim }}>{card.meta.due}</Text>
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
