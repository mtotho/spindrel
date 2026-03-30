import { useMemo, useState } from "react";
import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import {
  Heart,
  ClipboardList,
  Clock,
  Moon,
  ArrowRight,
} from "lucide-react";
import { useUpcomingActivity, type UpcomingItem } from "@/src/api/hooks/useUpcomingActivity";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { formatTimeShort } from "@/src/utils/time";
import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Bot color palette (matches tasks page)
// ---------------------------------------------------------------------------
const BOT_COLORS = [
  { bg: "rgba(59,130,246,0.12)", dot: "#3b82f6", fg: "#2563eb" },
  { bg: "rgba(168,85,247,0.12)", dot: "#a855f7", fg: "#9333ea" },
  { bg: "rgba(236,72,153,0.12)", dot: "#ec4899", fg: "#db2777" },
  { bg: "rgba(239,68,68,0.12)", dot: "#ef4444", fg: "#dc2626" },
  { bg: "rgba(249,115,22,0.12)", dot: "#f97316", fg: "#ea580c" },
  { bg: "rgba(234,179,8,0.12)", dot: "#eab308", fg: "#ca8a04" },
  { bg: "rgba(34,197,94,0.12)", dot: "#22c55e", fg: "#16a34a" },
  { bg: "rgba(20,184,166,0.12)", dot: "#14b8a6", fg: "#0d9488" },
  { bg: "rgba(6,182,212,0.12)", dot: "#06b6d4", fg: "#0891b2" },
  { bg: "rgba(99,102,241,0.12)", dot: "#6366f1", fg: "#4f46e5" },
  { bg: "rgba(244,63,94,0.12)", dot: "#f43f5e", fg: "#e11d48" },
  { bg: "rgba(132,204,22,0.12)", dot: "#84cc16", fg: "#65a30d" },
];

function botColor(botId: string) {
  let hash = 0;
  for (let i = 0; i < botId.length; i++) {
    hash = ((hash << 5) - hash + botId.charCodeAt(i)) | 0;
  }
  return BOT_COLORS[Math.abs(hash) % BOT_COLORS.length];
}

