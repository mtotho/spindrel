/**
 * ChannelPicker — searchable channel selector with integration groups.
 */
import { useMemo } from "react";
import { Hash, Users } from "lucide-react";
import type { Channel, BotConfig } from "@/src/types/api";
import { SelectDropdown, type SelectDropdownOption } from "./SelectDropdown";

function humanizeIntegration(s: string): string {
  const SPECIAL: Record<string, string> = {
    bluebubbles: "Blue Bubbles",
    homeassistant: "Home Assistant",
    web_search: "Web Search",
  };
  if (SPECIAL[s]) return SPECIAL[s];
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function channelTypeKey(ch: Channel): string {
  return ch.integration || "direct";
}

function channelTypeLabel(key: string): string {
  if (key === "direct") return "Direct";
  return humanizeIntegration(key);
}

function channelDisplayName(ch: Channel): string {
  return ch.display_name || ch.name;
}

interface ChannelOption extends SelectDropdownOption {
  channel?: Channel;
  primaryBot?: BotConfig;
  memberCount?: number;
}

export function ChannelPicker({ value, onChange, channels, bots, allowNone, placeholder, disabled }: {
  value: string;
  onChange: (channelId: string) => void;
  channels: Channel[];
  bots?: BotConfig[];
  allowNone?: boolean;
  placeholder?: string;
  disabled?: boolean;
}) {
  const botMap = useMemo(() => {
    const m = new Map<string, BotConfig>();
    for (const bot of bots ?? []) m.set(bot.id, bot);
    return m;
  }, [bots]);

  const options = useMemo<ChannelOption[]>(() => {
    const mapped = channels.map((channel) => {
      const type = channelTypeKey(channel);
      const primaryBot = botMap.get(channel.bot_id);
      const memberCount = channel.member_bots?.length ?? 0;
      return {
        value: String(channel.id),
        label: channelDisplayName(channel),
        group: type,
        groupLabel: channelTypeLabel(type),
        description: primaryBot ? primaryBot.name : undefined,
        meta: channel.category,
        searchText: `${channelDisplayName(channel)} ${channel.name} ${channel.client_id ?? ""} ${channel.category ?? ""} ${primaryBot?.name ?? ""} ${channelTypeLabel(type)}`,
        channel,
        primaryBot,
        memberCount,
      };
    });
    if (!allowNone) return mapped;
    return [{ value: "", label: "None", searchText: "none no channel" }, ...mapped];
  }, [allowNone, botMap, channels]);

  return (
    <SelectDropdown
      value={value}
      onChange={(next) => onChange(next)}
      options={options}
      placeholder={value === "" && allowNone ? "None" : (placeholder ?? "Select channel...")}
      disabled={disabled}
      searchable
      searchPlaceholder="Search channels..."
      emptyLabel="No channels found"
      popoverWidth="content"
      leadingIcon={<Hash size={14} className="shrink-0 text-text-dim" />}
      renderValue={(option) => {
        const channel = (option as ChannelOption).channel;
        if (!channel) return <span className="italic text-text-dim">None</span>;
        return (
          <span className="flex min-w-0 items-center gap-2">
            <Hash size={14} className="shrink-0 text-text-dim" />
            <span className="min-w-0 flex-1 truncate text-text">{channelDisplayName(channel)}</span>
            {channel.integration && (
              <span className="shrink-0 rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-text-dim">
                {humanizeIntegration(channel.integration)}
              </span>
            )}
          </span>
        );
      }}
      renderOption={(option, state) => {
        const channel = (option as ChannelOption).channel;
        if (!channel) return <span className="text-[12px] italic text-text-dim">None</span>;
        const primaryBot = (option as ChannelOption).primaryBot;
        const memberCount = channel.member_bots?.length ?? 0;
        return (
          <>
            <Hash size={14} className={`mt-0.5 shrink-0 ${state.selected ? "text-accent" : "text-text-dim"}`} />
            <span className="min-w-0 flex-1">
              <span className={`block truncate text-[12px] font-medium ${state.selected ? "text-accent" : "text-text"}`}>
                {channelDisplayName(channel)}
              </span>
              <span className="mt-0.5 flex min-w-0 items-center gap-2 text-[10px] text-text-dim">
                {primaryBot && <span className="truncate">{primaryBot.name}</span>}
                {memberCount > 1 && (
                  <span className="inline-flex shrink-0 items-center gap-0.5">
                    <Users size={9} />
                    {memberCount}
                  </span>
                )}
                {channel.integration && <span className="shrink-0">{humanizeIntegration(channel.integration)}</span>}
              </span>
            </span>
            {channel.category && (
              <span className="shrink-0 rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-text-dim">
                {channel.category}
              </span>
            )}
          </>
        );
      }}
    />
  );
}
