import { View, Text, Pressable } from "react-native";
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
} from "lucide-react";
import { useUIStore } from "../../../stores/ui";
import { useChannelReadStore } from "../../../stores/channelRead";
import { useThemeTokens } from "../../../theme/tokens";
import type { Channel } from "../../../types/api";
import type { BotConfig } from "../../../types/api";
import { useState, useMemo, useCallback } from "react";

/** Resolve a lucide icon name to a component. */
const ICON_MAP: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  Container, Plug, Lock, Hash, Home, Shield, Moon,
};
function resolveIcon(name: string): React.ComponentType<{ size: number; color: string }> {
  return ICON_MAP[name] || Plug;
}

/** Skeleton loading rows for channels */
export function ChannelSkeletons() {
  const t = useThemeTokens();
  return (
    <View className="gap-1">
      {[1, 2, 3, 4].map((i) => (
        <View key={i} className="flex-row items-center gap-3 px-3 py-2.5">
          <View
            className="rounded animate-pulse"
            style={{ width: 18, height: 18, backgroundColor: t.skeletonBg }}
          />
          <View className="flex-1 gap-1.5">
            <View
              className="rounded animate-pulse"
              style={{
                height: 13,
                width: `${50 + i * 10}%`,
                backgroundColor: t.skeletonBg,
              }}
            />
            <View
              className="rounded animate-pulse"
              style={{
                height: 10,
                width: `${30 + i * 8}%`,
                backgroundColor: t.skeletonBg,
              }}
            />
          </View>
        </View>
      ))}
    </View>
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

  return (
    <Link href={`/channels/${channel.id}` as any} asChild>
      <Pressable
        onPress={closeMobile}
        className={`flex-row items-center gap-2.5 rounded-md px-3 ${channelPy} ${
          isActive ? "bg-accent/10" : "hover:bg-surface-overlay active:bg-surface-overlay"
        }`}
      >
        {channel.private ? (
          <Lock size={mobile ? 20 : 16} color={isActive ? t.accent : t.textDim} />
        ) : (
          <Hash size={mobile ? 20 : 16} color={isActive ? t.accent : t.textDim} />
        )}
        <View className="flex-1 min-w-0">
          <Text
            style={mobile ? { fontSize: 15 } : undefined}
            className={`${mobile ? "" : "text-sm"} ${
              isActive ? "text-accent font-medium" : unread ? "text-text font-semibold" : "text-text-muted"
            }`}
            numberOfLines={1}
          >
            {displayName}
          </Text>
          {bot && (
            <View className="flex-row items-center gap-1">
              <Text className={`${mobile ? "text-xs" : "text-[11px]"} text-text-dim`} numberOfLines={1}>
                {bot.name}
              </Text>
              {channel.channel_workspace_enabled && (
                <Container size={11} color={t.textDim} style={{ opacity: 0.5 }} />
              )}
              {channel.integrations?.map((binding) => {
                const IIcon = resolveIcon(integrationIcons[binding.integration_type] || "Plug");
                return <View key={binding.id} style={{ opacity: 0.6 }}><IIcon size={11} color={t.textDim} /></View>;
              })}
            </View>
          )}
          {channel.tags && channel.tags.length > 0 && (
            <Text className="text-[10px] text-text-dim" numberOfLines={1} style={{ opacity: 0.6 }}>
              {channel.tags.slice(0, 2).join(", ")}
            </Text>
          )}
        </View>
        {isStreaming && (
          <View
            className="animate-pulse"
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: t.accent,
              flexShrink: 0,
            }}
          />
        )}
        {channel.heartbeat_enabled && !channel.heartbeat_in_quiet_hours && !isStreaming && (
          <View
            style={{
              width: 6,
              height: 6,
              borderRadius: 3,
              backgroundColor: "#22c55e",
              flexShrink: 0,
              opacity: 0.8,
            }}
          />
        )}
        {channel.heartbeat_in_quiet_hours && !isStreaming && (
          <Moon size={12} color={t.textDim} style={{ flexShrink: 0, opacity: 0.5 }} />
        )}
        {unread && !isStreaming && (
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: t.accent,
              flexShrink: 0,
            }}
          />
        )}
      </Pressable>
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

  return (
    <View className="px-2 pt-1.5 pb-0.5">
      <Link href={`/channels/${channel.id}` as any} asChild>
        <Pressable
          onPress={closeMobile}
          className={`flex-row items-center gap-2.5 rounded-lg px-3 ${channelPy} ${
            isActive ? "bg-accent/15" : "hover:bg-surface-overlay active:bg-surface-overlay"
          }`}
          style={!isActive ? { backgroundColor: t.accent + "08" } : undefined}
        >
          <Home size={mobile ? 20 : 16} color={isActive ? t.accent : t.text} />
          <Text
            style={mobile ? { fontSize: 15 } : undefined}
            className={`flex-1 ${mobile ? "" : "text-sm"} ${
              isActive ? "text-accent font-medium" : unread ? "text-text font-semibold" : "text-text font-medium"
            }`}
            numberOfLines={1}
          >
            Orchestrator
          </Text>
          <Shield size={12} color={t.textDim} style={{ opacity: 0.6, flexShrink: 0 }} />
          {unread && (
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                backgroundColor: t.accent,
                flexShrink: 0,
              }}
            />
          )}
        </Pressable>
      </Link>
    </View>
  );
}

