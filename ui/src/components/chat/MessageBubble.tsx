import { View, Text } from "react-native";
import type { Message } from "../../types/api";

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <View
      className={`max-w-[80%] mb-3 ${isUser ? "self-end" : "self-start"}`}
    >
      <View
        className={`rounded-2xl px-4 py-3 ${
          isUser
            ? "bg-accent rounded-br-md"
            : "bg-surface-raised border border-surface-border rounded-bl-md"
        }`}
      >
        <Text
          className={`text-sm leading-relaxed ${
            isUser ? "text-white" : "text-text"
          }`}
          selectable
        >
          {message.content}
        </Text>
      </View>
      <Text
        className={`text-[10px] text-text-dim mt-1 ${
          isUser ? "text-right" : "text-left"
        }`}
      >
        {new Date(message.created_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}
      </Text>
    </View>
  );
}