const TYPE_BADGE: Record<string, { bg: string; fg: string; label: string }> = {
  heartbeat: { bg: "rgba(234,179,8,0.12)", fg: "#ca8a04", label: "Heartbeat" },
  scheduled: { bg: "rgba(59,130,246,0.12)", fg: "#3b82f6", label: "Scheduled" },
  delegation: { bg: "rgba(168,85,247,0.12)", fg: "#9333ea", label: "Delegation" },
  agent: { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af", label: "Task" },
};

type TypeFilter = "all" | "heartbeat" | "task";

// ---------------------------------------------------------------------------
// Date grouping helpers
// ---------------------------------------------------------------------------
function startOfDay(d: Date) {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}

function isToday(d: Date) {
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

function isTomorrow(d: Date) {
  const tom = new Date();
  tom.setDate(tom.getDate() + 1);
  return d.getFullYear() === tom.getFullYear() && d.getMonth() === tom.getMonth() && d.getDate() === tom.getDate();
}

function dateSectionLabel(d: Date): string {
  if (isToday(d)) return "Today";
  if (isTomorrow(d)) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function relativeTime(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff < 0) return "now";
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "< 1m";
  if (mins < 60) return `in ${mins}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `in ${hrs}h`;
  const days = Math.round(hrs / 24);
  return `in ${days}d`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function UpcomingActivityPage() {
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const apiType = typeFilter === "all" ? undefined : typeFilter;
  const { data: items, isLoading } = useUpcomingActivity(200, apiType);
  const { refreshing, onRefresh } = usePageRefresh([["upcoming-activity"]]);
  const t = useThemeTokens();

  // Group items by date
  const groups = useMemo(() => {
    if (!items?.length) return [];
    const map = new Map<string, { label: string; items: UpcomingItem[] }>();
    for (const item of items) {
      const d = new Date(item.scheduled_at);
      const key = startOfDay(d).toISOString();
      if (!map.has(key)) {
        map.set(key, { label: dateSectionLabel(d), items: [] });
      }
      map.get(key)!.items.push(item);
    }
    return Array.from(map.values());
  }, [items]);

  const FILTERS: { key: TypeFilter; label: string }[] = [
    { key: "all", label: "All" },
    { key: "heartbeat", label: "Heartbeats" },
    { key: "task", label: "Tasks" },
  ];

  return (
    <View className="flex-1 bg-background">
      <MobileHeader title="Upcoming Activity" />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ paddingBottom: 40 }}
      >
        {/* Header */}
        <View className="px-6 pt-6 pb-3">
          <View className="flex-row items-center justify-between mb-4">
            <View className="flex-row items-center gap-3">
              <Clock size={20} color={t.text} />
              <Text style={{ fontSize: 20, fontWeight: "700", color: t.text }}>
                Upcoming Activity
              </Text>
            </View>
            <Link href={"/admin/tasks" as any} asChild>
              <Pressable className="flex-row items-center gap-1.5 rounded-md px-3 py-1.5 hover:bg-surface-overlay active:bg-surface-overlay">
                <Text className="text-sm text-accent">Tasks</Text>
                <ArrowRight size={14} color={t.accent} />
              </Pressable>
            </Link>
          </View>

          {/* Type filter */}
          <View className="flex-row gap-2">
            {FILTERS.map((f) => (
              <Pressable
                key={f.key}
                onPress={() => setTypeFilter(f.key)}
                className={`rounded-full px-3 py-1 ${
                  typeFilter === f.key ? "bg-accent/15" : "bg-surface-overlay"
                }`}
              >
                <Text
                  className={`text-xs font-medium ${
                    typeFilter === f.key ? "text-accent" : "text-text-muted"
                  }`}
                >
                  {f.label}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>

        {/* Content */}
        {isLoading ? (
          <View className="px-6 gap-3 pt-2">
            {[1, 2, 3, 4].map((i) => (
              <View key={i} className="flex-row items-center gap-3 py-3">
                <View className="rounded animate-pulse" style={{ width: 18, height: 18, backgroundColor: t.skeletonBg }} />
                <View className="flex-1 gap-1.5">
                  <View className="rounded animate-pulse" style={{ height: 14, width: `${40 + i * 12}%`, backgroundColor: t.skeletonBg }} />
                  <View className="rounded animate-pulse" style={{ height: 11, width: `${25 + i * 8}%`, backgroundColor: t.skeletonBg }} />
                </View>
              </View>
            ))}
          </View>
        ) : !groups.length ? (
          <View className="items-center justify-center py-16 px-6">
            <Clock size={32} color={t.textDim} style={{ opacity: 0.3, marginBottom: 12 }} />
            <Text className="text-text-dim text-sm">No upcoming activity</Text>
          </View>
        ) : (
          groups.map((group) => (
            <View key={group.label} className="px-4 mb-2">
              {/* Date header */}
              <View className="px-2 py-2 mb-1">
                <Text style={{ fontSize: 12, fontWeight: "600", color: t.textDim, letterSpacing: 0.5 }}>
                  {group.label.toUpperCase()}
                </Text>
              </View>

              {/* Items */}
              {group.items.map((item, idx) => {
                const bc = botColor(item.bot_id);
                const badge = item.type === "heartbeat"
                  ? TYPE_BADGE.heartbeat
                  : TYPE_BADGE[item.task_type || "agent"] || TYPE_BADGE.agent;
                const href = item.type === "heartbeat" && item.channel_id
                  ? `/channels/${item.channel_id}`
                  : "/admin/tasks";

                return (
                  <Link key={`${item.type}-${idx}`} href={href as any} asChild>
                    <Pressable className="flex-row items-center gap-3 rounded-lg px-3 py-3 hover:bg-surface-overlay active:bg-surface-overlay">
                      {/* Type icon */}
                      {item.type === "heartbeat" ? (
                        <Heart
                          size={16}
                          color={item.in_quiet_hours ? t.textDim : t.warning}
                          style={item.in_quiet_hours ? { opacity: 0.4 } : undefined}
                        />
                      ) : (
                        <ClipboardList size={16} color={t.accent} />
                      )}

                      {/* Bot dot */}
                      <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: bc.dot, flexShrink: 0 }} />

                      {/* Title + meta */}
                      <View className="flex-1 min-w-0">
                        <Text className="text-text text-sm" numberOfLines={1}>
                          {item.type === "heartbeat" && item.channel_name
                            ? `Heartbeat — #${item.channel_name}`
                            : item.title}
                        </Text>
                        <View className="flex-row items-center gap-2 mt-0.5">
                          <Text className="text-text-dim text-xs" numberOfLines={1}>
                            {item.bot_name}
                          </Text>
                          {item.type === "heartbeat" && item.interval_minutes && (
                            <Text className="text-text-dim text-xs">
                              every {item.interval_minutes}m
                            </Text>
                          )}
                          {item.type === "task" && item.channel_name && (
                            <Text className="text-text-dim text-xs" numberOfLines={1}>
                              #{item.channel_name}
                            </Text>
                          )}
                          {item.in_quiet_hours && (
                            <View className="flex-row items-center gap-0.5">
                              <Moon size={10} color={t.textDim} style={{ opacity: 0.5 }} />
                              <Text className="text-text-dim text-[10px]">quiet</Text>
                            </View>
                          )}
                        </View>
                      </View>

                      {/* Type badge */}
                      <View
                        className="rounded-full px-2 py-0.5"
                        style={{ backgroundColor: badge.bg }}
                      >
                        <Text style={{ fontSize: 10, fontWeight: "600", color: badge.fg }}>
                          {badge.label}
                        </Text>
                      </View>

                      {/* Time */}
                      <View className="items-end" style={{ minWidth: 52 }}>
                        <Text className="text-text-muted text-xs">
                          {item.scheduled_at ? formatTimeShort(item.scheduled_at) : "—"}
                        </Text>
                        <Text className="text-text-dim text-[10px]">
                          {item.scheduled_at ? relativeTime(item.scheduled_at) : ""}
                        </Text>
                      </View>
                    </Pressable>
                  </Link>
                );
              })}
            </View>
          ))
        )}
      </RefreshableScrollView>
    </View>
  );
}
