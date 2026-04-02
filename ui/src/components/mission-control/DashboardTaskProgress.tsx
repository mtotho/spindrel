import { View, Text } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { useMCKanban } from "@/src/api/hooks/useMissionControl";

const COLUMN_COLORS: Record<string, string> = {
  backlog: "#6b7280",
  "in progress": "#3b82f6",
  review: "#f59e0b",
  done: "#22c55e",
};

function getColor(name: string): string {
  return COLUMN_COLORS[name.toLowerCase()] || "#6b7280";
}

export function DashboardTaskProgress({ scope }: { scope?: "fleet" | "personal" }) {
  const t = useThemeTokens();
  const { data } = useMCKanban(scope);
  const columns = data?.columns || [];

  const segments = columns
    .map((col) => ({
      name: col.name,
      count: col.cards.length,
      color: getColor(col.name),
    }))
    .filter((s) => s.count > 0);

  const total = segments.reduce((acc, s) => acc + s.count, 0);
  if (total === 0) return null;

  return (
    <View style={{ gap: 8 }}>
      <Text
        className="text-text-dim"
        style={{ fontSize: 10, fontWeight: "700", letterSpacing: 0.8, textTransform: "uppercase" }}
      >
        TASK PROGRESS
      </Text>

      {/* Stacked bar */}
      <View
        style={{
          flexDirection: "row",
          height: 10,
          borderRadius: 5,
          overflow: "hidden",
          backgroundColor: t.surfaceBorder,
        }}
      >
        {segments.map((seg) => (
          <View
            key={seg.name}
            style={{
              flex: seg.count,
              backgroundColor: seg.color,
            }}
          />
        ))}
      </View>

      {/* Legend row */}
      <View style={{ flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
        {segments.map((seg) => (
          <View key={seg.name} className="flex-row items-center gap-1.5">
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                backgroundColor: seg.color,
              }}
            />
            <Text style={{ fontSize: 10, color: t.textDim }}>
              {seg.name}
            </Text>
            <Text style={{ fontSize: 10, fontWeight: "700", color: t.text }}>
              {seg.count}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}
