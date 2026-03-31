import { View, Text, Pressable } from "react-native";
import { Link, useRouter } from "expo-router";
import { useChannels, useEnsureOrchestrator } from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useAuthStore } from "@/src/stores/auth";
import {
  Hash,
  Bot,
  Activity,
  Plus,
  Home,
  ChevronRight,
} from "lucide-react";
import type { Channel } from "@/src/types/api";

function isOrchestratorChannel(channel: Channel): boolean {
  return channel.client_id === "orchestrator:home";
}

function ChannelCard({ channel, bot, t, isOrchestrator }: {
  channel: Channel;
  bot: { name: string } | undefined;
  t: ReturnType<typeof useThemeTokens>;
  isOrchestrator: boolean;
}) {
  const Icon = isOrchestrator ? Home : Hash;
  return (
    <Link
      href={`/channels/${channel.id}` as any}
      asChild
    >
      <Pressable
        className="bg-surface-raised border rounded-lg flex-row items-center gap-4 hover:border-accent/40 active:bg-surface-overlay cursor-pointer"
        style={{
          padding: 16,
          borderColor: isOrchestrator ? t.accent + "40" : t.surfaceBorder,
        }}
      >
        <View style={{
          width: 44, height: 44, borderRadius: 8,
          backgroundColor: isOrchestrator ? t.accent + "20" : t.accentSubtle,
          alignItems: "center", justifyContent: "center",
        }}>
          <Icon size={22} color={t.accent} />
        </View>
        <View className="flex-1 min-w-0">
          <Text style={{ fontSize: 15, fontWeight: "600", color: t.text }} numberOfLines={1}>
            {channel.display_name || channel.name || channel.client_id}
          </Text>
          <View className="flex-row items-center gap-2 mt-1">
            {isOrchestrator ? (
              <Text style={{ fontSize: 13, color: t.textMuted }}>
                Setup, projects, and system management
              </Text>
            ) : (
              <>
                <Bot size={13} color={t.textMuted} />
                <Text style={{ fontSize: 13, color: t.textMuted }}>
                  {bot?.name ?? channel.bot_id}
                </Text>
                {(channel.integrations?.length ?? 0) > 0 ? (
                  channel.integrations!.map((b) => (
                    <Text key={b.id} className="text-text-dim text-xs bg-surface-overlay px-2 py-0.5 rounded">
                      {b.integration_type}
                    </Text>
                  ))
                ) : channel.integration ? (
                  <Text className="text-text-dim text-xs bg-surface-overlay px-2 py-0.5 rounded">
                    {channel.integration}
                  </Text>
                ) : null}
              </>
            )}
          </View>
        </View>
      </Pressable>
    </Link>
  );
}

