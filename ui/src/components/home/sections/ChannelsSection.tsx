import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bot, ChevronDown, ChevronRight, Hash, Hash as HashIcon, Lock, Plus, Sparkles } from "lucide-react";

import { useChannels } from "../../../api/hooks/useChannels";
import { useBots } from "../../../api/hooks/useBots";
import { prettyIntegrationName } from "../../../utils/format";
import type { BotConfig, Channel } from "../../../types/api";
import { QuietPill } from "../../shared/SettingsControls";
import { SectionHeading } from "./SectionHeading";

function isOrchestratorChannel(channel: Channel): boolean {
  return channel.client_id === "orchestrator:home";
}

/**
 * Modernized channel list — the centerpiece of the mobile hub. Groups
 * by `channel.category` (matching the sidebar), pins the orchestrator
 * channel into the OnboardingSection above so it doesn't repeat here,
 * and falls back to a "Create your first channel" CTA when the user
 * has no channels yet.
 */
export function ChannelsSection() {
  const { data: channels, isLoading, error } = useChannels();
  const { data: bots } = useBots();
  const botMap = useMemo(
    () => new Map<string, BotConfig>((bots ?? []).map((b) => [b.id, b])),
    [bots],
  );

  const otherChannels = useMemo(
    () => (channels ?? []).filter((ch) => !isOrchestratorChannel(ch)),
    [channels],
  );

  const categoryGroups = useMemo(() => {
    const grouped = new Map<string | null, Channel[]>();
    for (const ch of otherChannels) {
      const cat = ch.category ?? null;
      const list = grouped.get(cat) ?? [];
      list.push(ch);
      grouped.set(cat, list);
    }
    const sorted: { category: string | null; channels: Channel[] }[] = [];
    const named = [...grouped.keys()].filter((k): k is string => k !== null).sort();
    for (const cat of named) sorted.push({ category: cat, channels: grouped.get(cat)! });
    const uncategorized = grouped.get(null);
    if (uncategorized?.length) sorted.push({ category: null, channels: uncategorized });
    return sorted;
  }, [otherChannels]);

  const hasCategories = categoryGroups.some((g) => g.category !== null);

  if (error) {
    return (
      <section className="flex flex-col gap-2">
        <SectionHeading icon={<Hash size={14} />} label="Channels" />
        <div className="rounded-md bg-danger/10 px-3 py-3 text-sm text-danger">
          Failed to load channels
          <div className="mt-1 text-xs text-text-dim">
            {error instanceof Error ? error.message : "Unknown error"}
          </div>
        </div>
      </section>
    );
  }

  if (isLoading) {
    return (
      <section className="flex flex-col gap-2">
        <SectionHeading icon={<Hash size={14} />} label="Channels" />
        <div className="flex items-center justify-center rounded-md bg-surface-raised/40 px-3 py-8">
          <div className="chat-spinner" />
        </div>
      </section>
    );
  }

  if (otherChannels.length === 0) {
    return <FirstChannelCTA />;
  }

  if (!hasCategories) {
    return (
      <section className="flex flex-col gap-2">
        <SectionHeading icon={<Hash size={14} />} label="Channels" count={otherChannels.length} />
        <div className="flex flex-col gap-1">
          {otherChannels.map((ch) => (
            <ChannelRow key={ch.id} channel={ch} bot={botMap.get(ch.bot_id)} />
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-3">
      <SectionHeading icon={<Hash size={14} />} label="Channels" count={otherChannels.length} />
      <div className="flex flex-col gap-3">
        {categoryGroups.map((group) => (
          <CategoryGroup
            key={group.category ?? "__uncategorized"}
            category={group.category}
            channels={group.channels}
            botMap={botMap}
          />
        ))}
      </div>
    </section>
  );
}

function CategoryGroup({
  category,
  channels,
  botMap,
}: {
  category: string | null;
  channels: Channel[];
  botMap: Map<string, BotConfig>;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const label = (category ?? "Uncategorized").toUpperCase();
  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="flex min-h-[24px] items-center gap-1.5 px-1 text-left text-text-dim hover:text-text-muted"
      >
        {category ? (
          collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />
        ) : null}
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em]">{label}</span>
        <span className="ml-auto text-[10px] text-text-dim/70 tabular-nums">{channels.length}</span>
      </button>
      {!collapsed
        ? channels.map((ch) => (
            <ChannelRow key={ch.id} channel={ch} bot={botMap.get(ch.bot_id)} />
          ))
        : null}
    </div>
  );
}

function ChannelRow({ channel, bot }: { channel: Channel; bot: BotConfig | undefined }) {
  const Icon = channel.private ? Lock : HashIcon;
  const integrations = channel.integrations ?? [];
  return (
    <Link
      to={`/channels/${channel.id}`}
      data-testid="channel-row"
      className="group flex min-h-[56px] items-center gap-3 rounded-md bg-surface-raised/40 px-3 py-3 transition-colors hover:bg-surface-overlay/45"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-accent/[0.08] text-accent">
        <Icon size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-text">
          {channel.display_name || channel.name || channel.client_id}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-text-muted">
          <Bot size={11} className="shrink-0 text-text-dim" />
          <span className="truncate">{bot?.name ?? channel.bot_id}</span>
          {integrations.length > 0
            ? integrations.map((b) => (
                <QuietPill key={b.id} label={prettyIntegrationName(b.integration_type)} />
              ))
            : channel.integration
              ? <QuietPill label={prettyIntegrationName(channel.integration)} />
              : null}
        </div>
      </div>
      <ChevronRight
        size={14}
        className="shrink-0 text-text-dim opacity-0 transition-opacity group-hover:opacity-100"
      />
    </Link>
  );
}

function FirstChannelCTA() {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-col gap-1 px-1">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-accent" />
          <span className="text-base font-semibold text-text">Create your first channel</span>
        </div>
        <span className="text-xs text-text-muted">
          Channels are conversations with your bot. Activate integrations to add specialized tools and skills.
        </span>
      </div>
      <Link
        to="/channels/new"
        className="flex items-center justify-center gap-2 rounded-md bg-accent/[0.08] px-4 py-3 text-sm font-medium text-accent transition-colors hover:bg-accent/[0.12]"
      >
        <Plus size={14} />
        New Channel
      </Link>
    </section>
  );
}
