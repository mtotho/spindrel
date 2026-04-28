import { Link } from "react-router-dom";
import { Check, CheckCheck, Hash, Inbox, Loader2, X } from "lucide-react";
import { useMemo } from "react";
import { useChannels } from "../../../api/hooks/useChannels";
import { useMarkRead, useUnreadState, type SessionReadState } from "../../../api/hooks/useUnread";
import { cn } from "../../../lib/cn";
import { unreadStateHref } from "../../../lib/unreadNavigation";

interface UnreadInboxPanelProps {
  onClose: () => void;
}

function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value;
}

function formatRelative(value: string | null): string {
  if (!value) return "";
  const ts = new Date(value).getTime();
  if (!Number.isFinite(ts)) return "";
  const deltaMs = Date.now() - ts;
  if (deltaMs < 60_000) return "now";
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function sortUnreadRows(a: SessionReadState, b: SessionReadState): number {
  const at = new Date(a.latest_unread_at ?? a.first_unread_at ?? 0).getTime();
  const bt = new Date(b.latest_unread_at ?? b.first_unread_at ?? 0).getTime();
  return bt - at;
}

export function UnreadInboxPanel({ onClose }: UnreadInboxPanelProps) {
  const { data, isLoading } = useUnreadState();
  const { data: channels } = useChannels();
  const markRead = useMarkRead();

  const channelNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const channel of channels ?? []) m.set(channel.id, channel.name);
    return m;
  }, [channels]);

  const unreadRows = useMemo(
    () =>
      [...(data?.states ?? [])]
        .filter((state) => state.unread_agent_reply_count > 0)
        .sort(sortUnreadRows),
    [data?.states],
  );
  const totalReplies = unreadRows.reduce((sum, row) => sum + row.unread_agent_reply_count, 0);
  const totalChannels = new Set(unreadRows.map((row) => row.channel_id).filter(Boolean)).size;

  const markSessionRead = (sessionId: string) => {
    markRead.mutate({
      session_id: sessionId,
      source: "web_unread_inbox",
      surface: "sidebar_unread_inbox",
    });
  };

  const markAllRead = () => {
    markRead.mutate({
      source: "web_unread_inbox",
      surface: "sidebar_unread_inbox",
    });
  };

  return (
    <div className="w-full shrink-0 h-full flex flex-col bg-surface border-r border-surface-border/60">
      <div className="shrink-0 border-b border-surface-border/60 px-3 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/10 text-accent">
            <Inbox size={15} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-semibold text-text">Unread</div>
            <div className="text-[11px] text-text-dim">
              {totalReplies > 0
                ? `${totalReplies} ${totalReplies === 1 ? "reply" : "replies"} across ${totalChannels} ${totalChannels === 1 ? "channel" : "channels"}`
                : "No unread replies"}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay/60 hover:text-text"
            aria-label="Close unread inbox"
            title="Close"
          >
            <X size={14} />
          </button>
        </div>

        <button
          type="button"
          onClick={markAllRead}
          disabled={totalReplies === 0 || markRead.isPending}
          className={cn(
            "mt-3 inline-flex min-h-[30px] w-full items-center justify-center gap-1.5 rounded-md px-2.5 text-[12px] font-medium transition-colors",
            totalReplies === 0 || markRead.isPending
              ? "cursor-not-allowed bg-surface-overlay/25 text-text-dim/70"
              : "bg-surface-overlay/50 text-text-muted hover:bg-surface-overlay hover:text-text",
          )}
        >
          {markRead.isPending ? <Loader2 size={13} className="animate-spin" /> : <CheckCheck size={13} />}
          Mark all read
        </button>
      </div>

      <div className="scroll-subtle min-h-0 flex-1 overflow-y-auto overflow-x-hidden py-2">
        {isLoading ? (
          <div className="flex flex-col gap-2 px-3 py-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-[62px] animate-pulse rounded-md bg-surface-overlay/35" />
            ))}
          </div>
        ) : unreadRows.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <div className="mx-auto mb-3 flex h-9 w-9 items-center justify-center rounded-md bg-surface-overlay/45 text-text-dim">
              <Check size={16} />
            </div>
            <div className="text-[13px] font-medium text-text-muted">All caught up</div>
          </div>
        ) : (
          <div className="flex flex-col gap-1 px-2">
            {unreadRows.map((row) => {
              const channelName = row.channel_id
                ? channelNameById.get(row.channel_id) ?? "Unknown channel"
                : "Direct session";
              const href = unreadStateHref(row);
              const count = row.unread_agent_reply_count;
              const rowBody = (
                <>
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <Hash size={13} className="shrink-0 text-text-dim" />
                    <span className="truncate text-[13px] font-semibold text-text">{channelName}</span>
                  </div>
                  <span className="shrink-0 rounded-full bg-accent/15 px-1.5 py-0.5 text-[10px] font-bold text-accent tabular-nums">
                    {count > 99 ? "99+" : count}
                  </span>
                </>
              );

              return (
                <div
                  key={row.session_id}
                  className="group rounded-md transition-colors hover:bg-surface-overlay/55"
                >
                  <div className="flex min-w-0 items-stretch">
                    {href ? (
                      <Link
                        to={href}
                        onClick={onClose}
                        className="grid min-w-0 flex-1 grid-rows-[auto_auto] gap-1 px-2.5 py-2"
                      >
                        <div className="flex min-w-0 items-center gap-2">{rowBody}</div>
                        <div className="truncate pl-[21px] text-[11px] text-text-dim">
                          Session {shortId(row.session_id)} - {formatRelative(row.latest_unread_at)}
                        </div>
                      </Link>
                    ) : (
                      <div className="grid min-w-0 flex-1 grid-rows-[auto_auto] gap-1 px-2.5 py-2">
                        <div className="flex min-w-0 items-center gap-2">{rowBody}</div>
                        <div className="truncate pl-[21px] text-[11px] text-text-dim">
                          Session {shortId(row.session_id)} - {formatRelative(row.latest_unread_at)}
                        </div>
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => markSessionRead(row.session_id)}
                      className="mr-1 my-1 flex w-8 shrink-0 items-center justify-center rounded-md text-text-dim opacity-80 transition-colors hover:bg-surface-overlay hover:text-text group-hover:opacity-100"
                      aria-label={`Mark ${channelName} session read`}
                      title="Mark read"
                    >
                      <Check size={13} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
