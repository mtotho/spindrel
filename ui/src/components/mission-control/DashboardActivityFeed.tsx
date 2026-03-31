import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";
import { useMCTimeline, type MCTimelineEvent } from "@/src/api/hooks/useMissionControl";
import { channelColor } from "./botColors";
import { ArrowRight, Clock } from "lucide-react";

// Inline bold rendering for humanized events
function EventText({ text, t }: { text: string; t: ReturnType<typeof useThemeTokens> }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <Text style={{ fontSize: 12, color: t.text, lineHeight: 17 }} numberOfLines={2}>
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

export function DashboardActivityFeed({ scope }: { scope?: "fleet" | "personal" }) {
  const t = useThemeTokens();
  const { data } = useMCTimeline(7, scope);
  const events = (data?.events || []).slice(0, 5);

  if (events.length === 0) return null;

  return (
    <View style={{ gap: 10 }}>
      <View className="flex-row items-center gap-2">
        <Clock size={12} color={t.textDim} />
        <Text
          className="text-text-dim"
          style={{ fontSize: 10, fontWeight: "700", letterSpacing: 0.8, textTransform: "uppercase" }}
        >
          RECENT ACTIVITY
        </Text>
      </View>

      <View
        className="rounded-xl border border-surface-border"
        style={{ overflow: "hidden" }}
      >
        {events.map((ev, i) => {
          const cc = channelColor(ev.channel_id);
          return (
            <View
              key={`${ev.date}-${ev.time}-${i}`}
              style={{
                flexDirection: "row",
                alignItems: "flex-start",
                gap: 10,
                paddingHorizontal: 14,
                paddingVertical: 10,
                borderBottomWidth: i < events.length - 1 ? 1 : 0,
                borderBottomColor: t.surfaceBorder,
              }}
            >
              <View
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 3,
                  backgroundColor: cc,
                  marginTop: 5,
                }}
              />
              <View style={{ flex: 1 }}>
                <EventText text={ev.event} t={t} />
                <View className="flex-row items-center gap-2 mt-1">
                  <Text style={{ fontSize: 10, color: t.textDim }}>
                    {ev.channel_name}
                  </Text>
                  <Text style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
                    {ev.time}
                  </Text>
                </View>
              </View>
            </View>
          );
        })}
      </View>

      <Link href={"/mission-control/timeline" as any} asChild>
        <Pressable className="flex-row items-center gap-1 self-end">
          <Text style={{ fontSize: 11, fontWeight: "600", color: t.accent }}>
            View all
          </Text>
          <ArrowRight size={10} color={t.accent} />
        </Pressable>
      </Link>
    </View>
  );
}
