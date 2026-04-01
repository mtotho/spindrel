import { useState, useMemo } from "react";
import { View, Text, Pressable, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCTimeline,
  useMCPrefs,
  useMCOverview,
  type MCTimelineEvent,
} from "@/src/api/hooks/useMissionControl";
import { MCEmptyState } from "@/src/components/mission-control/MCEmptyState";
import { ChannelFilterBar } from "@/src/components/mission-control/ChannelFilterBar";
import { channelColor } from "@/src/components/mission-control/botColors";
import {
  Calendar,
  Clock,
  Plus,
  ArrowRight,
  CheckCircle,
  ClipboardCheck,
  Circle,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Day filter
// ---------------------------------------------------------------------------
const DAY_OPTIONS = [
  { label: "7d", value: 7 },
  { label: "14d", value: 14 },
  { label: "30d", value: 30 },
  { label: "60d", value: 60 },
];

// ---------------------------------------------------------------------------
// Event type detection from humanized text
// ---------------------------------------------------------------------------
type EventType = "create" | "move" | "complete" | "plan" | "other";

const EVENT_CONFIG: Record<EventType, { icon: typeof Plus; color: string }> = {
  create: { icon: Plus, color: "#22c55e" },
  move: { icon: ArrowRight, color: "#3b82f6" },
  complete: { icon: CheckCircle, color: "#22c55e" },
  plan: { icon: ClipboardCheck, color: "#8b5cf6" },
  other: { icon: Circle, color: "#6b7280" },
};

function detectEventType(text: string): EventType {
  const lower = text.toLowerCase();
  if (lower.includes("was completed")) return "complete";
  if (lower.includes("new task:") || lower.includes("added to")) return "create";
  if (lower.includes("was started") || lower.includes("moved to")) return "move";
  if (lower.includes("plan ")) return "plan";
  return "other";
}

// ---------------------------------------------------------------------------
// Relative date label
// ---------------------------------------------------------------------------
function dateLabel(isoDate: string): string {
  const today = new Date();
  const d = new Date(isoDate + "T00:00:00");
  const diffMs = today.getTime() - d.getTime();
  const diffDays = Math.floor(diffMs / 86_400_000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// ---------------------------------------------------------------------------
// Inline markdown bold rendering
// ---------------------------------------------------------------------------
function EventText({ text, t }: { text: string; t: ReturnType<typeof useThemeTokens> }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <Text style={{ fontSize: 13, color: t.text, lineHeight: 19 }}>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <Text key={i} style={{ fontWeight: "700", color: t.text }}>
              {part.slice(2, -2)}
            </Text>
          );
        }
        return <Text key={i}>{part}</Text>;
      })}
    </Text>
  );
}

// ---------------------------------------------------------------------------
// Event row — card-style with icon and left color tint
// ---------------------------------------------------------------------------
function TimelineEventRow({ event, showChannel }: { event: MCTimelineEvent; showChannel: boolean }) {
  const t = useThemeTokens();
  const cc = channelColor(event.channel_id);
  const evType = detectEventType(event.event);
  const config = EVENT_CONFIG[evType];
  const IconComponent = config.icon;

  return (
    <View
      className="rounded-lg border border-surface-border"
      style={{
        flexDirection: "row",
        overflow: "hidden",
        marginBottom: 6,
      }}
    >
      {/* Left color tint */}
      <View
        style={{
          width: 3,
          backgroundColor: config.color,
        }}
      />

      <View style={{ flex: 1, flexDirection: "row", gap: 10, paddingVertical: 10, paddingHorizontal: 12 }}>
        {/* Icon */}
        <View
          style={{
            width: 28,
            height: 28,
            borderRadius: 14,
            backgroundColor: config.color + "15",
            alignItems: "center",
            justifyContent: "center",
            marginTop: 1,
          }}
        >
          <IconComponent size={14} color={config.color} />
        </View>

        {/* Content */}
        <View style={{ flex: 1, gap: 2 }}>
          <EventText text={event.event} t={t} />
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 2 }}>
            <Text
              style={{
                fontSize: 11,
                fontWeight: "600",
                fontFamily: "monospace",
                color: t.textDim,
              }}
            >
              {event.time}
            </Text>
            {showChannel && (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                <View
                  style={{
                    width: 5,
                    height: 5,
                    borderRadius: 2.5,
                    backgroundColor: cc,
                    opacity: 0.6,
                  }}
                />
                <Text style={{ fontSize: 10, color: t.textDim }}>
                  {event.channel_name}
                </Text>
              </View>
            )}
          </View>
        </View>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Day group
