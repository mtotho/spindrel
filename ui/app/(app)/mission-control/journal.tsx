import { useState, useMemo } from "react";
import { View, Text, Pressable, useWindowDimensions, Platform } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCJournal,
  useMCPrefs,
  useUpdateMCPrefs,
  type MCJournalEntry,
} from "@/src/api/hooks/useMissionControl";
import { MCEmptyState } from "@/src/components/mission-control/MCEmptyState";
import { botDotColor } from "@/src/components/mission-control/botColors";
import { ChevronDown, ChevronRight, Calendar, Users, LayoutList } from "lucide-react";

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

      {expanded && MarkdownViewer ? (
        <MarkdownViewer content={entry.content} />
      ) : (
        <Text
          className="text-text-muted text-xs"
          style={{ fontFamily: "monospace", lineHeight: 18 }}
          numberOfLines={expanded ? undefined : 3}
        >
          {expanded ? entry.content : preview}
        </Text>
      )}

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
  const [filterBot, setFilterBot] = useState<string | null>(null);
  const [groupMode, setGroupMode] = useState<"date" | "bot">("date");
  const { data: prefs } = useMCPrefs();
  const scope = ((prefs?.layout_prefs as any)?.scope as "fleet" | "personal") || "fleet";
  const { data, isLoading } = useMCJournal(days, scope);
  const { refreshing, onRefresh } = usePageRefresh([["mc-journal"]]);
  const t = useThemeTokens();

  const entries = data?.entries || [];

  // Extract unique bots for filter pills
  const bots = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of entries) map.set(e.bot_id, e.bot_name);
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [entries]);

  // Apply bot filter
  const filtered = useMemo(
    () => (filterBot ? entries.filter((e) => e.bot_id === filterBot) : entries),
    [entries, filterBot]
  );

  // Group entries
  const grouped = useMemo(() => {
    const map = new Map<string, MCJournalEntry[]>();
    for (const entry of filtered) {
      const key = groupMode === "date" ? entry.date : entry.bot_id;
      const list = map.get(key) || [];
      list.push(entry);
      map.set(key, list);
    }
    return map;
  }, [filtered, groupMode]);

  const groupLabel = (key: string) => {
    if (groupMode === "date") return key;
    return bots.find((b) => b.id === key)?.name || key;
  };

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Journal" subtitle="Daily logs across bots" />

      {/* Filter bar */}
      <View className="flex-row items-center gap-2 px-4 py-2 border-b border-surface-border flex-wrap">
        {/* Date range */}
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

        {/* Separator */}
        <View
          style={{ width: 1, height: 16, backgroundColor: t.surfaceBorder, marginHorizontal: 4 }}
        />

        {/* Bot filter pills */}
        {bots.length > 1 && (
          <>
            <Pressable
              onPress={() => setFilterBot(null)}
              className={`rounded-full px-3 py-1 border ${
                !filterBot ? "border-accent bg-accent/10" : "border-surface-border"
              }`}
            >
              <Text
                className={`text-xs ${
                  !filterBot ? "text-accent font-medium" : "text-text-muted"
                }`}
              >
                All bots
              </Text>
            </Pressable>
            {bots.map((bot) => {
              const active = filterBot === bot.id;
              return (
                <Pressable
                  key={bot.id}
                  onPress={() => setFilterBot(active ? null : bot.id)}
                  className={`rounded-full px-3 py-1 border flex-row items-center gap-1.5 ${
                    active ? "border-accent bg-accent/10" : "border-surface-border"
                  }`}
                >
                  <View
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 3,
                      backgroundColor: botDotColor(bot.id),
                    }}
                  />
                  <Text
                    className={`text-xs ${
                      active ? "text-accent font-medium" : "text-text-muted"
                    }`}
                  >
                    {bot.name}
                  </Text>
                </Pressable>
              );
            })}
          </>
        )}

        {/* Separator */}
        <View
          style={{ width: 1, height: 16, backgroundColor: t.surfaceBorder, marginHorizontal: 4 }}
        />

        {/* Group toggle */}
        <Pressable
          onPress={() => setGroupMode(groupMode === "date" ? "bot" : "date")}
          className="flex-row items-center gap-1.5 rounded-full px-3 py-1 border border-surface-border hover:bg-surface-overlay"
        >
          {groupMode === "date" ? (
            <LayoutList size={12} color={t.textDim} />
          ) : (
            <Users size={12} color={t.textDim} />
          )}
          <Text className="text-text-muted text-xs">
            By {groupMode === "date" ? "Date" : "Bot"}
          </Text>
        </Pressable>
      </View>

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 24, gap: 24, paddingBottom: 40, maxWidth: 960 }}
      >
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading journal...</Text>
        ) : filtered.length === 0 ? (
          <MCEmptyState feature="journal">
            <Text className="text-text-muted text-sm">
              No journal entries found for the last {days} days.
            </Text>
          </MCEmptyState>
        ) : (
          Array.from(grouped.entries()).map(([key, groupEntries]) => (
            <View key={key} style={{ gap: 10 }}>
              <Text className="text-text-dim text-xs font-semibold tracking-wider">
                {groupLabel(key)}
              </Text>
              <View style={{ gap: 10 }}>
                {groupEntries.map((entry) => (
                  <JournalEntryView key={`${entry.bot_id}-${entry.date}`} entry={entry} />
                ))}
              </View>
            </View>
          ))
        )}
      </RefreshableScrollView>
    </View>
  );
}
