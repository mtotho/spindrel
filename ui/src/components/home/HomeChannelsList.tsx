import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useChannels, useEnsureOrchestrator } from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { useProviders } from "@/src/api/hooks/useProviders";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { prettyIntegrationName } from "@/src/utils/format";
import { useAuthStore } from "@/src/stores/auth";
import {
  Hash,
  Bot,
  Plus,
  Home,
  ChevronRight,
  ChevronDown,
  Sparkles,
  AlertTriangle,
  Lock,
  LayoutGrid,
} from "lucide-react";
import type { Channel, BotConfig } from "@/src/types/api";

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
    <Link to={`/channels/${channel.id}` as any} style={{ textDecoration: "none", color: "inherit" } as any}>
      <div
        data-testid="channel-row"
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 16,
          padding: 16,
          backgroundColor: t.surfaceRaised,
          border: `1px solid ${isOrchestrator ? t.accent + "40" : t.surfaceBorder}`,
          borderRadius: 8,
          cursor: "pointer",
          transition: "border-color 0.15s",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.borderColor = t.accent + "40"; }}
        onMouseLeave={(e) => { e.currentTarget.style.borderColor = isOrchestrator ? t.accent + "40" : t.surfaceBorder; }}
      >
        <div style={{
          width: 44, height: 44, borderRadius: 8,
          backgroundColor: isOrchestrator ? t.accent + "20" : t.accentSubtle,
          display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
          flexShrink: 0,
        }}>
          <Icon size={22} color={t.accent} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <span style={{
            fontSize: 15, fontWeight: 600, color: t.text, display: "block",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {channel.display_name || channel.name || channel.client_id}
          </span>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4, flexWrap: "wrap" }}>
            {isOrchestrator ? (
              <span style={{ fontSize: 13, color: t.textMuted }}>
                Setup, projects, and system management
              </span>
            ) : (
              <>
                <Bot size={13} color={t.textMuted} />
                <span style={{ fontSize: 13, color: t.textMuted }}>
                  {bot?.name ?? channel.bot_id}
                </span>
                {(channel.integrations?.length ?? 0) > 0 ? (
                  channel.integrations!.map((b) => (
                    <span key={b.id} style={{
                      fontSize: 12, color: t.textDim, backgroundColor: t.surfaceOverlay,
                      padding: "1px 8px", borderRadius: 4,
                    }}>
                      {prettyIntegrationName(b.integration_type)}
                    </span>
                  ))
                ) : channel.integration ? (
                  <span style={{
                    fontSize: 12, color: t.textDim, backgroundColor: t.surfaceOverlay,
                    padding: "1px 8px", borderRadius: 4,
                  }}>
                    {prettyIntegrationName(channel.integration)}
                  </span>
                ) : null}
              </>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}

/** Shown when the user has no channels — simple CTA to create first channel. */
function OnboardingCards({ t }: { t: ReturnType<typeof useThemeTokens> }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Sparkles size={18} color={t.accent} />
          <span style={{ fontSize: 17, fontWeight: 700, color: t.text }}>
            Create your first channel
          </span>
        </div>
        <span style={{ fontSize: 13, color: t.textMuted, lineHeight: "19px" }}>
          Channels are conversations with your bot. Activate integrations to add specialized tools and skills.
        </span>
      </div>

      <Link to={"/channels/new"} style={{ textDecoration: "none", color: "inherit" } as any}>
        <div
          style={{
            padding: 16,
            backgroundColor: t.accent,
            borderRadius: 8,
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            cursor: "pointer",
          }}
        >
          <Plus size={16} color="#fff" />
          <span style={{ fontSize: 14, fontWeight: 600, color: "#fff" }}>
            New Channel
          </span>
        </div>
      </Link>
    </div>
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
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "2px 0",
          background: "none", border: "none", cursor: "pointer", font: "inherit",
          color: "inherit", textAlign: "left",
        }}
      >
        {category ? (
          collapsed ? (
            <ChevronRight size={14} color={t.textDim} />
          ) : (
            <ChevronDown size={14} color={t.textDim} />
          )
        ) : null}
        <span style={{ fontSize: 13, fontWeight: 600, color: t.textDim, letterSpacing: 0.5, flex: 1 }}>
          {label}
        </span>
        <span style={{ fontSize: 12, color: t.textDim, opacity: 0.5 }}>
          {channels.length}
        </span>
      </button>
      {!collapsed && channels.map((channel) => (
        <ChannelCard
          key={channel.id}
          channel={channel}
          bot={botMap.get(channel.bot_id)}
          t={t}
          isOrchestrator={false}
        />
      ))}
    </div>
  );
}

