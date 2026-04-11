import { Link, usePathname } from "expo-router";
import {
  Plus,
  Hash,
  Home,
  Lock,
  Shield,
  Moon,
  Container,
  Plug,
  ChevronDown,
  ChevronRight,
  MessageSquare,
  Code2,
  Mail,
  Camera,
  LayoutDashboard,
  Tv,
  Terminal,
  MessageCircle,
} from "lucide-react";
import { useUIStore } from "../../../stores/ui";
import { useChannelReadStore } from "../../../stores/channelRead";
import { useThemeTokens } from "../../../theme/tokens";
import type { Channel } from "../../../types/api";
import type { BotConfig } from "../../../types/api";
import { useCallback, useMemo, useState } from "react";

const CATEGORY_COLLAPSED_STORAGE_KEY = "channel-category-collapsed";

function loadCategoryCollapsed(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(CATEGORY_COLLAPSED_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveCategoryCollapsed(state: Record<string, boolean>) {
  try {
    localStorage.setItem(CATEGORY_COLLAPSED_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

/** Resolve a lucide icon name to a component. */
const ICON_MAP: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  Container, Plug, Lock, Hash, Home, Shield, Moon,
  MessageSquare, Code2, Mail, Camera, LayoutDashboard, Tv, Terminal, MessageCircle,
};
function resolveIcon(name: string): React.ComponentType<{ size: number; color: string }> {
  return ICON_MAP[name] || Plug;
}

/** Skeleton loading rows for channels */
export function ChannelSkeletons() {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {[1, 2, 3, 4].map((i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 12px" }}>
          <div style={{
            width: 18, height: 18, borderRadius: 4,
            backgroundColor: t.skeletonBg,
            animation: "pulse 2s ease-in-out infinite",
          }} />
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{
              height: 13, width: `${50 + i * 10}%`, borderRadius: 4,
              backgroundColor: t.skeletonBg,
              animation: "pulse 2s ease-in-out infinite",
            }} />
            <div style={{
              height: 10, width: `${30 + i * 8}%`, borderRadius: 4,
              backgroundColor: t.skeletonBg,
              animation: "pulse 2s ease-in-out infinite",
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

interface ChannelItemProps {
  channel: Channel;
  bot?: BotConfig;
  mobile?: boolean;
  channelPy: string;
  isStreaming: boolean;
  integrationIcons: Record<string, string>;
}

function ChannelItem({ channel, bot, mobile, channelPy, isStreaming, integrationIcons }: ChannelItemProps) {
  const pathname = usePathname();
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const isUnread = useChannelReadStore((s) => s.isUnread);
  const t = useThemeTokens();

  const isActive = pathname.includes(channel.id);
  const unread = !isActive && isUnread(channel.id, channel.updated_at);
  const displayName = channel.display_name || channel.name || channel.client_id;
  const py = channelPy === "py-3" ? "12px" : "8px";

  return (
    <Link href={`/channels/${channel.id}` as any} onPress={closeMobile}>
      <div
        className="sidebar-nav-item"
        style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: `${py} 12px`, borderRadius: 6, cursor: "pointer",
          backgroundColor: isActive ? "rgba(59,130,246,0.1)" : undefined,
        }}
      >
        {channel.private ? (
          <Lock size={mobile ? 20 : 16} color={isActive ? t.accent : t.textDim} />
        ) : (
          <Hash size={mobile ? 20 : 16} color={isActive ? t.accent : t.textDim} />
        )}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <span style={{
            fontSize: mobile ? 15 : 14,
            color: isActive ? t.accent : unread ? t.text : t.textMuted,
            fontWeight: isActive ? 500 : unread ? 600 : 400,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {displayName}
          </span>
          {bot && (
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{
                fontSize: mobile ? 12 : 11, color: t.textDim,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {bot.name}
              </span>
              {channel.channel_workspace_enabled && (
                <Container size={11} color={t.textDim} style={{ opacity: 0.5 }} />
              )}
              {channel.integrations?.map((binding) => {
                const IIcon = resolveIcon(integrationIcons[binding.integration_type] || "Plug");
                return <span key={binding.id} style={{ opacity: 0.6 }}><IIcon size={11} color={t.textDim} /></span>;
              })}
            </div>
          )}
          {channel.tags && channel.tags.length > 0 && (
            <span style={{ fontSize: 10, color: t.textDim, opacity: 0.6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {channel.tags.slice(0, 2).join(", ")}
            </span>
          )}
        </div>
        {isStreaming && (
          <span style={{
            width: 8, height: 8, borderRadius: 4,
            backgroundColor: t.accent, flexShrink: 0,
            animation: "pulse 2s ease-in-out infinite",
            display: "inline-block",
          }} />
        )}
        {channel.heartbeat_enabled && !channel.heartbeat_in_quiet_hours && !isStreaming && (
          <span style={{
            width: 6, height: 6, borderRadius: 3,
            backgroundColor: "#22c55e", flexShrink: 0, opacity: 0.8,
            display: "inline-block",
          }} />
        )}
        {channel.heartbeat_in_quiet_hours && !isStreaming && (
          <Moon size={12} color={t.textDim} style={{ flexShrink: 0, opacity: 0.5 }} />
        )}
        {unread && !isStreaming && (
          <span style={{
            width: 8, height: 8, borderRadius: 4,
            backgroundColor: t.accent, flexShrink: 0,
            display: "inline-block",
          }} />
        )}
      </div>
    </Link>
  );
}

function OrchestratorItem({ channel, mobile, channelPy }: { channel: Channel; mobile?: boolean; channelPy: string }) {
  const pathname = usePathname();
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const isUnread = useChannelReadStore((s) => s.isUnread);
  const t = useThemeTokens();

  const isActive = pathname.includes(channel.id);
  const unread = !isActive && isUnread(channel.id, channel.updated_at);
  const py = channelPy === "py-3" ? "12px" : "8px";

  return (
    <div style={{ padding: "6px 8px 2px" }}>
      <Link href={`/channels/${channel.id}` as any} onPress={closeMobile}>
        <div
          className="sidebar-nav-item"
          style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: `${py} 12px`, borderRadius: 8, cursor: "pointer",
            backgroundColor: isActive ? "rgba(59,130,246,0.15)" : `${t.accent}08`,
          }}
        >
          <Home size={mobile ? 20 : 16} color={isActive ? t.accent : t.text} />
          <span style={{
            flex: 1,
            fontSize: mobile ? 15 : 14,
            color: isActive ? t.accent : unread ? t.text : t.text,
            fontWeight: isActive || !unread ? 500 : 600,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            Orchestrator
          </span>
          <Shield size={12} color={t.textDim} style={{ opacity: 0.6, flexShrink: 0 }} />
          {unread && (
            <span style={{
              width: 8, height: 8, borderRadius: 4,
              backgroundColor: t.accent, flexShrink: 0,
              display: "inline-block",
            }} />
          )}
        </div>
      </Link>
    </div>
  );
}

interface CategoryGroupProps {
  category: string;
  channels: Channel[];
  botMap: Map<string, BotConfig>;
  integrationIcons: Record<string, string>;
  mobile?: boolean;
  channelPy: string;
  streamingSet: Set<string>;
  collapsed: boolean;
  onToggle: () => void;
}

function CategoryGroup({
  category,
  channels,
  botMap,
  integrationIcons,
  mobile,
  channelPy,
  streamingSet,
  collapsed,
  onToggle,
}: CategoryGroupProps) {
  const t = useThemeTokens();

  if (channels.length === 0) return null;

  return (
    <div>
      <button
        onClick={onToggle}
        className="sidebar-nav-item"
        style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "6px 12px", marginTop: 4, borderRadius: 4,
          background: "none", border: "none", cursor: "pointer",
          width: "100%", textAlign: "left",
        }}
      >
        {collapsed ? (
          <ChevronRight size={12} color={t.textDim} />
        ) : (
          <ChevronDown size={12} color={t.textDim} />
        )}
        <span style={{
          flex: 1, fontSize: 11, fontWeight: 600,
          letterSpacing: 0.5, color: t.textDim,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {category.toUpperCase()}
        </span>
        <span style={{ fontSize: 10, color: t.textDim, opacity: 0.6 }}>
          {channels.length}
        </span>
      </button>
      {!collapsed &&
        channels.map((channel) => (
          <ChannelItem
            key={channel.id}
            channel={channel}
            bot={botMap.get(channel.bot_id)}
            mobile={mobile}
            channelPy={channelPy}
            isStreaming={streamingSet.has(channel.id)}
            integrationIcons={integrationIcons}
          />
        ))}
    </div>
  );
}

export interface ChannelListProps {
  channels: Channel[] | undefined;
  channelsLoading: boolean;
  botMap: Map<string, BotConfig>;
  integrationIcons: Record<string, string>;
  mobile?: boolean;
  channelPy: string;
  streamingSet: Set<string>;
}

export function ChannelList({
  channels,
  channelsLoading,
  botMap,
  integrationIcons,
  mobile,
  channelPy,
  streamingSet,
}: ChannelListProps) {
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const t = useThemeTokens();

  const orchestratorChannel = channels?.find((ch) => ch.client_id === "orchestrator:home");
  const regularChannels = useMemo(
    () => channels?.filter((ch) => ch.client_id !== "orchestrator:home") ?? [],
    [channels],
  );

  // Group channels by category — uncategorized float to the top so they
  // don't visually merge into the trailing named category.
  const { uncategorized, namedGroups } = useMemo(() => {
    const byCategory = new Map<string, Channel[]>();
    const loose: Channel[] = [];
    for (const ch of regularChannels) {
      const cat = ch.category ?? null;
      if (cat === null) {
        loose.push(ch);
      } else {
        const list = byCategory.get(cat) ?? [];
        list.push(ch);
        byCategory.set(cat, list);
      }
    }
    const namedCategories = [...byCategory.keys()].sort();
    return {
      uncategorized: loose,
      namedGroups: namedCategories.map((cat) => ({ category: cat, channels: byCategory.get(cat)! })),
    };
  }, [regularChannels]);

  const [categoryCollapsed, setCategoryCollapsed] = useState<Record<string, boolean>>(
    () => loadCategoryCollapsed(),
  );

  const toggleCategory = useCallback((category: string) => {
    setCategoryCollapsed((prev) => {
      const next = { ...prev, [category]: !prev[category] };
      saveCategoryCollapsed(next);
      return next;
    });
  }, []);

  const hasAnyChannels = regularChannels.length > 0;
  const showDivider = uncategorized.length > 0 && namedGroups.length > 0;

  return (
    <>
      {/* Orchestrator */}
      {!channelsLoading && orchestratorChannel && (
        <OrchestratorItem channel={orchestratorChannel} mobile={mobile} channelPy={channelPy} />
      )}

      {/* Channels */}
      <div style={{ padding: "6px 8px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 12px", marginBottom: 4 }}>
          <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.5, color: t.textDim, padding: "6px 0" }}>
            CHANNELS
          </span>
          <Link href={"/channels/new" as any} onPress={closeMobile}>
            <div
              className="sidebar-icon-btn"
              style={{
                width: 28, height: 28, borderRadius: 4,
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer",
              }}
            >
              <Plus size={14} color={t.textDim} />
            </div>
          </Link>
        </div>

        {channelsLoading ? (
          <ChannelSkeletons />
        ) : !hasAnyChannels ? (
          <Link href={"/channels/new" as any}>
            <div
              className="sidebar-nav-item"
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "6px 8px", margin: "4px 8px",
                border: `1px dashed ${t.surfaceBorder}`,
                borderRadius: 6, cursor: "pointer",
              }}
            >
              <Plus size={12} color={t.textDim} />
              <span style={{ fontSize: 11, color: t.textDim }}>Create a channel</span>
            </div>
          </Link>
        ) : (
          <>
            {/* Uncategorized channels render first so they don't visually
                bleed into the trailing named category. */}
            {uncategorized.map((channel) => (
              <ChannelItem
                key={channel.id}
                channel={channel}
                bot={botMap.get(channel.bot_id)}
                mobile={mobile}
                channelPy={channelPy}
                isStreaming={streamingSet.has(channel.id)}
                integrationIcons={integrationIcons}
              />
            ))}
            {showDivider && (
              <div
                style={{
                  height: 1,
                  backgroundColor: t.surfaceBorder,
                  opacity: 0.6,
                  margin: "8px 12px 4px",
                }}
              />
            )}
            {namedGroups.map((group) => (
              <CategoryGroup
                key={group.category}
                category={group.category}
                channels={group.channels}
                botMap={botMap}
                integrationIcons={integrationIcons}
                mobile={mobile}
                channelPy={channelPy}
                streamingSet={streamingSet}
                collapsed={categoryCollapsed[group.category] ?? false}
                onToggle={() => toggleCategory(group.category)}
              />
            ))}
          </>
        )}
      </div>
    </>
  );
}
