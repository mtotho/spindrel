import { Link } from "react-router-dom";
import { Clock3, Hash, MessageSquareText } from "lucide-react";

import { useRecentSessions, type RecentSessionItem } from "../../../api/hooks/useRecentSessions";
import { buildChannelSessionRoute } from "../../../lib/channelSessionSurfaces";
import { formatRelativeTime } from "../../../utils/format";
import { SectionHeading } from "./SectionHeading";

function shortId(id: string): string {
  return id.slice(0, 8);
}

function sessionHref(row: RecentSessionItem): string {
  if (row.is_active && row.surface_kind === "channel") {
    return buildChannelSessionRoute(row.channel_id, { kind: "primary" });
  }
  return buildChannelSessionRoute(row.channel_id, {
    kind: row.surface_kind,
    sessionId: row.session_id,
  });
}

function sessionTitle(row: RecentSessionItem): string {
  return row.label?.trim() || (row.is_active ? "Primary session" : `Session ${shortId(row.session_id)}`);
}

function sessionMeta(row: RecentSessionItem): string {
  const pieces = [
    `${row.message_count} msg${row.message_count === 1 ? "" : "s"}`,
    row.section_count ? `${row.section_count} section${row.section_count === 1 ? "" : "s"}` : null,
    formatRelativeTime(row.last_active),
  ].filter(Boolean);
  return pieces.join(" · ");
}

function RecentSessionRow({ row, index }: { row: RecentSessionItem; index: number }) {
  const unreadCount = row.unread_agent_reply_count;
  return (
    <Link
      to={sessionHref(row)}
      data-testid="home-recent-session-row"
      className={`group flex min-h-[74px] items-start gap-3 rounded-md border border-transparent bg-surface-raised/45 px-3 py-3 transition-colors hover:border-surface-border hover:bg-surface-overlay/40 ${index >= 5 ? "hidden sm:flex" : ""}`}
    >
      <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-surface-border bg-surface">
        <MessageSquareText size={15} className={unreadCount ? "text-accent" : "text-text-dim"} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-semibold text-text">{sessionTitle(row)}</span>
          {unreadCount ? (
            <span className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-accent">
              {unreadCount} unread
            </span>
          ) : null}
        </span>
        <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-muted">
          <span className="inline-flex min-w-0 items-center gap-1">
            <Hash size={12} className="shrink-0 text-text-dim" />
            <span className="truncate">{row.channel_name}</span>
          </span>
          <span>{sessionMeta(row)}</span>
          {row.surface_kind === "scratch" ? <span>Scratch</span> : null}
        </span>
        <span className="mt-1.5 line-clamp-1 text-xs text-text-dim">
          {row.preview || row.summary || "No messages yet"}
        </span>
      </span>
    </Link>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="h-[74px] rounded-md bg-surface-raised/45" />
      ))}
    </div>
  );
}

export function RecentSessionsSection() {
  const { data, isLoading, isError } = useRecentSessions(8);
  const sessions = data?.sessions ?? [];

  return (
    <section data-testid="home-recent-sessions" className="space-y-2" aria-label="Recent sessions">
      <SectionHeading
        icon={<Clock3 size={12} />}
        label="Recent sessions"
        count={sessions.length || undefined}
      />
      {isLoading ? <LoadingRows /> : null}
      {!isLoading && isError ? (
        <div className="rounded-md border border-surface-border bg-surface-raised/45 px-3 py-4 text-sm text-text-muted">
          Recent sessions unavailable.
        </div>
      ) : null}
      {!isLoading && !isError && sessions.length === 0 ? (
        <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/30 px-3 py-4 text-sm text-text-muted">
          No recent sessions yet.
        </div>
      ) : null}
      {!isLoading && !isError && sessions.length ? (
        <div className="space-y-2">
          {sessions.map((row, index) => (
            <RecentSessionRow key={`${row.surface_kind}:${row.session_id}`} row={row} index={index} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
