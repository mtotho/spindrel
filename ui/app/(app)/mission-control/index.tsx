import { useState } from "react";
import { View, Text, Pressable, useWindowDimensions } from "react-native";
import { Link } from "expo-router";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCOverview,
  useMCPrefs,
  useMCPlans,
  useUpdateMCPrefs,
  useJoinChannel,
  useLeaveChannel,
  type MCChannelOverview,
  type MCBotOverview,
} from "@/src/api/hooks/useMissionControl";
import { useIntegrations } from "@/src/api/hooks/useIntegrations";
import { ReadinessIndicator } from "@/src/components/mission-control/MCEmptyState";
import { botColor } from "@/src/components/mission-control/botColors";
import { DashboardActivityFeed } from "@/src/components/mission-control/DashboardActivityFeed";
import { DashboardTaskProgress } from "@/src/components/mission-control/DashboardTaskProgress";
import { DashboardPlansSummary } from "@/src/components/mission-control/DashboardPlansSummary";
import {
  Hash,
  Bot,
  ClipboardList,
  ClipboardCheck,
  Columns,
  ArrowRight,
  Info,
  ChevronDown,
  ChevronRight,
  Calendar,
  Brain,
  Clock,
  UserPlus,
  UserMinus,
} from "lucide-react";

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
      className="rounded-lg border border-surface-border px-4 py-3"
      style={{ minWidth: 100, flex: 1 }}
    >
      <View className="flex-row items-center gap-2 mb-1">
        <Icon size={14} color={t.textDim} />
        <Text className="text-text-dim" style={{ fontSize: 10, fontWeight: "600", letterSpacing: 0.5, textTransform: "uppercase" }}>
          {label}
        </Text>
      </View>
      <Text style={{ fontSize: 24, fontWeight: "700", color: t.text }}>
        {value}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Channel Card (compact)
// ---------------------------------------------------------------------------
function MemberToggle({
  isMember,
  loading,
  onPress,
}: {
  isMember: boolean;
  loading?: boolean;
  onPress: () => void;
}) {
  const t = useThemeTokens();
  const Icon = isMember ? UserMinus : UserPlus;
  return (
    <Pressable
      onPress={(e: any) => {
        e.stopPropagation?.();
        e.preventDefault?.();
        if (!loading) onPress();
      }}
      hitSlop={6}
      disabled={loading}
      className="flex-row items-center gap-1 rounded-md px-1.5 py-0.5"
      style={{
        backgroundColor: isMember ? t.accent + "14" : "transparent",
        borderWidth: 1,
        borderColor: isMember ? t.accent + "30" : t.textDim + "30",
        opacity: loading ? 0.5 : 1,
      }}
    >
      <Icon size={11} color={isMember ? t.accent : t.textDim} />
      <Text
        style={{
          fontSize: 10,
          fontWeight: "600",
          color: isMember ? t.accent : t.textDim,
        }}
      >
        {isMember ? "Watching" : "Watch"}
      </Text>
    </Pressable>
  );
}

