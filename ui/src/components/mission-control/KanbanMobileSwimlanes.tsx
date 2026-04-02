/**
 * Mobile kanban layout — channel-grouped accordion.
 *
 * ▼ Channel A (5 cards)
 *   Backlog (2)
 *     [card] [card]
 *   In Progress (1)
 *     [card]
 * ▶ Channel B (3 cards)
 */
import { useState } from "react";
import { View, Text, Pressable } from "react-native";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { channelColor } from "./botColors";
import { KanbanCardView } from "./KanbanCard";
import { columnColor, type SwimlaneRow } from "./kanbanTypes";
import type { MCKanbanColumn } from "@/src/api/hooks/useMissionControl";

interface Props {
  columns: MCKanbanColumn[];
  swimlanes: SwimlaneRow[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  moveDisabled?: boolean;
}

export function KanbanMobileSwimlanes({
  columns,
  swimlanes,
  onMove,
  onUpdate,
  moveDisabled,
}: Props) {
  return (
    <View style={{ gap: 10 }}>
      {swimlanes.map((row) => (
        <ChannelAccordion
          key={row.channelId}
          row={row}
          columns={columns}
          onMove={onMove}
          onUpdate={onUpdate}
          moveDisabled={moveDisabled}
        />
      ))}
      {swimlanes.length === 0 && (
        <Text
          style={{
            textAlign: "center",
            fontSize: 13,
            color: "#6b7280",
            paddingVertical: 32,
          }}
        >
          No cards to display
        </Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Per-channel accordion
// ---------------------------------------------------------------------------
function ChannelAccordion({
  row,
  columns,
  onMove,
  onUpdate,
  moveDisabled,
}: {
  row: SwimlaneRow;
  columns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  moveDisabled?: boolean;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(true);
  const cc = channelColor(row.channelId);

  return (
    <View
      style={{
        borderWidth: 1,
        borderColor: t.surfaceBorder,
        borderRadius: 4,
        overflow: "hidden",
        backgroundColor: t.surface,
      }}
    >
      {/* Channel header */}
      <Pressable
        onPress={() => setOpen(!open)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingHorizontal: 12,
          paddingVertical: 10,
          borderBottomWidth: open ? 1 : 0,
          borderBottomColor: t.surfaceBorder,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          {open ? (
            <ChevronDown size={14} color={t.textDim} />
          ) : (
            <ChevronRight size={14} color={t.textDim} />
          )}
          <View
            style={{
              width: 7,
              height: 7,
              borderRadius: 3.5,
              backgroundColor: cc,
            }}
          />
          <Text style={{ fontSize: 13, fontWeight: "600", color: t.text }}>
            {row.channelName}
          </Text>
        </View>
        <Text style={{ fontSize: 11, color: t.textDim }}>
          {row.totalCards} card{row.totalCards !== 1 ? "s" : ""}
        </Text>
      </Pressable>

      {/* Column sub-sections */}
      {open && (
        <View style={{ padding: 8, gap: 8 }}>
          {columns.map((col) => {
            const cards = row.cells.get(col.name) || [];
            if (cards.length === 0) return null;
            const cc2 = columnColor(col.name);
            return (
              <View key={col.name} style={{ gap: 4 }}>
                {/* Column sub-header */}
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 6,
                    paddingHorizontal: 4,
                    paddingVertical: 2,
                  }}
                >
                  <View
                    style={{
                      width: 5,
                      height: 5,
                      borderRadius: 2.5,
                      backgroundColor: cc2,
                    }}
                  />
                  <Text style={{ fontSize: 11, fontWeight: "600", color: t.textDim }}>
                    {col.name}
                  </Text>
                  <Text style={{ fontSize: 10, color: t.textDim }}>
                    ({cards.length})
                  </Text>
                </View>
                {/* Cards */}
                <View style={{ paddingLeft: 4 }}>
                  {cards.map((card, idx) => (
                    <KanbanCardView
                      key={card.meta.id || `${card.channel_id}-${idx}`}
                      card={card}
                      currentColumn={col.name}
                      columns={columns}
                      onMove={onMove}
                      onUpdate={onUpdate}
                      moveDisabled={moveDisabled}
                    />
                  ))}
                </View>
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
}