interface CategoryGroupProps {
  category: string | null;
  channels: Channel[];
  botMap: Map<string, BotConfig>;
  integrationIcons: Record<string, string>;
  mobile?: boolean;
  channelPy: string;
  streamingSet: Set<string>;
}

function CategoryGroup({ category, channels, botMap, integrationIcons, mobile, channelPy, streamingSet }: CategoryGroupProps) {
  const [collapsed, setCollapsed] = useState(false);
  const t = useThemeTokens();

  if (channels.length === 0) return null;

  // Uncategorized channels have no header
  if (!category) {
    return (
      <>
        {channels.map((channel) => (
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
      </>
    );
  }

  return (
    <View>
      <Pressable
        onPress={() => setCollapsed(!collapsed)}
        className="flex-row items-center gap-1.5 px-3 py-1 rounded hover:bg-surface-overlay active:bg-surface-overlay"
      >
        {collapsed ? (
          <ChevronRight size={12} color={t.textDim} />
        ) : (
          <ChevronDown size={12} color={t.textDim} />
        )}
        <Text className="text-text-dim text-[10px] font-semibold tracking-wider flex-1" numberOfLines={1}>
          {category.toUpperCase()}
        </Text>
        <Text className="text-text-dim text-[10px]" style={{ opacity: 0.5 }}>
          {channels.length}
        </Text>
      </Pressable>
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
    </View>
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

  // Group channels by category
  const categoryGroups = useMemo(() => {
    const grouped = new Map<string | null, Channel[]>();
    for (const ch of regularChannels) {
      const cat = ch.category ?? null;
      const list = grouped.get(cat) ?? [];
      list.push(ch);
      grouped.set(cat, list);
    }
    // Sort: named categories alphabetically first, then uncategorized at end
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
  }, [regularChannels]);

  const hasCategories = categoryGroups.some((g) => g.category !== null);

  return (
    <>
      {/* Orchestrator */}
      {!channelsLoading && orchestratorChannel && (
        <OrchestratorItem channel={orchestratorChannel} mobile={mobile} channelPy={channelPy} />
      )}

      {/* Channels */}
      <View className="px-2 py-1.5">
        <View className="flex-row items-center justify-between px-3 mb-1">
          <Text className="text-text-dim text-[11px] font-semibold tracking-wider py-1.5">
            CHANNELS
          </Text>
          <Link href={"/channels/new" as any} asChild>
            <Pressable
              onPress={closeMobile}
              className="items-center justify-center rounded hover:bg-surface-overlay active:bg-surface-overlay"
              style={{ width: 28, height: 28 }}
            >
              <Plus size={14} color={t.textDim} />
            </Pressable>
          </Link>
        </View>

        {channelsLoading ? (
          <ChannelSkeletons />
        ) : hasCategories ? (
          categoryGroups.map((group) => (
            <CategoryGroup
              key={group.category ?? "__uncategorized"}
              category={group.category}
              channels={group.channels}
              botMap={botMap}
              integrationIcons={integrationIcons}
              mobile={mobile}
              channelPy={channelPy}
              streamingSet={streamingSet}
            />
          ))
        ) : (
          <>
            {regularChannels.map((channel) => (
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
            {regularChannels.length === 0 && (
              <Text className="text-text-dim text-xs px-3 py-2">No channels yet</Text>
            )}
          </>
        )}
      </View>
    </>
  );
}
