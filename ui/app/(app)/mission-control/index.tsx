import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCOverview,
  type MCChannelOverview,
  type MCBotOverview,
} from "@/src/api/hooks/useMissionControl";
import { useIntegrations } from "@/src/api/hooks/useIntegrations";
import {
  Hash,
  Bot,
  ClipboardList,
  Columns,
  ArrowRight,
  Info,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Bot color palette
// ---------------------------------------------------------------------------
const BOT_COLORS = [
  { bg: "rgba(59,130,246,0.12)", dot: "#3b82f6" },
  { bg: "rgba(168,85,247,0.12)", dot: "#a855f7" },
  { bg: "rgba(236,72,153,0.12)", dot: "#ec4899" },
  { bg: "rgba(34,197,94,0.12)", dot: "#22c55e" },
  { bg: "rgba(6,182,212,0.12)", dot: "#06b6d4" },
  { bg: "rgba(99,102,241,0.12)", dot: "#6366f1" },
];

function botColor(botId: string) {
  let hash = 0;
  for (let i = 0; i < botId.length; i++) {
    hash = ((hash << 5) - hash + botId.charCodeAt(i)) | 0;
  }
  return BOT_COLORS[Math.abs(hash) % BOT_COLORS.length];
}

// ---------------------------------------------------------------------------
// Stat Card
// ---------------------------------------------------------------------------
function StatCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: React.ComponentType<{ size: number; color: string }>;
}) {
  const t = useThemeTokens();
  return (
    <View
      className="rounded-lg border border-surface-border p-4"
      style={{ minWidth: 140, flex: 1 }}
    >
      <View className="flex-row items-center gap-2 mb-2">
        <Icon size={16} color={t.textDim} />
        <Text className="text-text-dim text-xs font-medium tracking-wider uppercase">
          {label}
        </Text>
      </View>
      <Text style={{ fontSize: 28, fontWeight: "700", color: t.text }}>
        {value}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Channel Card
// ---------------------------------------------------------------------------
function ChannelCard({ channel }: { channel: MCChannelOverview }) {
  const t = useThemeTokens();
  const bc = channel.bot_id ? botColor(channel.bot_id) : BOT_COLORS[0];
  return (
    <Link href={`/channels/${channel.id}` as any} asChild>
      <Pressable className="rounded-lg border border-surface-border p-4 hover:bg-surface-overlay active:bg-surface-overlay">
        <View className="flex-row items-center gap-2 mb-2">
          <Hash size={14} color={t.textDim} />
          <Text
            className="text-text font-semibold flex-1"
            numberOfLines={1}
            style={{ fontSize: 14 }}
          >
            {channel.name}
          </Text>
          {channel.task_count > 0 && (
            <View
              className="rounded-full px-2 py-0.5"
              style={{ backgroundColor: "rgba(99,102,241,0.15)" }}
            >
              <Text style={{ fontSize: 11, color: t.accent, fontWeight: "600" }}>
                {channel.task_count} tasks
              </Text>
            </View>
          )}
        </View>
        <View className="flex-row items-center gap-2">
          {channel.bot_name && (
            <View className="flex-row items-center gap-1">
              <View
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 3,
                  backgroundColor: bc.dot,
                }}
              />
              <Text className="text-text-dim text-xs">{channel.bot_name}</Text>
            </View>
          )}
          {channel.template_name && (
            <Text className="text-text-dim text-xs" style={{ opacity: 0.7 }}>
              {channel.template_name}
            </Text>
          )}
        </View>
        <View className="flex-row items-center gap-3 mt-2">
          <Link
            href={`/mission-control/channel-context/${channel.id}` as any}
            asChild
          >
            <Pressable className="flex-row items-center gap-1">
              <Text style={{ fontSize: 11, color: t.accent }}>Context</Text>
              <ArrowRight size={10} color={t.accent} />
            </Pressable>
          </Link>
        </View>
      </Pressable>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Bot Card
// ---------------------------------------------------------------------------
function BotCard({ bot }: { bot: MCBotOverview }) {
  const t = useThemeTokens();
  const bc = botColor(bot.id);
  return (
    <View className="rounded-lg border border-surface-border p-4">
      <View className="flex-row items-center gap-2 mb-1">
        <View
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            backgroundColor: bc.dot,
          }}
        />
        <Text className="text-text font-semibold text-sm" numberOfLines={1}>
          {bot.name}
        </Text>
      </View>
      <Text className="text-text-dim text-xs">{bot.model}</Text>
      <View className="flex-row items-center gap-3 mt-2">
        <Text className="text-text-muted text-xs">
          {bot.channel_count} channel{bot.channel_count !== 1 ? "s" : ""}
        </Text>
        {bot.memory_scheme && (
          <Text className="text-text-dim text-xs" style={{ opacity: 0.7 }}>
            {bot.memory_scheme}
          </Text>
        )}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Integration Status Banner
// ---------------------------------------------------------------------------
function IntegrationBanner() {
  const t = useThemeTokens();
  const { data } = useIntegrations();
  const mc = data?.integrations?.find((i) => i.id === "mission_control");
  if (!mc || mc.process_status?.status === "running") return null;

  return (
    <Link href={"/admin/integrations" as any} asChild>
      <Pressable
        className="rounded-lg p-3 flex-row items-center gap-2"
        style={{ backgroundColor: "rgba(59,130,246,0.08)", borderWidth: 1, borderColor: "rgba(59,130,246,0.2)" }}
      >
        <Info size={14} color="#3b82f6" />
        <Text style={{ fontSize: 13, color: "#3b82f6", flex: 1 }}>
          Dashboard container is not running.
        </Text>
        <Text style={{ fontSize: 12, color: "#3b82f6", fontWeight: "600" }}>
          Manage
        </Text>
        <ArrowRight size={12} color="#3b82f6" />
      </Pressable>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCDashboard() {
  const { data, isLoading } = useMCOverview();
  const { refreshing, onRefresh } = usePageRefresh([["mc-overview"]]);
  const t = useThemeTokens();

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Mission Control" subtitle="Fleet overview" />
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ padding: 16, gap: 20, paddingBottom: 40 }}
      >
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading...</Text>
        ) : !data ? (
          <Text className="text-text-muted text-sm">No data</Text>
        ) : (
          <>
            {/* Integration status */}
            <IntegrationBanner />

            {/* Stats */}
            <View className="flex-row flex-wrap gap-3">
              <StatCard
                label="Channels"
                value={data.total_channels}
                icon={Hash}
              />
              <StatCard
                label="Bots"
                value={data.total_bots}
                icon={Bot}
              />
              <StatCard
                label="Tasks"
                value={data.total_tasks}
                icon={ClipboardList}
              />
            </View>

            {/* Quick links */}
            <View className="flex-row gap-3">
              <Link href={"/mission-control/kanban" as any} asChild>
                <Pressable className="flex-row items-center gap-2 rounded-lg border border-surface-border px-4 py-3 hover:bg-surface-overlay flex-1">
                  <Columns size={16} color={t.accent} />
                  <Text className="text-accent font-medium text-sm">
                    Open Kanban
                  </Text>
                </Pressable>
              </Link>
            </View>

            {/* Channels grid */}
            <View>
              <Text className="text-text-dim text-xs font-semibold tracking-wider mb-3">
                CHANNELS
              </Text>
              <View className="gap-3">
                {data.channels.map((ch) => (
                  <ChannelCard key={ch.id} channel={ch} />
                ))}
                {data.channels.length === 0 && (
                  <Text className="text-text-muted text-sm">
                    No workspace-enabled channels found
                  </Text>
                )}
              </View>
            </View>

            {/* Bots */}
            <View>
              <Text className="text-text-dim text-xs font-semibold tracking-wider mb-3">
                BOTS
              </Text>
              <View className="gap-3">
                {data.bots.map((bot) => (
                  <BotCard key={bot.id} bot={bot} />
                ))}
              </View>
            </View>
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}