export function HomeChannelsList() {
  const { data: channels, isLoading: channelsLoading, error: channelsError } = useChannels();
  const { data: bots } = useBots();
  const columns = useResponsiveColumns();
  const { refreshing, onRefresh } = usePageRefresh();
  const t = useThemeTokens();
  const navigate = useNavigate();
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);
  const ensureOrchestrator = useEnsureOrchestrator();
  const botMap = useMemo(() => new Map(bots?.map((b) => [b.id, b]) ?? []), [bots]);

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
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", backgroundColor: t.surface }}>
      <PageHeader variant="list"
        title="Channels"
        subtitle="Select a channel to start chatting"
        right={
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
            {columns !== "single" && (
              <Link
                to={"/canvas"}
                title="Open spatial canvas (preview)"
                style={{ textDecoration: "none" } as any}
              >
                <div style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                  border: `1px solid ${t.surfaceBorder}`, borderRadius: 8,
                  padding: "8px 12px", cursor: "pointer", color: t.textDim,
                }}>
                  <LayoutGrid size={14} />
                  <span style={{ fontSize: 13, fontWeight: 600 }}>Canvas</span>
                </div>
              </Link>
            )}
            <Link to={"/channels/new"} style={{ textDecoration: "none" } as any}>
              <div style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                backgroundColor: t.accent, borderRadius: 8,
                padding: "8px 14px", cursor: "pointer",
              }}>
                <Plus size={14} color="#fff" />
                <span style={{ color: "#fff", fontSize: 13, fontWeight: 600 }}>New</span>
              </div>
            </Link>
          </div>
        }
      />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }}>
        <div style={{
          padding: columns === "single" ? 16 : 28,
          maxWidth: 672,
          width: "100%",
          margin: "0 auto",
          boxSizing: "border-box",
          display: "flex",
          flexDirection: "column",
          gap: 24,
        }}>

        {/* Orchestrator hero */}
        {!channelsLoading && orchestratorChannel && (
          <Link to={`/channels/${orchestratorChannel.id}` as any} style={{ textDecoration: "none", color: "inherit" } as any}>
            <div
              style={{
                padding: 20,
                border: `1px solid ${t.accent}50`,
                backgroundColor: t.accent + "08",
                borderRadius: 12,
                cursor: "pointer",
                transition: "opacity 0.15s",
              }}
            >
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 12 }}>
                <div style={{
                  width: 48, height: 48, borderRadius: 12,
                  backgroundColor: t.accent + "20",
                  display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
                  flexShrink: 0,
                }}>
                  <Home size={24} color={t.accent} />
                </div>
                <div style={{ flex: 1 }}>
                  <span style={{ fontSize: 17, fontWeight: 700, color: t.text, display: "block" }}>
                    Home
                  </span>
                  <span style={{ fontSize: 13, color: t.textMuted, marginTop: 2, display: "block" }}>
                    Setup, projects, and system management
                  </span>
                </div>
                <ChevronRight size={18} color={t.textDim} />
              </div>
            </div>
          </Link>
        )}

        {/* No provider banner — shown when no DB providers and no orchestrator */}
        {!channelsLoading && !orchestratorChannel && isAdmin && !hasProviders && (
          <Link to={"/admin/providers"} style={{ textDecoration: "none", color: "inherit" } as any}>
            <div
              style={{
                padding: 16,
                border: `1px solid ${t.warning}40`,
                backgroundColor: t.warning + "08",
                borderRadius: 12,
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                gap: 12,
                cursor: "pointer",
                transition: "opacity 0.15s",
              }}
            >
              <AlertTriangle size={20} color={t.warning} />
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: t.text, display: "block" }}>
                  No LLM provider configured
                </span>
                <span style={{ fontSize: 12, color: t.textMuted, marginTop: 2, display: "block" }}>
                  Add one in Admin &gt; Providers to start chatting.
                </span>
              </div>
              <ChevronRight size={16} color={t.textDim} />
            </div>
          </Link>
        )}

        {/* Setup options when orchestrator doesn't exist (admin only, has provider) */}
        {!channelsLoading && !orchestratorChannel && isAdmin && hasProviders && (
          <button
            type="button"
            onClick={() => {
              ensureOrchestrator.mutate(undefined, {
                onSuccess: (data) => {
                  navigate(`/channels/${data.id}`);
                },
              });
            }}
            disabled={ensureOrchestrator.isPending}
            style={{
              padding: 20,
              border: `1px solid ${t.accent}50`,
              backgroundColor: t.accent + "08",
              borderRadius: 12,
              cursor: ensureOrchestrator.isPending ? "default" : "pointer",
              textAlign: "left",
              font: "inherit",
              color: "inherit",
              transition: "opacity 0.15s",
            }}
          >
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 12 }}>
              <div style={{
                width: 48, height: 48, borderRadius: 12,
                backgroundColor: t.accent + "20",
                display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
                flexShrink: 0,
              }}>
                <Home size={24} color={t.accent} />
              </div>
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 17, fontWeight: 700, color: t.text, display: "block" }}>
                  {ensureOrchestrator.isPending ? "Setting up..." : "Guided Setup"}
                </span>
                <span style={{ fontSize: 13, color: t.textMuted, marginTop: 2, display: "block" }}>
                  AI-guided walkthrough for creating bots and channels
                </span>
                {ensureOrchestrator.isError && (
                  <span style={{ fontSize: 12, color: "#ef4444", marginTop: 4, display: "block" }}>
                    {ensureOrchestrator.error instanceof Error ? ensureOrchestrator.error.message : "Failed to create orchestrator"}
                  </span>
                )}
              </div>
              <ChevronRight size={18} color={t.textDim} />
            </div>
          </button>
        )}

        {/* Channel list */}
        {channelsError ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "48px 0", gap: 8 }}>
            <span style={{ color: "#f87171", fontSize: 14, fontWeight: 600 }}>Failed to load channels</span>
            <span style={{ color: t.textDim, fontSize: 12, textAlign: "center", maxWidth: 256 }}>
              {channelsError instanceof Error ? channelsError.message : "Unknown error"}
            </span>
          </div>
        ) : channelsLoading ? (
          <div style={{ display: "flex", flexDirection: "row", justifyContent: "center", padding: "48px 0" }}>
            <div className="chat-spinner" />
          </div>
        ) : !hasChannels || otherChannels.length === 0 ? (
          <OnboardingCards t={t} />
        ) : hasCategories ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {categoryGroups.map((group) => (
              <CategoryCardGroup
                key={group.category ?? "__uncategorized"}
                category={group.category}
                channels={group.channels}
                botMap={botMap}
                t={t}
              />
            ))}
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: t.textDim, letterSpacing: 0.5, marginBottom: 4 }}>
              CHANNELS
            </span>
            {otherChannels.map((channel) => (
              <ChannelCard
                key={channel.id}
                channel={channel}
                bot={botMap.get(channel.bot_id)}
                t={t}
                isOrchestrator={false}
              />
            ))}
          </div>
        )}
        </div>
      </RefreshableScrollView>
    </div>
  );
}
