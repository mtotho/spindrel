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

const ICON_MAP: Record<string, React.ComponentType<{ size: number; className?: string }>> = {
  Container, Plug, Lock, Hash, Home, Shield, Moon,
  MessageSquare, Code2, Mail, Camera, LayoutDashboard, Tv, Terminal, MessageCircle,
};
function resolveIcon(name: string): React.ComponentType<{ size: number; className?: string }> {
  return ICON_MAP[name] || Plug;
}

export function ChannelSkeletons() {
  return (
    <div className="flex flex-col gap-0.5 px-2">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="flex flex-row items-center gap-2 px-2 py-1.5">
          <div className="w-3.5 h-3.5 rounded bg-skeleton/[0.04] animate-pulse" />
          <div
            className="h-3 rounded bg-skeleton/[0.04] animate-pulse"
            style={{ width: `${40 + i * 12}%` }}
          />
        </div>
      ))}
    </div>
  );
}

interface ChannelItemProps {
  channel: Channel;
  bot?: BotConfig;
  isStreaming: boolean;
  integrationIcons: Record<string, string>;
}

function ChannelItem({ channel, bot, isStreaming, integrationIcons }: ChannelItemProps) {
  const { pathname } = useLocation();
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const isUnread = useChannelReadStore((s) => s.isUnread);

  const isActive = pathname.includes(channel.id);
  const unread = !isActive && isUnread(channel.id, channel.updated_at);
  const displayName = channel.display_name || channel.name || channel.client_id;

  const IconComp = channel.private ? Lock : Hash;

  // Precedence: streaming > unread > heartbeat-active > heartbeat-quiet-hours > none
  let pip: React.ReactNode = null;
  if (isStreaming) {
    pip = <span aria-label="Streaming" className="w-2 h-2 rounded-full bg-accent shrink-0 animate-pulse inline-block" />;
  } else if (unread) {
    pip = <span aria-label="Unread" className="w-2 h-2 rounded-full bg-accent shrink-0 inline-block" />;
  } else if (channel.heartbeat_enabled && !channel.heartbeat_in_quiet_hours) {
    pip = <span aria-label="Heartbeat active" className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0 opacity-80 inline-block" />;
  } else if (channel.heartbeat_in_quiet_hours) {
    pip = <Moon aria-label="Quiet hours" size={11} className="text-text-dim shrink-0 opacity-50" />;
  }

  // Build a compact tooltip for bot + integration + tag details. Native `title`
  // keeps the row single-line and avoids the overlay covering neighbors.
  const tooltipParts: string[] = [];
  if (bot) tooltipParts.push(bot.name);
  if (channel.integrations?.length) {
    tooltipParts.push(
      channel.integrations
        .map((b) => integrationIcons[b.integration_type] ? b.integration_type : b.integration_type)
        .join(", "),
    );
  }
  if (channel.tags?.length) tooltipParts.push(channel.tags.slice(0, 3).join(", "));
  const tooltip = tooltipParts.length
    ? `${displayName} — ${tooltipParts.join(" · ")}`
    : displayName;

  return (
    <Link to={`/channels/${channel.id}`} onClick={closeMobile} title={tooltip}>
      <div
        className={cn(
          "group relative flex flex-row items-center gap-2 px-3 py-1.5 mx-1 rounded-md cursor-pointer transition-colors",
          "hover:bg-surface-overlay/60 focus-within:bg-surface-overlay/60",
          isActive && "bg-accent/[0.10] before:content-[''] before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:w-[2px] before:h-4 before:rounded-full before:bg-accent",
        )}
      >
        <IconComp
          size={13}
          className={cn(
            "shrink-0",
            isActive ? "text-accent" : "text-text-dim",
          )}
        />
        <span
          className={cn(
            "flex-1 truncate text-[13px]",
            isActive
              ? "text-text font-medium"
              : unread
                ? "text-text font-semibold"
                : "text-text-muted font-normal",
          )}
        >
          {displayName}
        </span>

        {/* Hover-reveal integration glyph strip — inline, no layout shift.
            Only renders on hover of this row, so other rows stay uncluttered. */}
        {channel.integrations && channel.integrations.length > 0 && (
          <span className="hidden group-hover:flex flex-row items-center gap-1 shrink-0">
            {channel.integrations.slice(0, 3).map((binding) => {
              const IIcon = resolveIcon(integrationIcons[binding.integration_type] || "Plug");
              return (
                <IIcon key={binding.id} size={10} className="text-text-dim opacity-70" />
              );
            })}
          </span>
        )}

        {pip}
      </div>
    </Link>
  );
}

