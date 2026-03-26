import { useState } from "react";
import { View, Text, Pressable } from "react-native";
import { AlertTriangle, X } from "lucide-react";

interface Props {
  behavior: "queue" | "drop";
}

export function SystemPauseBanner({ behavior }: Props) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  const description =
    behavior === "queue"
      ? "Messages will be queued and processed when unpaused."
      : "Messages are being dropped.";

  return (
    <View
      className="flex-row items-center gap-2 px-4 py-2"
      style={{ backgroundColor: "rgba(245, 158, 11, 0.15)", flexShrink: 0 }}
    >
      <AlertTriangle size={16} color="#f59e0b" />
      <Text className="text-sm flex-1" style={{ color: "#f59e0b" }}>
        System Paused — {description}
      </Text>
      <Pressable
        onPress={() => setDismissed(true)}
        className="items-center justify-center rounded-md"
        style={{ width: 28, height: 28 }}
      >
        <X size={14} color="#f59e0b" />
      </Pressable>
    </View>
  );
}
