import { useState, useMemo } from "react";
import { View, Text, Pressable, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCKanban,
  useMCKanbanMove,
  useMCKanbanCreate,
  useMCKanbanUpdate,
  useMCOverview,
  useMCPrefs,
  type MCKanbanColumn,
} from "@/src/api/hooks/useMissionControl";
import { MCEmptyState } from "@/src/components/mission-control/MCEmptyState";
import { ChannelFilterBar } from "@/src/components/mission-control/ChannelFilterBar";
import { KanbanNewCardForm } from "@/src/components/mission-control/KanbanNewCardForm";
import { KanbanSwimlaneBoard } from "@/src/components/mission-control/KanbanSwimlaneBoard";
import { KanbanMobileSwimlanes } from "@/src/components/mission-control/KanbanMobileSwimlanes";
import { buildSwimlanes, EMPTY_DRAG, type DragState } from "@/src/components/mission-control/kanbanTypes";
import { Plus, AlertCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Column ordering
// ---------------------------------------------------------------------------
function orderColumns(columns: MCKanbanColumn[]): MCKanbanColumn[] {
  const byName = new Map(columns.map((c) => [c.name.toLowerCase(), c]));
  const ordered: MCKanbanColumn[] = [];

  const backlog = byName.get("backlog");
  if (backlog) ordered.push(backlog);

  const inProgress = byName.get("in progress");
  if (inProgress) ordered.push(inProgress);

  const review = byName.get("review");
  if (review) ordered.push(review);

  const done = byName.get("done");
  if (done) ordered.push(done);

  for (const col of columns) {
    const lc = col.name.toLowerCase();
    if (!["backlog", "in progress", "review", "done"].includes(lc)) {
      ordered.push(col);
    }
  }

  return ordered;
}

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
  const updateMutation = useMCKanbanUpdate();
  const { refreshing, onRefresh } = usePageRefresh([["mc-kanban"]]);
  const [showNewCard, setShowNewCard] = useState(false);
  const [filterChannel, setFilterChannel] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [dragState, setDragState] = useState<DragState>({ ...EMPTY_DRAG });
  const t = useThemeTokens();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const qc = useQueryClient();

  // Ordered columns (full, unfiltered — needed for column list)
  const columns = useMemo(() => orderColumns(data?.columns || []), [data?.columns]);

  // Swimlane rows (filtered by channel if set)
  const swimlanes = useMemo(
    () => buildSwimlanes(columns, filterChannel),
    [columns, filterChannel],
  );

  // Handlers
  const handleMove = (cardId: string, channelId: string, fromColumn: string, toColumn: string) => {
    setMoveError(null);
    // Optimistic update
    qc.setQueryData<{ columns: MCKanbanColumn[] }>(
      ["mc-kanban", scope],
      (old) => {
        if (!old) return old;
        const cols = old.columns.map((col) => ({ ...col, cards: [...col.cards] }));
        let movedCard = null;
        for (const col of cols) {
          if (col.name.toLowerCase() === fromColumn.toLowerCase()) {
            const idx = col.cards.findIndex((c) => c.meta.id === cardId);
            if (idx >= 0) movedCard = col.cards.splice(idx, 1)[0];
          }
        }
        if (movedCard) {
          const target = cols.find((c) => c.name.toLowerCase() === toColumn.toLowerCase());
          if (target) target.cards.push(movedCard);
        }
        return { columns: cols };
      },
    );
    moveMutation.mutate(
      { card_id: cardId, from_column: fromColumn, to_column: toColumn, channel_id: channelId },
      {
        onError: (err: any) => {
          setMoveError(err?.message || "Failed to move card");
          qc.invalidateQueries({ queryKey: ["mc-kanban"] });
        },
      },
    );
  };

  const handleUpdate = (cardId: string, channelId: string, fields: Record<string, string>) => {
    updateMutation.mutate(
      { card_id: cardId, channel_id: channelId, ...fields },
      { onError: (err: any) => setMoveError(err?.message || "Failed to update card") },
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
      onError: (err: any) => setMoveError(err?.message || "Failed to create card"),
    });
  };

  // Drag handlers
  const handleDragStart = (cardId: string, channelId: string, fromColumn: string) => {
    setDragState({ cardId, channelId, fromColumn, hoverColumn: null, hoverChannelId: null });
  };
  const handleDragEnd = () => setDragState({ ...EMPTY_DRAG });
  const handleDragHover = (column: string | null, channelId: string | null) => {
    setDragState((prev) => ({ ...prev, hoverColumn: column, hoverChannelId: channelId }));
  };
  const handleDrop = (toColumn: string) => {
    if (dragState.cardId && dragState.channelId && dragState.fromColumn) {
      if (dragState.fromColumn.toLowerCase() !== toColumn.toLowerCase()) {
        handleMove(dragState.cardId, dragState.channelId, dragState.fromColumn, toColumn);
      }
    }
    handleDragEnd();
  };

  const channels = overview?.channels.map((ch) => ({ id: ch.id, name: ch.name })) || [];

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
            <Text style={{ fontSize: 13, color: t.accent, fontWeight: "600" }}>Add</Text>
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
          <Text style={{ fontSize: 12, color: "#ef4444", flex: 1 }}>{moveError}</Text>
          <Pressable onPress={() => setMoveError(null)}>
            <Text style={{ fontSize: 11, color: "#ef4444", fontWeight: "600" }}>Dismiss</Text>
          </Pressable>
        </View>
      )}

      {/* Filter bar */}
      <View
        className="flex-row items-center gap-2 border-b border-surface-border flex-wrap"
        style={{ paddingHorizontal: 8, paddingVertical: 6 }}
      >
        <ChannelFilterBar
          channels={channels}
          value={filterChannel}
          onChange={setFilterChannel}
        />
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
        <RefreshableScrollView
          refreshing={refreshing}
          onRefresh={onRefresh}
          contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 48 }}
          className="flex-1"
        >
          <KanbanMobileSwimlanes
            columns={columns}
            swimlanes={swimlanes}
            onMove={handleMove}
            onUpdate={handleUpdate}
            moveDisabled={moveMutation.isPending}
          />
        </RefreshableScrollView>
      ) : (
        <KanbanSwimlaneBoard
          columns={columns}
          swimlanes={swimlanes}
          dragState={dragState}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragHover={handleDragHover}
          onDrop={handleDrop}
          onMove={handleMove}
          onUpdate={handleUpdate}
          moveDisabled={moveMutation.isPending}
        />
      )}
    </View>
  );
}
