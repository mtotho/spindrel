import { View, Text } from "react-native";
import { Loader2, Wrench } from "lucide-react";

interface Props {
  content: string;
  toolCalls: { name: string; status: "running" | "done" }[];
}

export function StreamingIndicator({ content, toolCalls }: Props) {
  return (
    <View className="self-start max-w-[80%] mb-3">
      {/* Tool calls in progress */}
      {toolCalls.length > 0 && (
        <View className="mb-2 gap-1">
          {toolCalls.map((tc, i) => (
            <View
              key={i}
              className="flex-row items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-overlay"
            >
              <Wrench size={12} color={tc.status === "running" ? "#3b82f6" : "#666666"} />
              <Text className="text-xs text-text-muted">{tc.name}</Text>
              {tc.status === "running" && (
                <Loader2 size={10} color="#3b82f6" />
              )}
              {tc.status === "done" && (
                <Text className="text-xs text-green-500">done</Text>
              )}
            </View>
          ))}
        </View>
      )}

      {/* Streaming text */}
      {content ? (
        <View className="bg-surface-raised border border-surface-border rounded-2xl rounded-bl-md px-4 py-3">
          <Text className="text-sm text-text leading-relaxed">{content}</Text>
          <View className="w-2 h-4 bg-accent ml-0.5 mt-0.5 opacity-75" />
        </View>
      ) : toolCalls.length === 0 ? (
        <View className="flex-row items-center gap-2 px-4 py-3">
          <View className="w-2 h-2 rounded-full bg-accent animate-pulse" />
          <View className="w-2 h-2 rounded-full bg-accent animate-pulse delay-150" />
          <View className="w-2 h-2 rounded-full bg-accent animate-pulse delay-300" />
        </View>
      ) : null}
    </View>
  );
}
