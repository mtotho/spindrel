import { View, Text } from "react-native";
import { MobileHeader } from "@/src/components/layout/MobileHeader";

export default function SessionsScreen() {
  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Sessions" />
      <View className="p-6">
        <Text className="text-text-muted text-sm">Coming soon</Text>
      </View>
    </View>
  );
}
