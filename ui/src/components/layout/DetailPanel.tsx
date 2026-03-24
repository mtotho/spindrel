import { View, Text, Pressable, ScrollView } from "react-native";
import { X } from "lucide-react";
import { useUIStore } from "../../stores/ui";

export function DetailPanel() {
  const { type, id } = useUIStore((s) => s.detailPanel);
  const closeDetail = useUIStore((s) => s.closeDetail);

  if (!type) return null;

  return (
    <View className="w-[350px] bg-surface border-l border-surface-border flex-1">
      {/* Header */}
      <View className="flex-row items-center justify-between px-4 py-3 border-b border-surface-border">
        <Text className="text-text font-medium text-sm capitalize">
          {type} Detail
        </Text>
        <Pressable onPress={closeDetail} className="p-1">
          <X size={16} color="#999999" />
        </Pressable>
      </View>

      {/* Content — will be replaced with type-specific views */}
      <ScrollView className="flex-1 p-4">
        <Text className="text-text-muted text-sm">
          {type}: {id}
        </Text>
      </ScrollView>
    </View>
  );
}