function ChannelCard({
  channel,
  onToggleMember,
  memberLoading,
}: {
  channel: MCChannelOverview;
  onToggleMember?: (channelId: string, isMember: boolean) => void;
  memberLoading?: boolean;
}) {
  const t = useThemeTokens();
  const bc = botColor(channel.bot_id || "default");
  return (
    <Link href={`/channels/${channel.id}` as any} asChild>
      <Pressable
        className="rounded-lg border border-surface-border p-3 hover:bg-surface-overlay active:bg-surface-overlay"
        style={{ gap: 6 }}
      >
        <View className="flex-row items-center gap-2">
          <Hash size={13} color={t.textDim} />
          <Text
            className="text-text font-semibold flex-1"
            numberOfLines={1}
            style={{ fontSize: 13 }}
          >
            {channel.name}
          </Text>
          {channel.task_count > 0 && (
            <Text style={{ fontSize: 10, color: t.accent, fontWeight: "600" }}>
              {channel.task_count} tasks
            </Text>
          )}
          {onToggleMember && (
            <MemberToggle
              isMember={channel.is_member}
              loading={memberLoading}
              onPress={() => onToggleMember(channel.id, channel.is_member)}
            />
          )}
        </View>
        <View className="flex-row items-center gap-2" style={{ paddingLeft: 21 }}>
          <View
            style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: bc.dot }}
          />
          <Text className="text-text-dim" style={{ fontSize: 11 }}>
            {channel.bot_name || channel.bot_id}
          </Text>
          {channel.template_name && (
            <Text className="text-text-dim" style={{ fontSize: 11, opacity: 0.6 }}>
              {channel.template_name}
            </Text>
          )}
          <View style={{ flex: 1 }} />
          <Link
            href={`/mission-control/channel-context/${channel.id}` as any}
            asChild
          >
            <Pressable className="flex-row items-center gap-1">
              <Text style={{ fontSize: 10, color: t.accent }}>Context</Text>
              <ArrowRight size={9} color={t.accent} />
            </Pressable>
          </Link>
        </View>
      </Pressable>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Quick Nav Links
