/**
 * Smart empty state for Mission Control pages.
 *
 * Distinguishes "not configured" (issues exist) from "configured but empty"
 * (no data yet). Shows actionable guidance with links to fix pages.
 */
import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import { AlertTriangle, ArrowRight, CheckCircle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCReadiness,
  type MCFeatureReadiness,
} from "@/src/api/hooks/useMissionControl";

type FeatureKey = "dashboard" | "kanban" | "journal" | "memory" | "timeline" | "plans";

const FIX_LINKS: Record<string, { href: string; label: string }> = {
  "channel settings": { href: "/admin/channels", label: "Go to Channels" },
  "bot YAML": { href: "/admin/bots", label: "Go to Bots" },
};

function guessFixLink(issue: string): { href: string; label: string } | null {
  for (const [keyword, link] of Object.entries(FIX_LINKS)) {
    if (issue.toLowerCase().includes(keyword)) return link;
  }
  return null;
}

export function MCEmptyState({
  feature,
  children,
}: {
  feature: FeatureKey;
  /** Fallback content when feature is configured but data is empty. */
  children?: React.ReactNode;
}) {
  const { data: readiness, isLoading } = useMCReadiness();
  const t = useThemeTokens();

  if (isLoading) return null;

  const feat: MCFeatureReadiness | undefined = readiness?.[feature];

  // If readiness data unavailable, show children as fallback
  if (!feat) return <>{children}</>;

  // Feature has issues → show amber guidance banner
  if (feat.issues.length > 0) {
    return (
      <View style={{ gap: 12 }}>
        {feat.issues.map((issue, i) => {
          const fix = guessFixLink(issue);
          return (
            <View
              key={i}
              className="rounded-xl p-4"
              style={{
                backgroundColor: "rgba(234,179,8,0.08)",
                borderWidth: 1,
                borderColor: "rgba(234,179,8,0.25)",
              }}
            >
              <View className="flex-row items-start gap-3">
                <AlertTriangle
                  size={18}
                  color="#ca8a04"
                  style={{ marginTop: 1 }}
                />
                <View className="flex-1" style={{ gap: 4 }}>
                  <Text
                    style={{
                      fontSize: 13,
                      fontWeight: "600",
                      color: "#ca8a04",
                      lineHeight: 18,
                    }}
                  >
                    {issue}
                  </Text>
                  {feat.detail && (
                    <Text
                      style={{
                        fontSize: 12,
                        color: "#a16207",
                        lineHeight: 16,
                      }}
                    >
                      {feat.detail}
                    </Text>
                  )}
                  {fix && (
                    <Link href={fix.href as any} asChild>
                      <Pressable className="flex-row items-center gap-1 mt-1">
                        <Text
                          style={{
                            fontSize: 12,
                            fontWeight: "600",
                            color: t.accent,
                          }}
                        >
                          {fix.label}
                        </Text>
                        <ArrowRight size={10} color={t.accent} />
                      </Pressable>
                    </Link>
                  )}
                </View>
              </View>
            </View>
          );
        })}
      </View>
    );
  }

  // Feature is configured but no data → show children (e.g. "No entries")
  if (feat.ready && children) {
    return <>{children}</>;
  }

  // Fallback
  return <>{children}</>;
}

/**
 * Compact readiness indicator dot + status for QuickNav cards.
 */
export function ReadinessIndicator({ feature }: { feature: FeatureKey }) {
  const { data: readiness } = useMCReadiness();
  const t = useThemeTokens();
  const feat = readiness?.[feature];

  if (!feat) return null;

  const dotColor = feat.ready
    ? feat.issues.length > 0
      ? "#eab308" // yellow — partially configured
      : "#22c55e" // green — ready
    : feat.issues.length > 0
      ? "#ef4444" // red — not configured
      : "#9ca3af"; // gray — unknown

  return (
    <View className="flex-row items-center gap-1.5">
      <View
        style={{
          width: 6,
          height: 6,
          borderRadius: 3,
          backgroundColor: dotColor,
        }}
      />
      <Text style={{ fontSize: 10, color: t.textDim }} numberOfLines={1}>
        {feat.detail}
      </Text>
    </View>
  );
}
