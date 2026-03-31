import { useState, useMemo } from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCJournal,
  useMCPrefs,
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
// Relative date label
// ---------------------------------------------------------------------------
function dateLabel(isoDate: string): string {
  const now = new Date();
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const yest = new Date(now);
  yest.setDate(yest.getDate() - 1);
  const yestStr = `${yest.getFullYear()}-${String(yest.getMonth() + 1).padStart(2, "0")}-${String(yest.getDate()).padStart(2, "0")}`;

  if (isoDate === todayStr) return "Today";
  if (isoDate === yestStr) return "Yesterday";

  const d = new Date(isoDate + "T12:00:00");
  const diffMs = now.getTime() - d.getTime();
  const diffDays = Math.round(diffMs / 86_400_000);
  if (diffDays < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// ---------------------------------------------------------------------------
// Entry component — shows more content by default
// ---------------------------------------------------------------------------
function JournalEntryView({ entry }: { entry: MCJournalEntry }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const dot = botDotColor(entry.bot_id);
  const lines = entry.content.split("\n");
  const isLong = lines.length > 8;
  const preview = lines.slice(0, 8).join("\n");

  return (
    <Pressable
      onPress={() => setExpanded(!expanded)}
      className="rounded-xl border border-surface-border hover:bg-surface-overlay"
      style={{ overflow: "hidden" }}
    >
      {/* Header */}
      <View
        className="flex-row items-center gap-2 px-4 py-3"
        style={{ borderBottomWidth: 1, borderBottomColor: t.surfaceBorder }}
      >
        {isLong && (expanded ? (
          <ChevronDown size={14} color={t.textDim} />
        ) : (
          <ChevronRight size={14} color={t.textDim} />
        ))}
        <View
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            backgroundColor: dot,
          }}
        />
        <Text className="text-text font-semibold" style={{ fontSize: 13 }}>
          {entry.bot_name}
        </Text>
        <View style={{ flex: 1 }} />
        <Text className="text-text-dim" style={{ fontSize: 11, fontFamily: "monospace" }}>
          {entry.date}
        </Text>
      </View>

      {/* Content */}
      <View style={{ padding: 16 }}>
        {expanded && MarkdownViewer ? (
          <MarkdownViewer content={entry.content} />
        ) : (
          <Text
            className="text-text"
            style={{ fontSize: 12, lineHeight: 19, fontFamily: "monospace" }}
            numberOfLines={expanded ? undefined : 8}
          >
            {expanded ? entry.content : preview}
          </Text>
        )}

        {!expanded && isLong && (
          <Text className="text-accent mt-2" style={{ fontSize: 11, fontWeight: "500" }}>
            {lines.length - 8} more lines...
          </Text>
        )}
      </View>
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

  const groupLabel = (key: string): { label: string; sub?: string } => {
    if (groupMode === "date") {
      return { label: dateLabel(key), sub: key };
    }
    return { label: bots.find((b) => b.id === key)?.name || key };
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
        contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 24, gap: 28, paddingBottom: 40, maxWidth: 960 }}
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
          Array.from(grouped.entries()).map(([key, groupEntries]) => {
            const gl = groupLabel(key);
            const isToday = gl.label === "Today";
            return (
              <View key={key} style={{ gap: 12 }}>
                {/* Group header */}
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <View
                    style={{
                      paddingHorizontal: 10,
                      paddingVertical: 4,
                      borderRadius: 12,
                      backgroundColor: isToday ? t.accent + "18" : t.surfaceOverlay,
                    }}
                  >
                    <Text
                      style={{
                        fontSize: 12,
                        fontWeight: "700",
                        color: isToday ? t.accent : t.text,
                        letterSpacing: 0.3,
                      }}
                    >
                      {gl.label}
                    </Text>
                  </View>
                  {gl.sub && (
                    <Text style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
                      {gl.sub}
                    </Text>
                  )}
                  <Text style={{ fontSize: 10, color: t.textDim }}>
                    {groupEntries.length} entr{groupEntries.length !== 1 ? "ies" : "y"}
                  </Text>
                  <View style={{ flex: 1, height: 1, backgroundColor: t.surfaceBorder, marginLeft: 4 }} />
                </View>
                <View style={{ gap: 10 }}>
                  {groupEntries.map((entry) => (
                    <JournalEntryView key={`${entry.bot_id}-${entry.date}`} entry={entry} />
                  ))}
                </View>
              </View>
            );
          })
        )}
      </RefreshableScrollView>
    </View>
  );
}