// ---------------------------------------------------------------------------
function QuickNav({ vertical }: { vertical?: boolean }) {
  const t = useThemeTokens();
  const links: { href: string; icon: any; label: string; feature: "kanban" | "journal" | "memory" | "timeline" | "plans" }[] = [
    { href: "/mission-control/kanban", icon: Columns, label: "Kanban", feature: "kanban" },
    { href: "/mission-control/timeline", icon: Clock, label: "Timeline", feature: "timeline" },
    { href: "/mission-control/plans", icon: ClipboardCheck, label: "Plans", feature: "plans" },
    { href: "/mission-control/journal", icon: Calendar, label: "Journal", feature: "journal" },
    { href: "/mission-control/memory", icon: Brain, label: "Memory", feature: "memory" },
  ];
  return (
    <View style={vertical ? { gap: 8 } : { flexDirection: "row", gap: 8 }}>
      {links.map((l) => (
        <Link key={l.href} href={l.href as any} asChild>
          <Pressable
            className="rounded-lg border border-surface-border px-3 py-2.5 hover:bg-surface-overlay"
            style={{ flex: vertical ? undefined : 1, gap: 6 }}
          >
            <View className="flex-row items-center gap-2">
              <l.icon size={14} color={t.accent} />
              <Text style={{ fontSize: 12, fontWeight: "600", color: t.accent }}>
                {l.label}
              </Text>
            </View>
            <ReadinessIndicator feature={l.feature} />
          </Pressable>
        </Link>
      ))}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Scope Toggle (Fleet / Personal)
// ---------------------------------------------------------------------------
function ScopeToggle({
  scope,
  onToggle,
}: {
  scope: "fleet" | "personal";
  onToggle: (s: "fleet" | "personal") => void;
}) {
  const t = useThemeTokens();
  return (
    <View
      className="flex-row rounded-lg border border-surface-border"
      style={{ alignSelf: "flex-start" }}
    >
      {(["fleet", "personal"] as const).map((s) => (
        <Pressable
          key={s}
          onPress={() => onToggle(s)}
          className="px-3 py-1.5"
          style={
            scope === s
              ? { backgroundColor: t.accent + "18", borderRadius: 6 }
              : undefined
          }
        >
          <Text
            style={{
              fontSize: 12,
              fontWeight: scope === s ? "600" : "400",
              color: scope === s ? t.accent : t.textMuted,
            }}
          >
            {s === "fleet" ? "Fleet" : "Personal"}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Integration Status Banner
// ---------------------------------------------------------------------------
function IntegrationBanner() {
  const { data } = useIntegrations();
  const mc = data?.integrations?.find((i) => i.id === "mission_control");
  if (!mc || mc.process_status?.status === "running") return null;

  return (
    <Link href={"/admin/integrations" as any} asChild>
      <Pressable
        className="rounded-xl p-4 flex-row items-center gap-3"
        style={{
          backgroundColor: "rgba(234,179,8,0.12)",
          borderWidth: 1,
          borderColor: "rgba(234,179,8,0.4)",
        }}
      >
        <View
          className="rounded-full items-center justify-center"
          style={{ width: 32, height: 32, backgroundColor: "rgba(234,179,8,0.2)" }}
        >
          <Info size={18} color="#ca8a04" />
        </View>
        <View className="flex-1">
          <Text style={{ fontSize: 14, fontWeight: "700", color: "#ca8a04" }}>
            Dashboard container is not running
          </Text>
          <Text style={{ fontSize: 12, color: "#a16207", marginTop: 2 }}>
            Start it from Integrations to enable the live dashboard.
          </Text>
        </View>
        <View
          className="rounded-md px-3 py-1.5"
          style={{ backgroundColor: "rgba(234,179,8,0.2)" }}
        >
          <Text style={{ fontSize: 12, fontWeight: "700", color: "#ca8a04" }}>
            Start
          </Text>
        </View>
        <ArrowRight size={14} color="#ca8a04" />
      </Pressable>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Bots Section (active bots prominent, inactive collapsed)
// ---------------------------------------------------------------------------
function BotsSection({ bots }: { bots: MCBotOverview[] }) {
  const t = useThemeTokens();
  const [showInactive, setShowInactive] = useState(false);
  const active = bots.filter((b) => b.channel_count > 0);
  const inactive = bots.filter((b) => b.channel_count === 0);

  return (
    <View style={{ gap: 10 }}>
      <Text className="text-text-dim" style={{ fontSize: 10, fontWeight: "700", letterSpacing: 0.8, textTransform: "uppercase" }}>
        BOTS
      </Text>
      {active.map((bot) => {
        const bc = botColor(bot.id);
        return (
          <View
            key={bot.id}
            className="flex-row items-center rounded-lg border border-surface-border px-3 py-2"
            style={{ gap: 8 }}
          >
            <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: bc.dot }} />
            <Text className="text-text font-semibold" style={{ fontSize: 13 }} numberOfLines={1}>
              {bot.name}
            </Text>
            <Text className="text-text-dim" style={{ fontSize: 11 }}>{bot.model}</Text>
            <View style={{ flex: 1 }} />
            <Text style={{ fontSize: 11, color: t.accent, fontWeight: "600" }}>
              {bot.channel_count} ch
            </Text>
          </View>
        );
      })}
      {active.length === 0 && (
        <Text className="text-text-muted" style={{ fontSize: 12 }}>
          No bots have workspace-enabled channels yet.
        </Text>
      )}
      {inactive.length > 0 && (
        <Pressable
          onPress={() => setShowInactive(!showInactive)}
          className="flex-row items-center gap-1"
          style={{ paddingVertical: 4 }}
        >
          {showInactive ? (
            <ChevronDown size={12} color={t.textDim} />
          ) : (
            <ChevronRight size={12} color={t.textDim} />
          )}
          <Text className="text-text-dim" style={{ fontSize: 11 }}>
            {inactive.length} bot{inactive.length !== 1 ? "s" : ""} without workspace channels
          </Text>
        </Pressable>
      )}
      {showInactive && (
        <View style={{ gap: 2, paddingLeft: 4 }}>
          {inactive.map((bot) => {
            const bc = botColor(bot.id);
            return (
              <View key={bot.id} className="flex-row items-center py-1" style={{ gap: 6 }}>
                <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: bc.dot, opacity: 0.5 }} />
                <Text className="text-text-dim" style={{ fontSize: 11 }}>{bot.name}</Text>
                <Text className="text-text-dim" style={{ fontSize: 10, opacity: 0.5 }}>{bot.model}</Text>
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCDashboard() {
  const { data: prefs } = useMCPrefs();
  const updatePrefs = useUpdateMCPrefs();
  const joinChannel = useJoinChannel();
  const leaveChannel = useLeaveChannel();
  const [pendingChannelId, setPendingChannelId] = useState<string | null>(null);
  const scope = ((prefs?.layout_prefs as any)?.scope as "fleet" | "personal") || "fleet";
  const { data, isLoading, error } = useMCOverview(scope);
  const { refreshing, onRefresh } = usePageRefresh([["mc-overview"], ["mc-plans"]]);
  const t = useThemeTokens();
  const { width } = useWindowDimensions();
  const isWide = width >= 1024;

  const handleScopeToggle = (s: "fleet" | "personal") => {
    updatePrefs.mutate({
      layout_prefs: { ...((prefs?.layout_prefs as any) || {}), scope: s },
    });
  };

  const handleToggleMember = (channelId: string, isMember: boolean) => {
    setPendingChannelId(channelId);
    const mutation = isMember ? leaveChannel : joinChannel;
    mutation.mutate(channelId, {
      onSettled: () => setPendingChannelId(null),
    });
  };

  // Plan count for stat card
  const { data: plansData } = useMCPlans(scope);
  const totalPlans = plansData?.plans?.length ?? 0;

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Mission Control"
        subtitle={scope === "personal" ? "My channels" : "Fleet overview"}
        right={<ScopeToggle scope={scope} onToggle={handleScopeToggle} />}
      />
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ paddingLeft: 24, paddingRight: 16, paddingTop: 24, gap: 32, paddingBottom: 48, maxWidth: 1200 }}
      >
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading...</Text>
        ) : error ? (
          <View
            className="rounded-lg p-4"
            style={{ backgroundColor: "rgba(239,68,68,0.06)", borderWidth: 1, borderColor: "rgba(239,68,68,0.15)" }}
          >
            <Text style={{ fontSize: 13, fontWeight: "600", color: "#ef4444" }}>
              Failed to load dashboard
            </Text>
            <Text style={{ fontSize: 12, color: "#dc2626", marginTop: 4 }}>
              {(error as any)?.message || "Check your connection and try again."}
            </Text>
          </View>
        ) : !data ? (
          <Text className="text-text-muted text-sm">No data</Text>
        ) : isWide ? (
          /* Desktop: two-column grid */
          <>
            <IntegrationBanner />

            {/* Stats row */}
            <View className="flex-row flex-wrap gap-3">
              <StatCard label="Channels" value={data.total_channels} icon={Hash} />
              <StatCard label="Bots" value={data.total_bots} icon={Bot} />
              <StatCard label="Tasks" value={data.total_tasks} icon={ClipboardList} />
              <StatCard label="Plans" value={totalPlans} icon={ClipboardCheck} />
            </View>

            <View style={{ flexDirection: "row", gap: 24 }}>
              {/* Left column: 2/3 */}
              <View style={{ flex: 2, gap: 24 }}>
                {/* Task Progress */}
                <DashboardTaskProgress scope={scope} />

                {/* Channels */}
                <View style={{ gap: 10 }}>
                  <Text className="text-text-dim" style={{ fontSize: 10, fontWeight: "700", letterSpacing: 0.8, textTransform: "uppercase" }}>
                    CHANNELS
                  </Text>
                  {data.channels.length > 0 ? (
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
                      {data.channels.map((ch) => (
                        <View key={ch.id} style={{ width: "48%" }}>
                          <ChannelCard
                            channel={ch}
                            onToggleMember={handleToggleMember}
                            memberLoading={pendingChannelId === ch.id}
                          />
                        </View>
                      ))}
                    </View>
                  ) : (
                    <EmptyChannels scope={scope} data={data} onSwitchFleet={() => handleScopeToggle("fleet")} t={t} />
                  )}
                </View>
              </View>

              {/* Right column: 1/3 */}
              <View style={{ flex: 1, gap: 24 }}>
                <QuickNav vertical />
                <DashboardActivityFeed scope={scope} />
                <DashboardPlansSummary scope={scope} />
                <BotsSection bots={data.bots} />
              </View>
            </View>
          </>
        ) : (
          /* Mobile/tablet: stacked */
          <>
            <IntegrationBanner />

            <View className="flex-row flex-wrap gap-3">
              <StatCard label="Channels" value={data.total_channels} icon={Hash} />
              <StatCard label="Bots" value={data.total_bots} icon={Bot} />
              <StatCard label="Tasks" value={data.total_tasks} icon={ClipboardList} />
            </View>

            <QuickNav />

            <DashboardTaskProgress scope={scope} />

            {/* Channels */}
            <View style={{ gap: 10 }}>
              <Text className="text-text-dim" style={{ fontSize: 10, fontWeight: "700", letterSpacing: 0.8, textTransform: "uppercase" }}>
                CHANNELS
              </Text>
              {data.channels.length > 0 ? (
                <View style={{ gap: 8 }}>
                  {data.channels.map((ch) => (
                    <ChannelCard
                      key={ch.id}
                      channel={ch}
                      onToggleMember={handleToggleMember}
                      memberLoading={pendingChannelId === ch.id}
                    />
                  ))}
                </View>
              ) : (
                <EmptyChannels scope={scope} data={data} onSwitchFleet={() => handleScopeToggle("fleet")} t={t} />
              )}
            </View>

            <DashboardActivityFeed scope={scope} />
            <DashboardPlansSummary scope={scope} />
            <BotsSection bots={data.bots} />
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Empty channels helper
// ---------------------------------------------------------------------------
function EmptyChannels({
  scope,
  data,
  onSwitchFleet,
  t,
}: {
  scope: string;
  data: { total_channels_all: number };
  onSwitchFleet: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <View
      className="rounded-lg p-4"
      style={{ backgroundColor: "rgba(107,114,128,0.06)", borderWidth: 1, borderColor: "rgba(107,114,128,0.12)" }}
    >
      {scope === "personal" ? (
        <>
          <Text style={{ fontSize: 13, fontWeight: "600", color: t.text, marginBottom: 4 }}>
            No watched channels
          </Text>
          <Text style={{ fontSize: 12, color: t.textDim, lineHeight: 18 }}>
            Switch to Fleet to see all channels, then click Watch on the ones you want to track here.
          </Text>
          <Pressable
            onPress={onSwitchFleet}
            className="flex-row items-center gap-1 mt-2"
          >
            <Text style={{ fontSize: 12, fontWeight: "600", color: t.accent }}>
              Switch to Fleet
            </Text>
            <ArrowRight size={10} color={t.accent} />
          </Pressable>
        </>
      ) : (
        <>
          <Text style={{ fontSize: 13, fontWeight: "600", color: t.text, marginBottom: 4 }}>
            No workspace-enabled channels
          </Text>
          <Text style={{ fontSize: 12, color: t.textDim, lineHeight: 18 }}>
            {data.total_channels_all > 0
              ? `There are ${data.total_channels_all} channel${data.total_channels_all !== 1 ? "s" : ""}, but none have workspace enabled. `
              : "No channels found. Create a channel first, then "}
            Go to a channel's settings and enable the Workspace tab to track it in Mission Control.
          </Text>
          {data.total_channels_all > 0 && (
            <Link href={"/admin/channels" as any} asChild>
              <Pressable className="flex-row items-center gap-1 mt-2">
                <Text style={{ fontSize: 12, fontWeight: "600", color: t.accent }}>
                  Go to Channels
                </Text>
                <ArrowRight size={10} color={t.accent} />
              </Pressable>
            </Link>
          )}
        </>
      )}
    </View>
  );
}
