import { useState } from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { Link } from "expo-router";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import {
  useMCReadiness,
  type MCFeatureReadiness,
} from "@/src/api/hooks/useMissionControl";
import {
  CheckCircle,
  AlertTriangle,
  XCircle,
  ChevronDown,
  ChevronRight,
  ArrowRight,
  BookOpen,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Lazy markdown import (web only)
// ---------------------------------------------------------------------------
let MarkdownViewer: React.ComponentType<{ content: string }> | null = null;
try {
  if (Platform.OS === "web") {
    MarkdownViewer =
      require("@/src/components/workspace/MarkdownViewer").MarkdownViewer;
  }
} catch {
  // Not available — fallback to monospace
}

// ---------------------------------------------------------------------------
// Setup guide content hook
// ---------------------------------------------------------------------------
function useSetupGuide() {
  return useQuery({
    queryKey: ["mc-setup-guide"],
    queryFn: () =>
      apiFetch<{ content: string }>("/api/v1/mission-control/setup-guide"),
    staleTime: 300_000,
  });
}

// ---------------------------------------------------------------------------
// Feature readiness row
// ---------------------------------------------------------------------------
const FIX_LINKS: Record<string, { href: string; label: string }> = {
  dashboard: { href: "/admin/channels", label: "Channel Settings" },
  kanban: { href: "/mission-control/kanban", label: "Kanban Board" },
  journal: { href: "/admin/bots", label: "Bot Config" },
  memory: { href: "/admin/bots", label: "Bot Config" },
};

function ReadinessRow({
  label,
  feature,
  readiness,
}: {
  label: string;
  feature: string;
  readiness: MCFeatureReadiness;
}) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(!readiness.ready);
  const fix = FIX_LINKS[feature];

  const StatusIcon = readiness.ready
    ? CheckCircle
    : readiness.issues.length > 0
      ? XCircle
      : AlertTriangle;

  const statusColor = readiness.ready
    ? "#22c55e"
    : readiness.issues.length > 0
      ? "#ef4444"
      : "#eab308";

  return (
    <View className="rounded-xl border border-surface-border overflow-hidden">
      <Pressable
        onPress={() => setExpanded(!expanded)}
        className="flex-row items-center gap-3 px-4 py-3 hover:bg-surface-overlay"
      >
        <StatusIcon size={18} color={statusColor} />
        <Text className="text-text font-semibold text-sm flex-1">{label}</Text>
        <Text className="text-text-dim text-xs">{readiness.detail}</Text>
        {expanded ? (
          <ChevronDown size={14} color={t.textDim} />
        ) : (
          <ChevronRight size={14} color={t.textDim} />
        )}
      </Pressable>

      {expanded && (
        <View className="px-4 pb-3 pt-1 border-t border-surface-border" style={{ gap: 6 }}>
          {readiness.issues.length > 0 ? (
            readiness.issues.map((issue, i) => (
              <Text key={i} className="text-text-muted text-xs" style={{ lineHeight: 18 }}>
                {issue}
              </Text>
            ))
          ) : (
            <Text className="text-text-dim text-xs" style={{ lineHeight: 18 }}>
              Everything looks good.
            </Text>
          )}
          {fix && readiness.issues.length > 0 && (
            <Link href={fix.href as any} asChild>
              <Pressable className="flex-row items-center gap-1 mt-1">
                <Text style={{ fontSize: 12, fontWeight: "600", color: t.accent }}>
                  {fix.label}
                </Text>
                <ArrowRight size={10} color={t.accent} />
              </Pressable>
            </Link>
          )}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCSetup() {
  const { data: readiness, isLoading: readinessLoading } = useMCReadiness();
  const { data: guide, isLoading: guideLoading } = useSetupGuide();
  const { refreshing, onRefresh } = usePageRefresh([
    ["mc-readiness"],
    ["mc-setup-guide"],
  ]);
  const t = useThemeTokens();

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Setup" subtitle="Configuration checklist" />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{
          padding: 16,
          gap: 24,
          paddingBottom: 40,
          maxWidth: 960,
        }}
      >
        {/* Feature readiness checklist */}
        <View style={{ gap: 10 }}>
          <Text
            className="text-text-dim"
            style={{
              fontSize: 10,
              fontWeight: "700",
              letterSpacing: 0.8,
              textTransform: "uppercase",
            }}
          >
            FEATURE READINESS
          </Text>

          {readinessLoading ? (
            <Text className="text-text-muted text-sm">Checking...</Text>
          ) : readiness ? (
            <View style={{ gap: 8 }}>
              <ReadinessRow
                label="Dashboard"
                feature="dashboard"
                readiness={readiness.dashboard}
              />
              <ReadinessRow
                label="Kanban Board"
                feature="kanban"
                readiness={readiness.kanban}
              />
              <ReadinessRow
                label="Journal"
                feature="journal"
                readiness={readiness.journal}
              />
              <ReadinessRow
                label="Memory"
                feature="memory"
                readiness={readiness.memory}
              />
            </View>
          ) : null}
        </View>

        {/* Setup guide documentation */}
        <View style={{ gap: 10 }}>
          <View className="flex-row items-center gap-2">
            <BookOpen size={14} color={t.textDim} />
            <Text
              className="text-text-dim"
              style={{
                fontSize: 10,
                fontWeight: "700",
                letterSpacing: 0.8,
                textTransform: "uppercase",
              }}
            >
              SETUP GUIDE
            </Text>
          </View>

          <View className="rounded-xl border border-surface-border p-4">
            {guideLoading ? (
              <Text className="text-text-muted text-sm">Loading guide...</Text>
            ) : guide?.content && MarkdownViewer ? (
              <MarkdownViewer content={guide.content} />
            ) : (
              <Text
                className="text-text-muted text-xs"
                style={{ fontFamily: "monospace", lineHeight: 18 }}
              >
                {guide?.content || "Could not load setup guide."}
              </Text>
            )}
          </View>
        </View>
      </RefreshableScrollView>
    </View>
  );
}
