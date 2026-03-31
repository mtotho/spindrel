import { useState } from "react";
import { View, Text, Pressable, TextInput, ActivityIndicator } from "react-native";
import { X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

const PRIORITY_COLORS: Record<string, { bg: string; fg: string }> = {
  critical: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444" },
  high: { bg: "rgba(249,115,22,0.15)", fg: "#f97316" },
  medium: { bg: "rgba(99,102,241,0.12)", fg: "#6366f1" },
  low: { bg: "rgba(107,114,128,0.10)", fg: "#9ca3af" },
};

export function KanbanNewCardForm({
  channels,
  onSubmit,
  onCancel,
  isPending,
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
  isPending?: boolean;
}) {
  const t = useThemeTokens();
  const [channelId, setChannelId] = useState(channels[0]?.id || "");
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("medium");
  const [description, setDescription] = useState("");

  const handleSubmit = () => {
    if (!title.trim() || !channelId || isPending) return;
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
        className="rounded-lg bg-accent px-4 py-2.5 items-center flex-row justify-center gap-2"
        style={{ opacity: title.trim() && !isPending ? 1 : 0.5 }}
        disabled={!title.trim() || isPending}
      >
        {isPending && <ActivityIndicator size="small" color="#fff" />}
        <Text style={{ color: "#fff", fontWeight: "600", fontSize: 13 }}>
          {isPending ? "Creating..." : "Create Card"}
        </Text>
      </Pressable>
    </View>
  );
}
