import { View, Text } from "react-native";
import { AlertTriangle } from "lucide-react";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useThemeTokens } from "@/src/theme/tokens";

export function FlushPromptOverrideWarning() {
  const t = useThemeTokens();
  const { data: bots } = useAdminBots();
  const wsFileBots =
    bots?.filter((b) => b.memory_scheme === "workspace-files") ?? [];
  if (!wsFileBots.length) return null;

  return (
    <View
      style={{
        flexDirection: "row",
        gap: 10,
        backgroundColor: "rgba(245,158,11,0.08)",
        borderWidth: 1,
        borderColor: "rgba(245,158,11,0.25)",
        borderRadius: 8,
        padding: 12,
        marginBottom: 4,
      }}
    >
      <AlertTriangle
        size={15}
        color="#f59e0b"
        style={{ marginTop: 1, flexShrink: 0 } as any}
      />
      <View style={{ flex: 1, gap: 4 }}>
        <Text style={{ fontSize: 12, fontWeight: "600", color: "#f59e0b" }}>
          Ignored by workspace-files bots
        </Text>
        <Text style={{ fontSize: 11, color: t.textMuted, lineHeight: 17 }}>
          {wsFileBots.length === bots?.length
            ? "All bots use workspace-files memory — this prompt is never used. "
            : `This prompt is ignored for ${wsFileBots.length} bot${wsFileBots.length > 1 ? "s" : ""} using workspace-files memory. `}
          Those bots use a built-in flush prompt that writes to disk instead.
        </Text>
        <View
          style={{
            flexDirection: "row",
            flexWrap: "wrap",
            gap: 4,
            marginTop: 2,
          }}
        >
          {wsFileBots.map((b) => (
            <View
              key={b.id}
              style={{
                backgroundColor: "rgba(245,158,11,0.1)",
                paddingHorizontal: 7,
                paddingVertical: 2,
                borderRadius: 4,
              }}
            >
              <Text
                style={{ fontSize: 10, fontWeight: "600", color: "#f59e0b" }}
              >
                {b.name}
              </Text>
            </View>
          ))}
        </View>
      </View>
    </View>
  );
}