export default function HomeScreen() {
  const { data: channels, isLoading: channelsLoading, error: channelsError } = useChannels();
  const { data: bots } = useBots();
  const columns = useResponsiveColumns();
  const { refreshing, onRefresh } = usePageRefresh();
  const t = useThemeTokens();
  const router = useRouter();
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);
  const ensureOrchestrator = useEnsureOrchestrator();
  const botMap = new Map(bots?.map((b) => [b.id, b]) ?? []);

  // Separate orchestrator channel from the rest, pin it at top
  const orchestratorChannel = channels?.find(isOrchestratorChannel);
  const otherChannels = channels?.filter((ch) => !isOrchestratorChannel(ch)) ?? [];

  const hasChannels = (channels?.length ?? 0) > 0;

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Channels"
        subtitle="Select a channel to start chatting"
        right={
          <Link href={"/channels/new" as any} asChild>
            <Pressable
              className="flex-row items-center gap-1.5 bg-accent rounded-lg"
              style={{ paddingHorizontal: 14, paddingVertical: 8 }}
            >
              <Plus size={14} color="#fff" />
              <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>New</Text>
            </Pressable>
          </Link>
        }
      />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1" contentContainerStyle={{ padding: columns === "single" ? 16 : 28 }}>
        <View className="max-w-2xl w-full mx-auto gap-6">

        {/* Orchestrator hero */}
        {!channelsLoading && orchestratorChannel && (
          <Link href={`/channels/${orchestratorChannel.id}` as any} asChild>
            <Pressable
              className="rounded-xl border hover:opacity-90 active:opacity-80 cursor-pointer"
              style={{
                padding: 20,
                borderColor: t.accent + "50",
                backgroundColor: t.accent + "08",
              }}
            >
              <View className="flex-row items-center gap-3">
                <View style={{
                  width: 48, height: 48, borderRadius: 12,
                  backgroundColor: t.accent + "20",
                  alignItems: "center", justifyContent: "center",
                }}>
                  <Home size={24} color={t.accent} />
                </View>
                <View className="flex-1">
                  <Text style={{ fontSize: 17, fontWeight: "700", color: t.text }}>
                    Home
                  </Text>
                  <Text style={{ fontSize: 13, color: t.textMuted, marginTop: 2 }}>
                    Setup, projects, and system management
                  </Text>
                </View>
                <ChevronRight size={18} color={t.textDim} />
              </View>
            </Pressable>
          </Link>
        )}

        {/* Setup orchestrator prompt when it doesn't exist (admin only) */}
        {!channelsLoading && !orchestratorChannel && isAdmin && (
          <Pressable
            onPress={() => {
              ensureOrchestrator.mutate(undefined, {
                onSuccess: (data) => {
                  router.push(`/channels/${data.id}` as any);
                },
              });
            }}
            disabled={ensureOrchestrator.isPending}
            className="rounded-xl border hover:opacity-90 active:opacity-80 cursor-pointer"
            style={{
              padding: 20,
              borderColor: t.surfaceBorder,
              borderStyle: "dashed" as any,
            }}
          >
            <View className="flex-row items-center gap-3">
              <View style={{
                width: 48, height: 48, borderRadius: 12,
                backgroundColor: t.accentSubtle,
                alignItems: "center", justifyContent: "center",
              }}>
                <Home size={24} color={t.textDim} />
              </View>
              <View className="flex-1">
                <Text style={{ fontSize: 17, fontWeight: "700", color: t.text }}>
                  {ensureOrchestrator.isPending ? "Setting up..." : "Set Up Home"}
                </Text>
                <Text style={{ fontSize: 13, color: t.textMuted, marginTop: 2 }}>
                  Create the orchestrator channel for setup, projects, and management
                </Text>
                {ensureOrchestrator.isError && (
                  <Text style={{ fontSize: 12, color: "#ef4444", marginTop: 4 }}>
                    {ensureOrchestrator.error instanceof Error ? ensureOrchestrator.error.message : "Failed to create orchestrator"}
                  </Text>
                )}
              </View>
              <ChevronRight size={18} color={t.textDim} />
            </View>
          </Pressable>
        )}

        {/* Channel list */}
        {channelsError ? (
          <View className="items-center py-12 gap-2">
            <Text className="text-red-400 text-sm font-semibold">Failed to load channels</Text>
            <Text className="text-text-dim text-xs text-center max-w-xs">
              {channelsError instanceof Error ? channelsError.message : "Unknown error"}
            </Text>
          </View>
        ) : channelsLoading ? (
          <View className="items-center py-12">
            <Activity size={24} color={t.textDim} className="animate-spin" />
          </View>
        ) : !hasChannels ? (
          <View className="items-center py-16 gap-3">
            <Hash size={36} color={t.textDim} />
            <Text className="text-text-muted text-base">No channels yet</Text>
            <Text className="text-text-dim text-sm">Create a channel to get started</Text>
          </View>
        ) : otherChannels.length > 0 ? (
          <View className="gap-1">
            <Text style={{ fontSize: 13, fontWeight: "600", color: t.textDim, letterSpacing: 0.5, marginBottom: 4 }}>
              CHANNELS
            </Text>
            {otherChannels.map((channel) => (
              <ChannelCard
                key={channel.id}
                channel={channel}
                bot={botMap.get(channel.bot_id)}
                t={t}
                isOrchestrator={false}
              />
            ))}
          </View>
        ) : null}
        </View>
      </RefreshableScrollView>
    </View>
  );
}
