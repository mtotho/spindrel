import { useState, useCallback } from "react";
import { View, Text, Pressable, ScrollView, TextInput } from "react-native";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCKanban,
  useMCKanbanMove,
  useMCKanbanCreate,
  useMCOverview,
  type MCKanbanCard,
  type MCKanbanColumn,
} from "@/src/api/hooks/useMissionControl";
import {
  Plus,
  X,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Priority colors
// ---------------------------------------------------------------------------
const PRIORITY_COLORS: Record<string, { bg: string; fg: string }> = {
  critical: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444" },
  high: { bg: "rgba(249,115,22,0.15)", fg: "#f97316" },
  medium: { bg: "rgba(99,102,241,0.12)", fg: "#6366f1" },
  low: { bg: "rgba(107,114,128,0.10)", fg: "#9ca3af" },
};

// Channel colors
const CHANNEL_COLORS = [
  "#3b82f6", "#a855f7", "#ec4899", "#22c55e", "#06b6d4",
  "#6366f1", "#f43f5e", "#84cc16", "#f97316", "#eab308",
];

function channelColor(channelId: string): string {
  let hash = 0;
  for (let i = 0; i < channelId.length; i++) {
    hash = ((hash << 5) - hash + channelId.charCodeAt(i)) | 0;
  }
  return CHANNEL_COLORS[Math.abs(hash) % CHANNEL_COLORS.length];
}

// ---------------------------------------------------------------------------
// Card component
// ---------------------------------------------------------------------------
function KanbanCardView({
  card,
  currentColumn,
  columns,
  onMove,
}: {
  card: MCKanbanCard;
  currentColumn: string;
  columns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
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
              >
                <Text className="text-text-muted text-[10px]">
                  Move to {col.name}
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
function KanbanColumnView({
  column,
  allColumns,
  onMove,
}: {
  column: MCKanbanColumn;
  allColumns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
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
// New Card Form
// ---------------------------------------------------------------------------
function NewCardForm({
  channels,
  onSubmit,
  onCancel,
}: {
  channels: Array<{ id: string; name: string }>;
  onSubmit: (data: {
    channel_id: string;
    title: string;
    column: string;
    priority: string;
    description: string;
  }) => void;
  onCancel: () => void;
}) {
  const t = useThemeTokens();
  const [channelId, setChannelId] = useState(channels[0]?.id || "");
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("medium");
  const [description, setDescription] = useState("");

  const handleSubmit = () => {
    if (!title.trim() || !channelId) return;
    onSubmit({
      channel_id: channelId,
      title: title.trim(),
      column: "Backlog",
      priority,
      description,
    });
  };

  return (
    <View className="rounded-xl border border-surface-border p-4 bg-surface gap-3" style={{ maxWidth: 400 }}>
      <View className="flex-row items-center justify-between">
        <Text className="text-text font-semibold">New Card</Text>
        <Pressable onPress={onCancel}>
          <X size={16} color={t.textDim} />
        </Pressable>
      </View>

      {/* Channel selector */}
      <View className="gap-1">
        <Text className="text-text-dim text-xs">Channel</Text>
        <View className="flex-row flex-wrap gap-2">
          {channels.map((ch) => (
            <Pressable
              key={ch.id}
              onPress={() => setChannelId(ch.id)}
              className={`rounded-lg px-3 py-1.5 border ${
                channelId === ch.id
                  ? "border-accent bg-accent/10"
                  : "border-surface-border"
              }`}
            >
              <Text
                className={`text-xs ${
                  channelId === ch.id ? "text-accent font-medium" : "text-text-muted"
                }`}
              >
                {ch.name}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>

      {/* Title */}
      <View className="gap-1">
        <Text className="text-text-dim text-xs">Title</Text>
        <TextInput
          value={title}
          onChangeText={setTitle}
          placeholder="Task title..."
          placeholderTextColor={t.textDim}
          className="rounded-lg border border-surface-border px-3 py-2 text-text text-sm"
          style={{ backgroundColor: "transparent", outlineStyle: "none" } as any}
        />
      </View>

      {/* Priority */}
      <View className="gap-1">
        <Text className="text-text-dim text-xs">Priority</Text>
        <View className="flex-row gap-2">
          {["low", "medium", "high", "critical"].map((p) => {
            const pc = PRIORITY_COLORS[p];
            const isActive = priority === p;
            return (
              <Pressable
                key={p}
                onPress={() => setPriority(p)}
                className={`rounded-full px-3 py-1 border ${
                  isActive ? "border-accent" : "border-surface-border"
                }`}
                style={isActive ? { backgroundColor: pc.bg } : undefined}
              >
                <Text
                  style={{
                    fontSize: 11,
                    color: isActive ? pc.fg : t.textMuted,
                    fontWeight: isActive ? "600" : "400",
                  }}
                >
                  {p}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {/* Description */}
      <View className="gap-1">
        <Text className="text-text-dim text-xs">Description (optional)</Text>
        <TextInput
          value={description}
          onChangeText={setDescription}
          placeholder="Description..."
          placeholderTextColor={t.textDim}
          multiline
          numberOfLines={3}
          className="rounded-lg border border-surface-border px-3 py-2 text-text text-sm"
          style={{ backgroundColor: "transparent", minHeight: 60, outlineStyle: "none" } as any}
        />
      </View>

      <Pressable
        onPress={handleSubmit}
        className="rounded-lg bg-accent px-4 py-2.5 items-center"
        style={{ opacity: title.trim() ? 1 : 0.5 }}
        disabled={!title.trim()}
      >
        <Text style={{ color: "#fff", fontWeight: "600", fontSize: 13 }}>
          Create Card
        </Text>
      </Pressable>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCKanban() {
  const { data, isLoading } = useMCKanban();
  const { data: overview } = useMCOverview();
  const moveMutation = useMCKanbanMove();
  const createMutation = useMCKanbanCreate();
  const { refreshing, onRefresh } = usePageRefresh([["mc-kanban"]]);
  const [showNewCard, setShowNewCard] = useState(false);
  const [filterChannel, setFilterChannel] = useState<string | null>(null);
  const t = useThemeTokens();

  const handleMove = useCallback(
    (cardId: string, channelId: string, fromColumn: string, toColumn: string) => {
      moveMutation.mutate({
        card_id: cardId,
        from_column: fromColumn,
        to_column: toColumn,
        channel_id: channelId,
      });
    },
    [moveMutation.mutate]
  );

  const handleCreate = useCallback(
    (formData: {
      channel_id: string;
      title: string;
      column: string;
      priority: string;
      description: string;
    }) => {
      createMutation.mutate(formData, {
        onSuccess: () => setShowNewCard(false),
      });
    },
    [createMutation.mutate]
  );

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

      {/* Filter bar */}
      <View className="flex-row items-center gap-2 px-4 py-2 border-b border-surface-border">
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
          <NewCardForm
            channels={channels}
            onSubmit={handleCreate}
            onCancel={() => setShowNewCard(false)}
          />
        </View>
      )}

      {/* Board */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <Text className="text-text-muted text-sm">Loading board...</Text>
        </View>
      ) : (
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
            />
          ))}
          {columns.length === 0 && (
            <View className="items-center justify-center" style={{ width: 300 }}>
              <Text className="text-text-muted text-sm">
                No task columns found. Create tasks in your channels to see them here.
              </Text>
            </View>
          )}
        </ScrollView>
      )}
    </View>
  );
}
