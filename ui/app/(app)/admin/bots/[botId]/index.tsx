import { View, Text, ScrollView, ActivityIndicator } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useBot } from "@/src/api/hooks/useBots";

export default function BotDetailScreen() {
  const { botId } = useLocalSearchParams<{ botId: string }>();
  const { data: bot, isLoading } = useBot(botId);

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  if (!bot) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <Text className="text-text-muted">Bot not found</Text>
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      <View className="px-6 py-4 border-b border-surface-border">
        <Text className="text-text text-xl font-bold">{bot.name}</Text>
        <Text className="text-text-muted text-sm mt-1">{bot.model}</Text>
      </View>

      <ScrollView className="flex-1 p-6">
        <View className="gap-4 max-w-3xl">
          {/* TODO: Tabbed bot editor */}
          <View className="bg-surface-raised border border-surface-border rounded-lg p-4">
            <Text className="text-text-dim text-xs font-semibold tracking-wider mb-2">
              ID
            </Text>
            <Text className="text-text text-sm font-mono">{bot.id}</Text>
          </View>

          <View className="bg-surface-raised border border-surface-border rounded-lg p-4">
            <Text className="text-text-dim text-xs font-semibold tracking-wider mb-2">
              TOOLS
            </Text>
            <Text className="text-text-muted text-sm">
              {[...bot.local_tools ?? [], ...bot.mcp_servers ?? []].join(", ") || "None"}
            </Text>
          </View>

          <View className="bg-surface-raised border border-surface-border rounded-lg p-4">
            <Text className="text-text-dim text-xs font-semibold tracking-wider mb-2">
              SKILLS
            </Text>
            <Text className="text-text-muted text-sm">
              {bot.skills?.map((s: any) => typeof s === "string" ? s : s.id).join(", ") || "None"}
            </Text>
          </View>
        </View>
      </ScrollView>
    </View>
  );
}
