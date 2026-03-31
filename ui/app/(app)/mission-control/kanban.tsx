import { useState } from "react";
import { View, Text, Pressable, ScrollView, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCKanban,
  useMCKanbanMove,
  useMCKanbanCreate,
  useMCOverview,
  useMCPrefs,
  type MCKanbanColumn,
} from "@/src/api/hooks/useMissionControl";
import { MCEmptyState } from "@/src/components/mission-control/MCEmptyState";
import { channelColor } from "@/src/components/mission-control/botColors";
import {
  KanbanColumnView,
  KanbanAccordionColumn,
} from "@/src/components/mission-control/KanbanColumn";
import { KanbanNewCardForm } from "@/src/components/mission-control/KanbanNewCardForm";
import { Plus, AlertCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCKanban() {
  const { data: prefs } = useMCPrefs();
  const scope = ((prefs?.layout_prefs as any)?.scope as "fleet" | "personal") || "fleet";
  const { data, isLoading } = useMCKanban(scope);
  const { data: overview } = useMCOverview(scope);
  const moveMutation = useMCKanbanMove();
  const createMutation = useMCKanbanCreate();
  const { refreshing, onRefresh } = usePageRefresh([["mc-kanban"]]);
  const [showNewCard, setShowNewCard] = useState(false);
  const [filterChannel, setFilterChannel] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const t = useThemeTokens();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const qc = useQueryClient();

  const handleMove = (cardId: string, channelId: string, fromColumn: string, toColumn: string) => {
    setMoveError(null);

    // Optimistic update
    qc.setQueryData<{ columns: MCKanbanColumn[] }>(
      ["mc-kanban", scope],
      (old) => {
        if (!old) return old;
        const cols = old.columns.map((col) => ({
          ...col,
          cards: [...col.cards],
        }));
        let movedCard = null;
        for (const col of cols) {
          if (col.name.toLowerCase() === fromColumn.toLowerCase()) {
            const idx = col.cards.findIndex((c) => c.meta.id === cardId);
            if (idx >= 0) {
              movedCard = col.cards.splice(idx, 1)[0];
            }
          }
        }
        if (movedCard) {
          const target = cols.find(
            (c) => c.name.toLowerCase() === toColumn.toLowerCase()
          );
          if (target) target.cards.push(movedCard);
        }
        return { columns: cols };
      }
    );

    moveMutation.mutate(
      {
        card_id: cardId,
        from_column: fromColumn,
        to_column: toColumn,
        channel_id: channelId,
      },
      {
        onError: (err: any) => {
          setMoveError(err?.message || "Failed to move card");
          qc.invalidateQueries({ queryKey: ["mc-kanban"] });
        },
      }
    );
  };

  const handleCreate = (formData: {
    channel_id: string;
    title: string;
    column: string;
    priority: string;
    description: string;
  }) => {
    setMoveError(null);
    createMutation.mutate(formData, {
      onSuccess: () => setShowNewCard(false),
      onError: (err: any) => {
        setMoveError(err?.message || "Failed to create card");
      },
    });
  };

  // Get unique channels for filter
  const channels =
    overview?.channels.map((ch) => ({ id: ch.id, name: ch.name })) || [];

  // Filter columns by channel
  const columns = (data?.columns || []).map((col) => ({
    ...col,
    cards: filterChannel
      ? col.cards.filter((c) => c.channel_id === filterChannel)
      : col.cards,
  }));

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Kanban"
        subtitle="Aggregated task board"
        right={
          <Pressable
            onPress={() => setShowNewCard(!showNewCard)}
            className="flex-row items-center gap-1.5 rounded-lg px-3 py-2 hover:bg-surface-overlay"
          >
            <Plus size={16} color={t.accent} />
            <Text style={{ fontSize: 13, color: t.accent, fontWeight: "600" }}>
              Add
            </Text>
          </Pressable>
        }
      />

      {/* Error banner */}
      {moveError && (
        <View
          className="flex-row items-center gap-2 px-4 py-2 border-b"
          style={{
            backgroundColor: "rgba(239,68,68,0.08)",
            borderColor: "rgba(239,68,68,0.2)",
          }}
        >
          <AlertCircle size={14} color="#ef4444" />
          <Text style={{ fontSize: 12, color: "#ef4444", flex: 1 }}>
            {moveError}
          </Text>
          <Pressable onPress={() => setMoveError(null)}>
            <Text style={{ fontSize: 11, color: "#ef4444", fontWeight: "600" }}>
              Dismiss
            </Text>
          </Pressable>
        </View>
      )}

      {/* Filter bar */}
      <View className="flex-row items-center gap-2 px-4 py-2 border-b border-surface-border flex-wrap">
        <Pressable
          onPress={() => setFilterChannel(null)}
          className={`rounded-full px-3 py-1 border ${
            !filterChannel ? "border-accent bg-accent/10" : "border-surface-border"
          }`}
        >
          <Text
            className={`text-xs ${!filterChannel ? "text-accent font-medium" : "text-text-muted"}`}
          >
            All
          </Text>
        </Pressable>
        {channels.map((ch) => {
          const isActive = filterChannel === ch.id;
          const cc = channelColor(ch.id);
          return (
            <Pressable
              key={ch.id}
              onPress={() => setFilterChannel(isActive ? null : ch.id)}
              className={`rounded-full px-3 py-1 border ${
                isActive ? "border-accent bg-accent/10" : "border-surface-border"
              }`}
            >
              <Text
                className={`text-xs ${isActive ? "text-accent font-medium" : "text-text-muted"}`}
              >
                {ch.name}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* New card form */}
      {showNewCard && (
        <View className="p-4 border-b border-surface-border">
          <KanbanNewCardForm
            channels={channels}
            onSubmit={handleCreate}
            onCancel={() => setShowNewCard(false)}
            isPending={createMutation.isPending}
          />
        </View>
      )}

      {/* Board */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <Text className="text-text-muted text-sm">Loading board...</Text>
        </View>
      ) : columns.length === 0 ? (
        <View style={{ padding: 16, paddingTop: 24 }}>
          <MCEmptyState feature="kanban">
            <Text className="text-text-muted text-sm">
              No task columns found. Create tasks in your channels to see them here.
            </Text>
          </MCEmptyState>
        </View>
      ) : isMobile ? (
        /* Mobile: vertical accordion layout */
        <RefreshableScrollView
          refreshing={refreshing}
          onRefresh={onRefresh}
          contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: 48 }}
          className="flex-1"
        >
          {columns.map((col) => (
            <KanbanAccordionColumn
              key={col.name}
              column={col}
              allColumns={columns}
              onMove={handleMove}
              moveDisabled={moveMutation.isPending}
            />
          ))}
        </RefreshableScrollView>
      ) : (
        /* Desktop: horizontal scroll */
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ padding: 16, gap: 12 }}
          className="flex-1"
        >
          {columns.map((col) => (
            <KanbanColumnView
              key={col.name}
              column={col}
              allColumns={columns}
              onMove={handleMove}
              moveDisabled={moveMutation.isPending}
            />
          ))}
        </ScrollView>
      )}
    </View>
  );
}
