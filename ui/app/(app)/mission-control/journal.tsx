import { useState } from "react";
import { View, Text, Pressable } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCJournal,
  type MCJournalEntry,
} from "@/src/api/hooks/useMissionControl";
import { ChevronDown, ChevronRight, Calendar } from "lucide-react";

// ---------------------------------------------------------------------------
// Bot colors
// ---------------------------------------------------------------------------
const BOT_DOT_COLORS = [
  "#3b82f6", "#a855f7", "#ec4899", "#22c55e", "#06b6d4",
  "#6366f1", "#f43f5e", "#84cc16", "#f97316", "#eab308",
];

function botDotColor(botId: string): string {
  let hash = 0;
  for (let i = 0; i < botId.length; i++) {
    hash = ((hash << 5) - hash + botId.charCodeAt(i)) | 0;
  }
  return BOT_DOT_COLORS[Math.abs(hash) % BOT_DOT_COLORS.length];
}

// ---------------------------------------------------------------------------
// Entry component
// ---------------------------------------------------------------------------
function JournalEntryView({ entry }: { entry: MCJournalEntry }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const dot = botDotColor(entry.bot_id);
  const preview = entry.content.split("\n").slice(0, 3).join("\n");

  return (
    <Pressable
      onPress={() => setExpanded(!expanded)}
      className="rounded-lg border border-surface-border p-4 hover:bg-surface-overlay"
    >
      <View className="flex-row items-center gap-2 mb-2">
        {expanded ? (
          <ChevronDown size={14} color={t.textDim} />
        ) : (
          <ChevronRight size={14} color={t.textDim} />
        )}
        <View
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            backgroundColor: dot,
          }}
        />
        <Text className="text-text font-semibold text-sm">{entry.bot_name}</Text>
        <Text className="text-text-dim text-xs">{entry.date}</Text>
      </View>

      <Text
        className="text-text-muted text-xs"
        style={{ fontFamily: "monospace", lineHeight: 18 }}
        numberOfLines={expanded ? undefined : 3}
      >
        {expanded ? entry.content : preview}
      </Text>

      {!expanded && entry.content.split("\n").length > 3 && (
        <Text className="text-accent text-[10px] mt-1">
          Show more...
        </Text>
      )}
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Date filter
// ---------------------------------------------------------------------------
const DAY_OPTIONS = [
  { label: "7d", value: 7 },
  { label: "14d", value: 14 },
  { label: "30d", value: 30 },
  { label: "60d", value: 60 },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCJournal() {
  const [days, setDays] = useState(7);
  const { data, isLoading } = useMCJournal(days);
  const { refreshing, onRefresh } = usePageRefresh([["mc-journal"]]);
  const t = useThemeTokens();

  const entries = data?.entries || [];

  // Group by date
  const grouped = new Map<string, MCJournalEntry[]>();
  for (const entry of entries) {
    const list = grouped.get(entry.date) || [];
    list.push(entry);
    grouped.set(entry.date, list);
  }

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Journal" subtitle="Daily logs across bots" />

      {/* Date range picker */}
      <View className="flex-row items-center gap-2 px-4 py-2 border-b border-surface-border">
        <Calendar size={14} color={t.textDim} />
        {DAY_OPTIONS.map((opt) => (
          <Pressable
            key={opt.value}
            onPress={() => setDays(opt.value)}
            className={`rounded-full px-3 py-1 border ${
              days === opt.value
                ? "border-accent bg-accent/10"
                : "border-surface-border"
            }`}
          >
            <Text
              className={`text-xs ${
                days === opt.value ? "text-accent font-medium" : "text-text-muted"
              }`}
            >
              {opt.label}
            </Text>
          </Pressable>
        ))}
      </View>

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ padding: 16, gap: 16, paddingBottom: 40 }}
      >
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading journal...</Text>
        ) : entries.length === 0 ? (
          <Text className="text-text-muted text-sm">
            No journal entries found for the last {days} days.
          </Text>
        ) : (
          Array.from(grouped.entries()).map(([date, dateEntries]) => (
            <View key={date}>
              <Text className="text-text-dim text-xs font-semibold tracking-wider mb-2">
                {date}
              </Text>
              <View className="gap-3">
                {dateEntries.map((entry, idx) => (
                  <JournalEntryView key={`${entry.bot_id}-${idx}`} entry={entry} />
                ))}
              </View>
            </View>
          ))
        )}
      </RefreshableScrollView>
    </View>
  );
}
