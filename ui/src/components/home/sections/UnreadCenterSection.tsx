import { Link } from "react-router-dom";
import { Check, CheckCheck, Inbox } from "lucide-react";

import { useChannels } from "../../../api/hooks/useChannels";
import { type SessionReadState, useMarkRead, useUnreadState } from "../../../api/hooks/useUnread";
import { unreadStateHref } from "../../../lib/unreadNavigation";
import type { Channel } from "../../../types/api";
import { formatRelativeTime } from "../../../utils/format";
import { SectionHeading } from "./SectionHeading";

function shortId(id: string): string {
  return id.slice(0, 8);
}

function channelNameById(channels: Channel[] | undefined) {
  return new Map((channels ?? []).map((channel) => [channel.id, channel.name]));
}

function sortUnread(states: SessionReadState[]): SessionReadState[] {
  return [...states]
    .filter((state) => state.unread_agent_reply_count > 0)
    .sort((a, b) => {
      const aTime = Date.parse(a.latest_unread_at ?? a.first_unread_at ?? "");
      const bTime = Date.parse(b.latest_unread_at ?? b.first_unread_at ?? "");
      return (Number.isNaN(bTime) ? 0 : bTime) - (Number.isNaN(aTime) ? 0 : aTime);
    });
}

export function UnreadCenterSection() {
  const { data: unread, isLoading, isError } = useUnreadState();
  const { data: channels } = useChannels();
  const markRead = useMarkRead();
  const names = channelNameById(channels);
  const states = sortUnread(unread?.states ?? []);
  const topStates = states.slice(0, 5);
  const total = states.reduce((sum, row) => sum + row.unread_agent_reply_count, 0);

  return (
    <section data-testid="home-unread-center" className="space-y-2" aria-label="Unread center">
      <SectionHeading
        icon={<Inbox size={12} />}
        label="Unread center"
        count={total || undefined}
        action={total ? (
          <button
            type="button"
            className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text"
            disabled={markRead.isPending}
            onClick={() => markRead.mutate({ source: "home_unread_center", surface: "home" })}
          >
            <CheckCheck size={13} />
            Clear
          </button>
        ) : null}
      />
      <div className="rounded-md border border-surface-border bg-surface-raised p-2">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, index) => (
              <div key={index} className="h-14 rounded-md bg-surface-overlay/35" />
            ))}
          </div>
        ) : null}
        {!isLoading && isError ? (
          <div className="px-2 py-3 text-sm text-text-muted">Unread state unavailable.</div>
        ) : null}
        {!isLoading && !isError && topStates.length === 0 ? (
          <div className="flex min-h-[72px] items-center gap-3 px-2 py-3">
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-surface-border bg-surface">
              <CheckCheck size={15} className="text-success" />
            </span>
            <span>
              <span className="block text-sm font-medium text-text">All caught up</span>
              <span className="block text-xs text-text-muted">No unread agent replies.</span>
            </span>
          </div>
        ) : null}
        {!isLoading && !isError && topStates.length ? (
          <div className="space-y-1">
            {topStates.map((row) => {
              const href = unreadStateHref(row);
              const channelName = row.channel_id ? names.get(row.channel_id) ?? "Unknown channel" : "Unknown channel";
              const time = formatRelativeTime(row.latest_unread_at ?? row.first_unread_at);
              const body = (
                <span className="flex min-w-0 flex-1 items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-surface-overlay/45">
                  <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-accent/20 bg-accent/10 text-xs font-semibold text-accent">
                    {row.unread_agent_reply_count}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-text">{channelName}</span>
                    <span className="block truncate text-xs text-text-muted">
                      Session {shortId(row.session_id)}{time ? ` · ${time}` : ""}
                    </span>
                  </span>
                </span>
              );
              return (
                <div key={row.session_id} className="flex items-center gap-1">
                  {href ? <Link to={href} className="min-w-0 flex-1">{body}</Link> : body}
                  <button
                    type="button"
                    className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-overlay hover:text-text"
                    aria-label={`Mark ${channelName} read`}
                    disabled={markRead.isPending}
                    onClick={() => markRead.mutate({ session_id: row.session_id, source: "home_unread_center", surface: "home" })}
                  >
                    <Check size={15} />
                  </button>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </section>
  );
}
