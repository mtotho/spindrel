import { Link, useLocation } from "react-router-dom";
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
import { cn } from "../../../lib/cn";
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
const ICON_MAP: Record<string, React.ComponentType<{ size: number; className?: string }>> = {
  Container, Plug, Lock, Hash, Home, Shield, Moon,
  MessageSquare, Code2, Mail, Camera, LayoutDashboard, Tv, Terminal, MessageCircle,
};
function resolveIcon(name: string): React.ComponentType<{ size: number; className?: string }> {
  return ICON_MAP[name] || Plug;
}

/** Skeleton loading rows for channels */
export function ChannelSkeletons() {
  return (
    <div className="flex flex-col gap-1">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="flex flex-row items-center gap-3 px-3 py-2.5">
          <div className="w-[18px] h-[18px] rounded bg-skeleton/[0.04] animate-pulse" />
          <div className="flex-1 flex flex-col gap-1.5">
            <div
              className="h-[13px] rounded bg-skeleton/[0.04] animate-pulse"
              style={{ width: `${50 + i * 10}%` }}
            />
            <div
              className="h-[10px] rounded bg-skeleton/[0.04] animate-pulse"
              style={{ width: `${30 + i * 8}%` }}
            />
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
  isStreaming: boolean;
  integrationIcons: Record<string, string>;
}

function ChannelItem({ channel, bot, mobile, isStreaming, integrationIcons }: ChannelItemProps) {
  const { pathname } = useLocation();
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const isUnread = useChannelReadStore((s) => s.isUnread);

  const isActive = pathname.includes(channel.id);
  const unread = !isActive && isUnread(channel.id, channel.updated_at);
  const displayName = channel.display_name || channel.name || channel.client_id;

  const IconComp = channel.private ? Lock : Hash;

  return (
    <Link to={`/channels/${channel.id}`} onClick={closeMobile}>
      <div
        className={cn(
          "sidebar-nav-item flex flex-row items-center gap-2.5 px-3 rounded-md cursor-pointer relative",
          mobile ? "py-3" : "py-2",
          isActive && "sidebar-item-active",
        )}
      >
        <IconComp
          size={mobile ? 18 : 14}
          className={isActive ? "text-accent" : "text-text-dim"}
        />
        <div className="flex-1 min-w-0 flex flex-col">
          <span
            className={cn(
              "truncate",
              mobile ? "text-[15px]" : "text-[13px]",
              isActive ? "text-text font-medium" : unread ? "text-text font-semibold" : "text-text-muted font-normal",
            )}
          >
            {displayName}
          </span>
          {bot && (
            <div className="flex flex-row items-center gap-1">
              <span
                className={cn(
                  "text-text-dim truncate",
                  mobile ? "text-xs" : "text-[11px]",
                )}
              >
                {bot.name}
              </span>
              {channel.channel_workspace_enabled && (
                <Container size={11} className="text-text-dim opacity-50" />
              )}
              {channel.integrations?.map((binding) => {
                const IIcon = resolveIcon(integrationIcons[binding.integration_type] || "Plug");
                return (
                  <span key={binding.id} className="opacity-60">
                    <IIcon size={11} className="text-text-dim" />
                  </span>
                );
              })}
            </div>
          )}
          {channel.tags && channel.tags.length > 0 && (
            <span className="text-[10px] text-text-dim opacity-60 truncate">
              {channel.tags.slice(0, 2).join(", ")}
            </span>
          )}
        </div>
        {isStreaming && (
          <span className="w-2 h-2 rounded-full bg-accent shrink-0 animate-pulse inline-block" />
        )}
        {channel.heartbeat_enabled && !channel.heartbeat_in_quiet_hours && !isStreaming && (
          <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0 opacity-80 inline-block" />
        )}
        {channel.heartbeat_in_quiet_hours && !isStreaming && (
          <Moon size={12} className="text-text-dim shrink-0 opacity-50" />
        )}
        {unread && !isStreaming && (
          <span className="w-2 h-2 rounded-full bg-accent shrink-0 inline-block" />
        )}
      </div>
    </Link>
  );
}

function OrchestratorItem({ channel, mobile }: { channel: Channel; mobile?: boolean }) {
  const { pathname } = useLocation();
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const isUnread = useChannelReadStore((s) => s.isUnread);

  const isActive = pathname.includes(channel.id);
  const unread = !isActive && isUnread(channel.id, channel.updated_at);

  return (
    <div className="px-3 pt-2 pb-1">
      <Link to={`/channels/${channel.id}`} onClick={closeMobile}>
        <div
          className={cn(
            "sidebar-nav-item flex flex-row items-center gap-2.5 px-3 rounded-lg cursor-pointer",
            mobile ? "py-3" : "py-2",
            isActive && "bg-accent/15",
          )}
        >
          <Home
            size={mobile ? 18 : 14}
            className={isActive ? "text-accent" : "text-text"}
          />
          <span
            className={cn(
              "flex-1 truncate",
              mobile ? "text-[15px]" : "text-sm",
              isActive || !unread ? "font-medium" : "font-semibold",
              isActive ? "text-accent" : "text-text",
            )}
          >
            Orchestrator
          </span>
          <Shield size={12} className="text-text-dim opacity-60 shrink-0" />
          {unread && (
            <span className="w-2 h-2 rounded-full bg-accent shrink-0 inline-block" />
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
  streamingSet,
  collapsed,
  onToggle,
}: CategoryGroupProps) {
  if (channels.length === 0) return null;

  return (
    <div>
      <button
        onClick={onToggle}
        className="sidebar-nav-item flex flex-row items-center gap-1.5 px-3 py-2 mt-2 rounded w-full text-left bg-transparent border-none cursor-pointer"
      >
        {collapsed ? (
          <ChevronRight size={12} className="text-text-dim" />
        ) : (
          <ChevronDown size={12} className="text-text-dim" />
        )}
        <span className="sidebar-section-label flex-1 truncate py-0 my-0">
          {category.toUpperCase()}
        </span>
        <span className="text-[10px] text-text-dim opacity-60">
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
  streamingSet: Set<string>;
}

export function ChannelList({
  channels,
  channelsLoading,
  botMap,
  integrationIcons,
  mobile,
  streamingSet,
}: ChannelListProps) {
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);

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
        <OrchestratorItem channel={orchestratorChannel} mobile={mobile} />
      )}

      {/* Channels */}
      <div className="px-3 pt-4 pb-1">
        <div className="flex flex-row items-center justify-between px-0 mb-2 group">
          <span className="sidebar-section-label">
            CHANNELS
          </span>
          <Link to={"/channels/new"} onClick={closeMobile}>
            <div className="sidebar-icon-btn w-7 h-7 rounded flex flex-row items-center justify-center cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity duration-200">
              <Plus size={14} className="text-text-dim" />
            </div>
          </Link>
        </div>

        {channelsLoading ? (
          <ChannelSkeletons />
        ) : !hasAnyChannels ? (
          <Link to={"/channels/new"}>
            <div className="sidebar-nav-item flex flex-row items-center gap-1.5 px-2 py-1.5 mx-2 my-1 border border-dashed border-surface-border rounded-md cursor-pointer">
              <Plus size={12} className="text-text-dim" />
              <span className="text-[11px] text-text-dim">Create a channel</span>
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
                isStreaming={streamingSet.has(channel.id)}
                integrationIcons={integrationIcons}
              />
            ))}
            {showDivider && (
              <div className="hidden" />
            )}
            {namedGroups.map((group) => (
              <CategoryGroup
                key={group.category}
                category={group.category}
                channels={group.channels}
                botMap={botMap}
                integrationIcons={integrationIcons}
                mobile={mobile}
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