interface CategoryGroupProps {
  category: string;
  channels: Channel[];
  botMap: Map<string, BotConfig>;
  integrationIcons: Record<string, string>;
  streamingSet: Set<string>;
  collapsed: boolean;
  onToggle: () => void;
}

function CategoryGroup({
  category,
  channels,
  botMap,
  integrationIcons,
  streamingSet,
  collapsed,
  onToggle,
}: CategoryGroupProps) {
  if (channels.length === 0) return null;

  return (
    <div className="mt-1">
      <button
        onClick={onToggle}
        className="flex flex-row items-center gap-1.5 px-3 py-1 w-full text-left bg-transparent border-none cursor-pointer rounded hover:bg-surface-overlay/40 transition-colors"
      >
        <ChevronRight
          size={11}
          className={cn(
            "text-text-dim transition-transform duration-150",
            !collapsed && "rotate-90",
          )}
        />
        <span className="text-[10px] font-semibold tracking-[0.14em] uppercase text-text-dim/75 flex-1 truncate">
          {category}
        </span>
        <span className="text-[10px] text-text-dim bg-surface-overlay/60 rounded px-1.5 tabular-nums">
          {channels.length}
        </span>
      </button>
      {!collapsed && (
        <div className="pt-0.5 flex flex-col gap-px">
          {channels.map((channel) => (
            <ChannelItem
              key={channel.id}
              channel={channel}
              bot={botMap.get(channel.bot_id)}
              isStreaming={streamingSet.has(channel.id)}
              integrationIcons={integrationIcons}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export interface ChannelListProps {
  channels: Channel[] | undefined;
  channelsLoading: boolean;
  botMap: Map<string, BotConfig>;
  integrationIcons: Record<string, string>;
  streamingSet: Set<string>;
}

export function ChannelList({
  channels,
  channelsLoading,
  botMap,
  integrationIcons,
  streamingSet,
}: ChannelListProps) {
  const regularChannels = useMemo(
    () => channels?.filter((ch) => ch.client_id !== "orchestrator:home") ?? [],
    [channels],
  );

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

  return (
    <div className="px-1 pt-1 pb-1">
      {channelsLoading ? (
        <ChannelSkeletons />
      ) : !hasAnyChannels ? (
        <Link to="/channels/new">
          <div className="flex flex-row items-center gap-1.5 px-2 py-1.5 mx-2 my-1 border border-dashed border-surface-border rounded-md cursor-pointer hover:bg-surface-overlay/40 transition-colors">
            <Plus size={12} className="text-text-dim" />
            <span className="text-[11px] text-text-dim">Create a channel</span>
          </div>
        </Link>
      ) : (
        <div className="flex flex-col gap-px">
          {uncategorized.map((channel) => (
            <ChannelItem
              key={channel.id}
              channel={channel}
              bot={botMap.get(channel.bot_id)}
              isStreaming={streamingSet.has(channel.id)}
              integrationIcons={integrationIcons}
            />
          ))}
          {namedGroups.map((group) => (
            <CategoryGroup
              key={group.category}
              category={group.category}
              channels={group.channels}
              botMap={botMap}
              integrationIcons={integrationIcons}
              streamingSet={streamingSet}
              collapsed={categoryCollapsed[group.category] ?? false}
              onToggle={() => toggleCategory(group.category)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
