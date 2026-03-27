import { View, Text, Platform } from "react-native";
import { Loader2, Wrench } from "lucide-react";

// Deterministic color from string hash (same as MessageBubble)
function avatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const colors = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
    "#10b981", "#06b6d4", "#ef4444", "#e879f9",
  ];
  return colors[Math.abs(hash) % colors.length];
}

interface Props {
  content: string;
  toolCalls: { name: string; status: "running" | "done" }[];
  botName?: string;
}

export function StreamingIndicator({ content, toolCalls, botName }: Props) {
  const name = botName || "Bot";
  const letter = name[0].toUpperCase();
  const bg = avatarColor(name);

  return (
    <View style={{ flexDirection: "row", gap: 12, paddingHorizontal: 20, paddingTop: 10, paddingBottom: 4, alignSelf: "stretch" }}>
      {/* Bot avatar */}
      <View style={{ paddingTop: 2 }}>
        <View
          style={{
            width: 36,
            height: 36,
            borderRadius: 6,
            backgroundColor: bg,
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <Text style={{ color: "#fff", fontSize: 14, fontWeight: "700" }}>
            {letter}
          </Text>
        </View>
      </View>

      <View style={{ flex: 1, minWidth: 0 }}>
        {/* Name header */}
        <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <Text style={{ fontSize: 15, fontWeight: "700", color: bg }}>
            {name}
          </Text>
        </View>

        {/* Tool calls in progress */}
        {toolCalls.length > 0 && (
          <View className="mb-2 gap-1.5">
            {toolCalls.map((tc, i) => (
              <View
                key={i}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                  paddingHorizontal: 10,
                  paddingVertical: 6,
                  borderRadius: 6,
                  backgroundColor: "rgba(255,255,255,0.03)",
                  borderWidth: 1,
                  borderColor: "rgba(255,255,255,0.06)",
                  alignSelf: "flex-start",
                }}
              >
                <Wrench size={12} color={tc.status === "running" ? "#8b5cf6" : "#4ade80"} />
                <Text style={{ fontSize: 12, color: "#999", fontFamily: Platform.OS === "web" ? "'Menlo', monospace" : undefined }}>
                  {tc.name}
                </Text>
                {tc.status === "running" && (
                  <Loader2 size={10} color="#8b5cf6" />
                )}
                {tc.status === "done" && (
                  <Text style={{ fontSize: 11, color: "#4ade80" }}>done</Text>
                )}
              </View>
            ))}
          </View>
        )}

        {/* Streaming text */}
        {content ? (
          <View>
            {Platform.OS === "web" ? (
              <div style={{ fontSize: 15, lineHeight: "1.6", color: "#d1d5db" }}>
                {content}
                <span
                  style={{
                    display: "inline-block",
                    width: 2,
                    height: 17,
                    backgroundColor: "#8b5cf6",
                    marginLeft: 2,
                    verticalAlign: "text-bottom",
                    opacity: 0.8,
                    animation: "blink 1s step-end infinite",
                  }}
                />
              </div>
            ) : (
              <Text style={{ fontSize: 15, lineHeight: 22, color: "#d1d5db" }}>{content}</Text>
            )}
          </View>
        ) : toolCalls.length === 0 ? (
          /* Typing indicator dots */
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 4 }}>
            <View className="w-2 h-2 rounded-full bg-text-dim animate-pulse" />
            <View className="w-2 h-2 rounded-full bg-text-dim animate-pulse delay-150" />
            <View className="w-2 h-2 rounded-full bg-text-dim animate-pulse delay-300" />
          </View>
        ) : null}
      </View>
    </View>
  );
}
