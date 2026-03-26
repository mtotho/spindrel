import { View, Text, Pressable, ScrollView } from "react-native";
import { Link } from "expo-router";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import {
  MessageSquare,
  Bot,
  Activity,
  Plus,
} from "lucide-react";

export default function HomeScreen() {
  const { data: channels, isLoading: channelsLoading, error: channelsError } = useChannels();
  const { data: bots } = useBots();
  const columns = useResponsiveColumns();
  const botMap = new Map(bots?.map((b) => [b.id, b]) ?? []);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Channels"
        subtitle="Select a channel to start chatting"
        right={
          <Link href={"/channels/new" as any} asChild>
            <Pressable
              className="flex-row items-center gap-1.5 bg-accent rounded-lg"
              style={{ paddingHorizontal: 14, paddingVertical: 8 }}
            >
              <Plus size={14} color="#fff" />
              <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>New</Text>
            </Pressable>
          </Link>
        }
      />

      <ScrollView className="flex-1" contentContainerStyle={{ padding: columns === "single" ? 12 : 24 }}>
        <View className="max-w-2xl w-full mx-auto gap-6">

        {/* Channel list */}
        {channelsError ? (
          <View className="items-center py-12 gap-2">
            <Text className="text-red-400 text-sm font-semibold">Failed to load channels</Text>
            <Text className="text-text-dim text-xs text-center max-w-xs">
              {channelsError instanceof Error ? channelsError.message : "Unknown error"}
            </Text>
          </View>
        ) : channelsLoading ? (
          <View className="items-center py-12">
            <Activity size={24} color="#666666" className="animate-spin" />
          </View>
        ) : channels?.length === 0 ? (
          <View className="items-center py-12 gap-2">
            <MessageSquare size={32} color="#666666" />
            <Text className="text-text-muted">No channels yet</Text>
          </View>
        ) : (
          <View className="gap-2">
            {channels?.map((channel) => {
              const bot = botMap.get(channel.bot_id);
              return (
                <Link
                  key={channel.id}
                  href={`/channels/${channel.id}` as any}
                  asChild
                >
                  <View className="bg-surface-raised border border-surface-border rounded-lg p-4 flex-row items-center gap-4 hover:border-accent/50 cursor-pointer">
                    <View className="w-10 h-10 rounded-full bg-accent/20 items-center justify-center">
                      <MessageSquare size={20} color="#3b82f6" />
                    </View>
                    <View className="flex-1 min-w-0">
                      <Text className="text-text font-medium" numberOfLines={1}>
                        {channel.display_name || channel.name || channel.client_id}
                      </Text>
                      <View className="flex-row items-center gap-2 mt-1">
                        <Bot size={12} color="#999999" />
                        <Text className="text-text-muted text-xs">
                          {bot?.name ?? channel.bot_id}
                        </Text>
                        {(channel.integrations?.length ?? 0) > 0 ? (
                          channel.integrations!.map((b) => (
                            <Text key={b.id} className="text-text-dim text-xs bg-surface-overlay px-2 py-0.5 rounded">
                              {b.integration_type}
                            </Text>
                          ))
                        ) : channel.integration ? (
                          <Text className="text-text-dim text-xs bg-surface-overlay px-2 py-0.5 rounded">
                            {channel.integration}
                          </Text>
                        ) : null}
                      </View>
                    </View>
                  </View>
                </Link>
              );
            })}
          </View>
        )}
        </View>
      </ScrollView>
    </View>
  );
}
