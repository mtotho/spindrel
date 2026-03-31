import { useState } from "react";
import { View, Text, Pressable, ScrollView } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCMemory,
  type MCMemorySection,
} from "@/src/api/hooks/useMissionControl";
import { Brain, FileText } from "lucide-react";

// ---------------------------------------------------------------------------
// Bot colors
// ---------------------------------------------------------------------------
const BOT_COLORS = [
  "#3b82f6", "#a855f7", "#ec4899", "#22c55e", "#06b6d4",
  "#6366f1", "#f43f5e", "#84cc16", "#f97316", "#eab308",
];

function botColor(botId: string): string {
  let hash = 0;
  for (let i = 0; i < botId.length; i++) {
    hash = ((hash << 5) - hash + botId.charCodeAt(i)) | 0;
  }
  return BOT_COLORS[Math.abs(hash) % BOT_COLORS.length];
}

// ---------------------------------------------------------------------------
// Memory Section component
// ---------------------------------------------------------------------------
function MemorySectionView({ section }: { section: MCMemorySection }) {
  const t = useThemeTokens();
  const color = botColor(section.bot_id);

  return (
    <View className="rounded-xl border border-surface-border overflow-hidden">
      {/* Header */}
      <View
        className="flex-row items-center gap-2 px-4 py-3 border-b border-surface-border"
        style={{ backgroundColor: `${color}08` }}
      >
        <View
          style={{
            width: 10,
            height: 10,
            borderRadius: 5,
            backgroundColor: color,
          }}
        />
        <Text className="text-text font-semibold text-sm flex-1">
          {section.bot_name}
        </Text>
        {section.reference_files.length > 0 && (
          <View className="flex-row items-center gap-1">
            <FileText size={12} color={t.textDim} />
            <Text className="text-text-dim text-xs">
              {section.reference_files.length} ref
            </Text>
          </View>
        )}
      </View>

      {/* MEMORY.md content */}
      <View className="p-4">
        {section.memory_content ? (
          <Text
            className="text-text-muted text-xs"
            style={{ fontFamily: "monospace", lineHeight: 18 }}
          >
            {section.memory_content}
          </Text>
        ) : (
          <Text className="text-text-dim text-xs italic">
            No MEMORY.md found
          </Text>
        )}
      </View>

      {/* Reference files */}
      {section.reference_files.length > 0 && (
        <View className="px-4 pb-4">
          <Text className="text-text-dim text-[10px] font-semibold tracking-wider mb-2">
            REFERENCE FILES
          </Text>
          <View className="gap-1">
            {section.reference_files.map((file) => (
              <View key={file} className="flex-row items-center gap-2">
                <FileText size={12} color={t.textDim} />
                <Text className="text-text-muted text-xs">{file}</Text>
              </View>
            ))}
          </View>
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCMemory() {
  const { data, isLoading } = useMCMemory();
  const { refreshing, onRefresh } = usePageRefresh([["mc-memory"]]);
  const t = useThemeTokens();

  const sections = data?.sections || [];

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Memory" subtitle="MEMORY.md across bots" />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ padding: 16, gap: 16, paddingBottom: 40 }}
      >
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading memory...</Text>
        ) : sections.length === 0 ? (
          <Text className="text-text-muted text-sm">
            No bots with workspace-files memory scheme found.
          </Text>
        ) : (
          sections.map((section) => (
            <MemorySectionView key={section.bot_id} section={section} />
          ))
        )}
      </RefreshableScrollView>
    </View>
  );
}
