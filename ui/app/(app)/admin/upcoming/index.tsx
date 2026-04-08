import { useMemo, useState } from "react";
import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import {
  Heart,
  Brain,
  ClipboardList,
  Clock,
  Moon,
  ArrowRight,
  RefreshCw,
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
  memory_hygiene: { bg: "rgba(168,85,247,0.12)", fg: "#9333ea", label: "Dreaming" },
  scheduled: { bg: "rgba(59,130,246,0.12)", fg: "#3b82f6", label: "Scheduled" },
  delegation: { bg: "rgba(168,85,247,0.12)", fg: "#9333ea", label: "Delegation" },
  agent: { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af", label: "Task" },
};

type TypeFilter = "all" | "heartbeat" | "task" | "memory_hygiene";

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
    { key: "memory_hygiene", label: "Dreaming" },
  ];

  return (
    <View style={{ flex: 1, backgroundColor: t.surface }}>
      <MobileHeader title="Upcoming Activity" />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ paddingBottom: 40 }}
      >
        {/* Header */}
        <View style={{ paddingHorizontal: 24, paddingTop: 24, paddingBottom: 12 }}>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
              <Clock size={20} color={t.text} />
              <Text style={{ fontSize: 20, fontWeight: "700", color: t.text }}>
                Upcoming Activity
              </Text>
            </View>
            <Link href={"/admin/tasks" as any} asChild>
              <Pressable
                className="hover:bg-surface-overlay active:bg-surface-overlay"
                style={{ flexDirection: "row", alignItems: "center", gap: 6, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 6 }}
              >
                <Text style={{ fontSize: 14, color: t.accent }}>Tasks</Text>
                <ArrowRight size={14} color={t.accent} />
              </Pressable>
            </Link>
          </View>

          {/* Type filter */}
          <View style={{ flexDirection: "row", gap: 8 }}>
            {FILTERS.map((f) => (
              <Pressable
                key={f.key}
                onPress={() => setTypeFilter(f.key)}
                style={{
                  borderRadius: 999,
                  paddingHorizontal: 12,
                  paddingVertical: 4,
                  backgroundColor: typeFilter === f.key ? t.accentMuted : t.surfaceOverlay,
                }}
              >
                <Text style={{
                  fontSize: 12,
                  fontWeight: "500",
                  color: typeFilter === f.key ? t.accent : t.textMuted,
                }}>
                  {f.label}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>

        {/* Content */}
        {isLoading ? (
          <View style={{ paddingHorizontal: 24, gap: 12, paddingTop: 8 }}>
            {[1, 2, 3, 4].map((i) => (
              <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12 }}>
                <View className="animate-pulse" style={{ width: 18, height: 18, borderRadius: 4, backgroundColor: t.skeletonBg }} />
                <View style={{ flex: 1, gap: 6 }}>
                  <View className="animate-pulse" style={{ height: 14, width: `${40 + i * 12}%`, borderRadius: 4, backgroundColor: t.skeletonBg }} />
                  <View className="animate-pulse" style={{ height: 11, width: `${25 + i * 8}%`, borderRadius: 4, backgroundColor: t.skeletonBg }} />
                </View>
              </View>
            ))}
          </View>
        ) : !groups.length ? (
          <View style={{ alignItems: "center", justifyContent: "center", paddingVertical: 64, paddingHorizontal: 24 }}>
            <Clock size={32} color={t.textDim} style={{ opacity: 0.3, marginBottom: 12 }} />
            <Text style={{ fontSize: 14, color: t.textDim }}>No upcoming activity</Text>
          </View>
        ) : (
          groups.map((group) => (
            <View key={group.label} style={{ paddingHorizontal: 16, marginBottom: 8 }}>
              {/* Date header */}
              <View style={{ paddingHorizontal: 8, paddingVertical: 8, marginBottom: 4 }}>
                <Text style={{ fontSize: 12, fontWeight: "600", color: t.textDim, letterSpacing: 0.5 }}>
                  {group.label.toUpperCase()}
                </Text>
              </View>

              {/* Items */}
              {group.items.map((item, idx) => {
                const bc = botColor(item.bot_id);
                const badge = item.type === "heartbeat"
                  ? TYPE_BADGE.heartbeat
                  : item.type === "memory_hygiene"
                    ? TYPE_BADGE.memory_hygiene
                    : TYPE_BADGE[item.task_type || "agent"] || TYPE_BADGE.agent;
                const href = item.type === "heartbeat" && item.channel_id
                  ? `/channels/${item.channel_id}/settings#heartbeat`
                  : item.type === "memory_hygiene"
                    ? `/admin/bots/${item.bot_id}#memory`
                    : item.task_id
                      ? `/admin/tasks/${item.task_id}`
                      : "/admin/tasks";

                return (
                  <Link key={`${item.type}-${idx}`} href={href as any} asChild>
                    <Pressable
                      className="hover:bg-surface-overlay active:bg-surface-overlay"
                      style={{
                        flexDirection: "row",
                        alignItems: "center",
                        gap: 12,
                        borderRadius: 8,
                        paddingHorizontal: 12,
                        paddingVertical: 12,
                      }}
                    >
                      {/* Type icon */}
                      {item.type === "heartbeat" ? (
                        <Heart
                          size={16}
                          color={item.in_quiet_hours ? t.textDim : t.warning}
                          style={item.in_quiet_hours ? { opacity: 0.4 } : undefined}
                        />
                      ) : item.type === "memory_hygiene" ? (
                        <Brain size={16} color="#9333ea" />
                      ) : (
                        <ClipboardList size={16} color={t.accent} />
                      )}

                      {/* Bot dot */}
                      <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: bc.dot, flexShrink: 0 }} />

                      {/* Title + meta */}
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Text style={{ fontSize: 14, color: t.text }} numberOfLines={1}>
                          {item.type === "heartbeat" && item.channel_name
                            ? `Heartbeat — #${item.channel_name}`
                            : item.title}
                        </Text>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 2 }}>
                          <Text style={{ fontSize: 12, color: t.textMuted }} numberOfLines={1}>
                            {item.bot_name}
                          </Text>
                          {item.type === "heartbeat" && item.interval_minutes && (
                            <Text style={{ fontSize: 12, color: t.textDim }}>
                              every {item.interval_minutes}m
                            </Text>
                          )}
                          {item.type === "memory_hygiene" && item.interval_hours && (
                            <Text style={{ fontSize: 12, color: t.textDim }}>
                              every {item.interval_hours}h
                            </Text>
                          )}
                          {item.type === "task" && item.channel_name && (
                            <Text style={{ fontSize: 12, color: t.textDim }} numberOfLines={1}>
                              #{item.channel_name}
                            </Text>
                          )}
                          {item.in_quiet_hours && (
                            <View style={{ flexDirection: "row", alignItems: "center", gap: 2 }}>
                              <Moon size={10} color={t.textDim} style={{ opacity: 0.5 }} />
                              <Text style={{ fontSize: 10, color: t.textDim }}>quiet</Text>
                            </View>
                          )}
                        </View>
                      </View>

                      {/* Recurring indicator + Type badge */}
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                        {(item.recurrence || item.interval_minutes || item.interval_hours) && (
                          <RefreshCw size={12} color={t.textDim} />
                        )}
                        <View style={{
                          borderRadius: 999,
                          paddingHorizontal: 8,
                          paddingVertical: 2,
                          backgroundColor: badge.bg,
                        }}>
                          <Text style={{ fontSize: 10, fontWeight: "600", color: badge.fg }}>
                            {badge.label}
                          </Text>
                        </View>
                      </View>

                      {/* Time */}
                      <View style={{ alignItems: "flex-end", minWidth: 52 }}>
                        <Text style={{ fontSize: 12, color: t.textMuted }}>
                          {item.scheduled_at ? formatTimeShort(item.scheduled_at) : "\u2014"}
                        </Text>
                        <Text style={{ fontSize: 10, color: t.textDim }}>
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
