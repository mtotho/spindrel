import { useMemo, useState } from "react";
import { View, Text, Pressable } from "react-native";
import { Link, useRouter } from "expo-router";
import { useChannels, useEnsureOrchestrator } from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";
import { useProviders } from "@/src/api/hooks/useProviders";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { prettyIntegrationName } from "@/src/utils/format";
import { useAuthStore } from "@/src/stores/auth";
import {
  Hash,
  Bot,
  Activity,
  Plus,
  Home,
  ChevronRight,
  ChevronDown,
  FileText,
  Sparkles,
  AlertTriangle,
  Lock,
} from "lucide-react";
import type { Channel, BotConfig, PromptTemplate } from "@/src/types/api";

function isOrchestratorChannel(channel: Channel): boolean {
  return channel.client_id === "orchestrator:home";
}

function ChannelCard({ channel, bot, t, isOrchestrator }: {
  channel: Channel;
  bot: { name: string } | undefined;
  t: ReturnType<typeof useThemeTokens>;
  isOrchestrator: boolean;
}) {
  const Icon = isOrchestrator ? Home : channel.private ? Lock : Hash;
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
                      {prettyIntegrationName(b.integration_type)}
                    </Text>
                  ))
                ) : channel.integration ? (
                  <Text className="text-text-dim text-xs bg-surface-overlay px-2 py-0.5 rounded">
                    {prettyIntegrationName(channel.integration)}
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

/** Shown when the user has no channels — surfaces templates as quick-start cards. */
function OnboardingCards({ templates, t }: { templates: PromptTemplate[]; t: ReturnType<typeof useThemeTokens> }) {
  // Show up to 6 templates, sorted with those having integration tags first
  const sorted = [...templates].sort((a, b) => {
    const aInt = (a.tags ?? []).some((tag) => tag.startsWith("integration:"));
    const bInt = (b.tags ?? []).some((tag) => tag.startsWith("integration:"));
    if (aInt && !bInt) return -1;
    if (!aInt && bInt) return 1;
    return 0;
  });
  const shown = sorted.slice(0, 6);

  return (
    <View style={{ gap: 16 }}>
      <View style={{ gap: 4 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Sparkles size={18} color={t.accent} />
          <Text style={{ fontSize: 17, fontWeight: "700", color: t.text }}>
            Create your first channel
          </Text>
        </View>
        <Text style={{ fontSize: 13, color: t.textMuted, lineHeight: 19 }}>
          Pick a template to start with structured files and the right tools, or create a blank channel.
        </Text>
      </View>

      <View style={{ gap: 8 }}>
        {shown.length === 0 && (
          <View style={{ paddingVertical: 8 }}>
            <Activity size={16} color={t.textDim} />
          </View>
        )}
        {shown.map((tpl) => {
          const integrationTags = (tpl.tags ?? []).filter((tag) => tag.startsWith("integration:"));
          return (
            <Link key={tpl.id} href={`/channels/new?templateId=${tpl.id}` as any} asChild>
              <Pressable
                className="border rounded-lg hover:border-accent/40 active:bg-surface-overlay cursor-pointer"
                style={{
                  padding: 14,
                  borderColor: t.surfaceBorder,
                  gap: 4,
                }}
              >
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <FileText size={16} color={t.accent} />
                  <Text style={{ fontSize: 14, fontWeight: "600", color: t.text, flex: 1 }} numberOfLines={1}>
                    {tpl.name}
                  </Text>
                  {integrationTags.length > 0 && (
                    <View style={{ flexDirection: "row", gap: 4 }}>
                      {integrationTags.slice(0, 2).map((tag) => (
                        <View
                          key={tag}
                          style={{
                            backgroundColor: t.success + "15",
                            paddingHorizontal: 6,
                            paddingVertical: 1,
                            borderRadius: 3,
                          }}
                        >
                          <Text style={{ fontSize: 10, color: t.success, fontWeight: "500" }}>
                            {prettyIntegrationName(tag.replace("integration:", ""))}
                          </Text>
                        </View>
                      ))}
                    </View>
                  )}
                  <ChevronRight size={14} color={t.textDim} />
                </View>
                {tpl.description && (
                  <Text style={{ fontSize: 12, color: t.textMuted, marginLeft: 24 }} numberOfLines={1}>
                    {tpl.description}
                  </Text>
                )}
              </Pressable>
            </Link>
          );
        })}

        {/* Blank channel option */}
        <Link href={"/channels/new" as any} asChild>
          <Pressable
            className="border rounded-lg hover:border-accent/40 active:bg-surface-overlay cursor-pointer"
            style={{
              padding: 14,
              borderColor: t.surfaceBorder,
              borderStyle: "dashed" as any,
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
            }}
          >
            <Plus size={16} color={t.textDim} />
            <Text style={{ fontSize: 14, color: t.textMuted, flex: 1 }}>
              Start from scratch
            </Text>
            <ChevronRight size={14} color={t.textDim} />
          </Pressable>
        </Link>
      </View>
    </View>
  );
}

function CategoryCardGroup({ category, channels, botMap, t }: {
  category: string | null;
  channels: Channel[];
  botMap: Map<string, BotConfig>;
  t: ReturnType<typeof useThemeTokens>;
}) {
  const [collapsed, setCollapsed] = useState(false);
  if (channels.length === 0) return null;

  const label = category ? category.toUpperCase() : "CHANNELS";

  return (
    <View style={{ gap: 4 }}>
      <Pressable
        onPress={() => setCollapsed(!collapsed)}
        style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 2 }}
      >
        {category ? (
          collapsed ? (
            <ChevronRight size={14} color={t.textDim} />
          ) : (
            <ChevronDown size={14} color={t.textDim} />
          )
        ) : null}
        <Text style={{ fontSize: 13, fontWeight: "600", color: t.textDim, letterSpacing: 0.5, flex: 1 }}>
          {label}
        </Text>
        <Text style={{ fontSize: 12, color: t.textDim, opacity: 0.5 }}>
          {channels.length}
        </Text>
      </Pressable>
      {!collapsed && channels.map((channel) => (
        <ChannelCard
          key={channel.id}
          channel={channel}
          bot={botMap.get(channel.bot_id)}
          t={t}
          isOrchestrator={false}
        />
      ))}
    </View>
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
  const botMap = useMemo(() => new Map(bots?.map((b) => [b.id, b]) ?? []), [bots]);

  const { data: templates } = usePromptTemplates(undefined, "workspace_schema");
  const { data: providersData, isLoading: providersLoading } = useProviders(isAdmin);
  // Assume providers exist while loading to prevent "no provider" banner flash
  const hasProviders = providersLoading || (providersData?.providers?.length ?? 0) > 0;

  // Separate orchestrator channel from the rest, pin it at top
  const orchestratorChannel = channels?.find(isOrchestratorChannel);
  const otherChannels = useMemo(
    () => channels?.filter((ch) => !isOrchestratorChannel(ch)) ?? [],
    [channels],
  );

  // Group channels by category (same logic as sidebar ChannelList)
  const categoryGroups = useMemo(() => {
    const grouped = new Map<string | null, Channel[]>();
    for (const ch of otherChannels) {
      const cat = ch.category ?? null;
      const list = grouped.get(cat) ?? [];
      list.push(ch);
      grouped.set(cat, list);
    }
    const sorted: { category: string | null; channels: Channel[] }[] = [];
    const namedCategories = [...grouped.keys()].filter((k): k is string => k !== null).sort();
    for (const cat of namedCategories) {
      sorted.push({ category: cat, channels: grouped.get(cat)! });
    }
    const uncategorized = grouped.get(null);
    if (uncategorized?.length) {
      sorted.push({ category: null, channels: uncategorized });
    }
    return sorted;
  }, [otherChannels]);

  const hasCategories = categoryGroups.some((g) => g.category !== null);
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

        {/* No provider banner — shown when no DB providers and no orchestrator */}
        {!channelsLoading && !orchestratorChannel && isAdmin && !hasProviders && (
          <Link href={"/admin/providers" as any} asChild>
            <Pressable
              className="rounded-xl border hover:opacity-90 active:opacity-80 cursor-pointer"
              style={{
                padding: 16,
                borderColor: t.warning + "40",
                backgroundColor: t.warning + "08",
                flexDirection: "row",
                alignItems: "center",
                gap: 12,
              }}
            >
              <AlertTriangle size={20} color={t.warning} />
              <View className="flex-1">
                <Text style={{ fontSize: 14, fontWeight: "600", color: t.text }}>
                  No LLM provider configured
                </Text>
                <Text style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>
                  Add one in Admin &gt; Providers to start chatting.
                </Text>
              </View>
              <ChevronRight size={16} color={t.textDim} />
            </Pressable>
          </Link>
        )}

        {/* Setup options when orchestrator doesn't exist (admin only, has provider) */}
        {!channelsLoading && !orchestratorChannel && isAdmin && hasProviders && (
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
                  {ensureOrchestrator.isPending ? "Setting up..." : "Guided Setup"}
                </Text>
                <Text style={{ fontSize: 13, color: t.textMuted, marginTop: 2 }}>
                  AI-guided walkthrough for creating bots and channels
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
        ) : !hasChannels || otherChannels.length === 0 ? (
          <OnboardingCards templates={templates ?? []} t={t} />
        ) : hasCategories ? (
          <View style={{ gap: 16 }}>
            {categoryGroups.map((group) => (
              <CategoryCardGroup
                key={group.category ?? "__uncategorized"}
                category={group.category}
                channels={group.channels}
                botMap={botMap}
                t={t}
              />
            ))}
          </View>
        ) : (
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
        )}
        </View>
      </RefreshableScrollView>
    </View>
  );
}
