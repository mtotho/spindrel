import { View, Text, Pressable, ScrollView, ActivityIndicator } from "react-native";
import { Link } from "expo-router";
import { Bot, ChevronRight } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";

export default function BotsScreen() {
  const { data, isLoading } = useBots();

  return (
    <View className="flex-1 bg-surface">
      <View className="px-6 py-4 border-b border-surface-border">
        <Text className="text-text text-xl font-bold">Bots</Text>
        <Text className="text-text-muted text-sm mt-1">
          {data?.length ?? 0} configured
        </Text>
      </View>

      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <ScrollView className="flex-1 p-4">
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
        </ScrollView>
      )}
    </View>
  );
}