// ---------------------------------------------------------------------------
function DayGroup({
  date,
  events,
  showChannel,
}: {
  date: string;
  events: MCTimelineEvent[];
  showChannel: boolean;
}) {
  const t = useThemeTokens();
  const label = dateLabel(date);
  const isToday = label === "Today";

  return (
    <View style={{ gap: 8 }}>
      {/* Date header */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingHorizontal: 2,
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
            {label}
          </Text>
        </View>
        <Text style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
          {date}
        </Text>
        <Text style={{ fontSize: 10, color: t.textDim }}>
          {events.length} event{events.length !== 1 ? "s" : ""}
        </Text>
        <View style={{ flex: 1, height: 1, backgroundColor: t.surfaceBorder, marginLeft: 4 }} />
      </View>

      {/* Events */}
      <View style={{ gap: 0 }}>
        {events.map((ev, i) => (
          <TimelineEventRow
            key={`${ev.date}-${ev.time}-${i}`}
            event={ev}
            showChannel={showChannel}
          />
        ))}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCTimeline() {
  const [days, setDays] = useState(7);
  const [filterChannel, setFilterChannel] = useState<string | null>(null);
  const { data: prefs } = useMCPrefs();
  const scope = ((prefs?.layout_prefs as any)?.scope as "fleet" | "personal") || "fleet";
  const { data, isLoading } = useMCTimeline(days, scope);
  const { data: overview } = useMCOverview(scope);
  const { refreshing, onRefresh } = usePageRefresh([["mc-timeline"]]);
  const t = useThemeTokens();

  const events = data?.events || [];

  // Get unique channels for filter
  const channels = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of events) map.set(e.channel_id, e.channel_name);
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [events]);

  // Apply filter
  const filtered = useMemo(
    () => (filterChannel ? events.filter((e) => e.channel_id === filterChannel) : events),
    [events, filterChannel]
  );

  // Group by date
  const grouped = useMemo(() => {
    const map = new Map<string, MCTimelineEvent[]>();
    for (const ev of filtered) {
      const list = map.get(ev.date) || [];
      list.push(ev);
      map.set(ev.date, list);
    }
    return map;
  }, [filtered]);

  const showChannel = !filterChannel && channels.length > 1;

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Timeline"
        subtitle={`Activity feed${filterChannel ? "" : " across channels"}`}
        right={
          <View className="flex-row items-center gap-2">
            <Clock size={14} color={t.textDim} />
            <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "600" }}>
              {filtered.length} events
            </Text>
          </View>
        }
      />

      {/* Filter bar */}
      <View
        className="flex-row items-center gap-2 border-b border-surface-border flex-wrap"
        style={{ paddingLeft: 24, paddingRight: 16, paddingVertical: 8 }}
      >
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

        {/* Channel filter */}
        <ChannelFilterBar
          channels={channels}
          value={filterChannel}
          onChange={setFilterChannel}
        />
      </View>

      {/* Content */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{
          paddingLeft: 24,
          paddingRight: 16,
          paddingTop: 20,
          gap: 24,
          paddingBottom: 48,
          maxWidth: 720,
        }}
      >
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading timeline...</Text>
        ) : filtered.length === 0 ? (
          <MCEmptyState feature="timeline">
            <Text className="text-text-muted text-sm">
              No timeline events in the last {days} days.
              Events are auto-logged when task cards are created or moved.
            </Text>
          </MCEmptyState>
        ) : (
          Array.from(grouped.entries()).map(([date, dayEvents]) => (
            <DayGroup
              key={date}
              date={date}
              events={dayEvents}
              showChannel={showChannel}
            />
          ))
        )}
      </RefreshableScrollView>
    </View>
  );
}
