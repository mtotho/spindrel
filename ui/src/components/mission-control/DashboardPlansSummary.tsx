import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";
import { useMCPlans } from "@/src/api/hooks/useMissionControl";
import { ClipboardCheck, ArrowRight, AlertCircle } from "lucide-react";

export function DashboardPlansSummary({ scope }: { scope?: "fleet" | "personal" }) {
  const t = useThemeTokens();
  const { data } = useMCPlans(scope);
  const plans = data?.plans || [];

  if (plans.length === 0) return null;

  const counts: Record<string, number> = {};
  for (const p of plans) {
    counts[p.status] = (counts[p.status] || 0) + 1;
  }
  const draftCount = counts.draft || 0;

  return (
    <View style={{ gap: 10 }}>
      <View className="flex-row items-center gap-2">
        <ClipboardCheck size={12} color={t.textDim} />
        <Text
          className="text-text-dim"
          style={{ fontSize: 10, fontWeight: "700", letterSpacing: 0.8, textTransform: "uppercase" }}
        >
          PLANS
        </Text>
      </View>

      <View
        className="rounded-xl border border-surface-border p-3"
        style={{ gap: 8 }}
      >
        {/* Draft alert */}
        {draftCount > 0 && (
          <Link href={"/mission-control/plans" as any} asChild>
            <Pressable
              className="flex-row items-center gap-2 rounded-lg px-3 py-2"
              style={{
                backgroundColor: "rgba(245,158,11,0.1)",
                borderWidth: 1,
                borderColor: "rgba(245,158,11,0.3)",
              }}
            >
              <AlertCircle size={14} color="#f59e0b" />
              <Text style={{ fontSize: 12, fontWeight: "600", color: "#f59e0b", flex: 1 }}>
                {draftCount} plan{draftCount !== 1 ? "s" : ""} awaiting approval
              </Text>
              <ArrowRight size={12} color="#f59e0b" />
            </Pressable>
          </Link>
        )}

        {/* Status counts */}
        <View className="flex-row flex-wrap gap-3">
          {Object.entries(counts).map(([status, count]) => (
            <View key={status} className="flex-row items-center gap-1.5">
              <Text style={{ fontSize: 11, color: t.textDim, textTransform: "capitalize" }}>
                {status}:
              </Text>
              <Text style={{ fontSize: 11, fontWeight: "700", color: t.text }}>
                {count}
              </Text>
            </View>
          ))}
        </View>
      </View>

      <Link href={"/mission-control/plans" as any} asChild>
        <Pressable className="flex-row items-center gap-1 self-end">
          <Text style={{ fontSize: 11, fontWeight: "600", color: t.accent }}>
            View all plans
          </Text>
          <ArrowRight size={10} color={t.accent} />
        </Pressable>
      </Link>
    </View>
  );
}
