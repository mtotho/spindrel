import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Link } from "expo-router";
import { Bot, ChevronRight, Plus } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { MobileHeader } from "@/src/components/layout/MobileHeader";

export default function BotsScreen() {
  const { data, isLoading } = useBots();
  const { refreshing, onRefresh } = usePageRefresh();

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Bots"
        subtitle={`${data?.length ?? 0} configured`}
        right={
          <Link href="/admin/bots/new" asChild>
            <Pressable className="flex-row items-center gap-2 bg-accent px-4 py-2 rounded-lg">
              <Plus size={14} color="#fff" />
              <Text className="text-white text-sm font-medium">New Bot</Text>
            </Pressable>
          </Link>
        }
      />

      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1 p-4">
          <View className="gap-2 max-w-3xl">
            {data?.map((bot) => (
              <Link
                key={bot.id}
                href={`/admin/bots/${bot.id}` as any}
                asChild
              >
                <Pressable className="bg-surface-raised border border-surface-border rounded-lg p-4 flex-row items-center gap-4 hover:border-accent/50">
                  <View className="w-10 h-10 rounded-full bg-accent/20 items-center justify-center">
                    <Bot size={20} color="#3b82f6" />
                  </View>
                  <View className="flex-1 min-w-0">
                    <Text className="text-text font-medium">{bot.name}</Text>
                    <Text className="text-text-muted text-xs mt-0.5">
                      {bot.model}
                    </Text>
                  </View>
                  <ChevronRight size={16} color="#666666" />
                </Pressable>
              </Link>
            ))}
          </View>
        </RefreshableScrollView>
      )}
    </View>
  );
}
