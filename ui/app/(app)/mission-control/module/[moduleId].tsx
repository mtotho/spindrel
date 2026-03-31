/**
 * Dynamic integration module page for Mission Control.
 *
 * Fetches structured data from the integration's API endpoint and renders
 * it using a generic section renderer. Integrations return JSON, not React.
 */
import { View, Text, Platform } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { useMCModules } from "@/src/api/hooks/useMissionControl";

// Lazy markdown import (web only)
let MarkdownViewer: React.ComponentType<{ content: string }> | null = null;
try {
  if (Platform.OS === "web") {
    MarkdownViewer =
      require("@/src/components/workspace/MarkdownViewer").MarkdownViewer;
  }
} catch {
  // Not available
}

// ---------------------------------------------------------------------------
// Module data types (returned by integration endpoints)
// ---------------------------------------------------------------------------
interface StatRowSection {
  type: "stat_row";
  stats: Array<{ label: string; value: string | number }>;
}

interface TableSection {
  type: "table";
  headers: string[];
  rows: Array<Array<string | number>>;
}

interface MarkdownSection {
  type: "markdown";
  content: string;
}

type ModuleSection = StatRowSection | TableSection | MarkdownSection;

interface ModuleData {
  title: string;
  sections: ModuleSection[];
}

// ---------------------------------------------------------------------------
// Section renderers
// ---------------------------------------------------------------------------
function StatRow({ section }: { section: StatRowSection }) {
  const t = useThemeTokens();
  return (
    <View className="flex-row flex-wrap gap-3">
      {section.stats.map((stat, i) => (
        <View
          key={i}
          className="rounded-lg border border-surface-border px-4 py-3"
          style={{ minWidth: 120, flex: 1 }}
        >
          <Text
            className="text-text-dim"
            style={{
              fontSize: 10,
              fontWeight: "600",
              letterSpacing: 0.5,
              textTransform: "uppercase",
            }}
          >
            {stat.label}
          </Text>
          <Text style={{ fontSize: 20, fontWeight: "700", color: t.text }}>
            {stat.value}
          </Text>
        </View>
      ))}
    </View>
  );
}

function TableView({ section }: { section: TableSection }) {
  const t = useThemeTokens();
  return (
    <View className="rounded-lg border border-surface-border overflow-hidden">
      {/* Header */}
      <View
        className="flex-row border-b border-surface-border"
        style={{ backgroundColor: "rgba(107,114,128,0.05)" }}
      >
        {section.headers.map((h, i) => (
          <View key={i} className="px-3 py-2" style={{ flex: 1 }}>
            <Text
              className="text-text-dim text-xs font-semibold"
              numberOfLines={1}
            >
              {h}
            </Text>
          </View>
        ))}
      </View>
      {/* Rows */}
      {section.rows.map((row, ri) => (
        <View
          key={ri}
          className="flex-row border-b border-surface-border"
          style={
            ri === section.rows.length - 1 ? { borderBottomWidth: 0 } : undefined
          }
        >
          {row.map((cell, ci) => (
            <View key={ci} className="px-3 py-2" style={{ flex: 1 }}>
              <Text className="text-text-muted text-xs" numberOfLines={2}>
                {String(cell)}
              </Text>
            </View>
          ))}
        </View>
      ))}
    </View>
  );
}

function SectionRenderer({ section }: { section: ModuleSection }) {
  switch (section.type) {
    case "stat_row":
      return <StatRow section={section} />;
    case "table":
      return <TableView section={section} />;
    case "markdown":
      return MarkdownViewer ? (
        <MarkdownViewer content={section.content} />
      ) : (
        <Text
          style={{ fontFamily: "monospace", fontSize: 12, lineHeight: 18 }}
        >
          {section.content}
        </Text>
      );
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCModulePage() {
  const { moduleId } = useLocalSearchParams<{ moduleId: string }>();
  const { data: modulesData } = useMCModules();
  const modules = modulesData?.modules || [];
  const mod = modules.find((m) => m.module_id === moduleId);

  const { data, isLoading, error } = useQuery({
    queryKey: ["mc-module-data", moduleId],
    queryFn: () =>
      apiFetch<ModuleData>(`${mod!.api_base}/data`),
    enabled: !!mod,
  });

  const { refreshing, onRefresh } = usePageRefresh([
    ["mc-module-data", moduleId],
  ]);
  const t = useThemeTokens();

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title={mod?.label || moduleId || "Module"}
        subtitle={mod?.description || "Integration module"}
      />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{
          padding: 16,
          gap: 16,
          paddingBottom: 40,
          maxWidth: 960,
        }}
      >
        {!mod ? (
          <Text className="text-text-muted text-sm">
            Module "{moduleId}" not found. Check that the integration is installed and configured.
          </Text>
        ) : isLoading ? (
          <Text className="text-text-muted text-sm">Loading module data...</Text>
        ) : error ? (
          <View
            className="rounded-lg p-4"
            style={{
              backgroundColor: "rgba(239,68,68,0.06)",
              borderWidth: 1,
              borderColor: "rgba(239,68,68,0.15)",
            }}
          >
            <Text style={{ fontSize: 13, color: "#ef4444", fontWeight: "600" }}>
              Failed to load module data
            </Text>
            <Text
              style={{ fontSize: 12, color: "#dc2626", marginTop: 4 }}
            >
              {(error as any)?.message || "Unknown error"}
            </Text>
          </View>
        ) : data ? (
          <>
            {data.title && (
              <Text
                className="text-text"
                style={{ fontSize: 18, fontWeight: "700" }}
              >
                {data.title}
              </Text>
            )}
            {data.sections?.map((section, i) => (
              <SectionRenderer key={i} section={section} />
            ))}
          </>
        ) : null}
      </RefreshableScrollView>
    </View>
  );
}
