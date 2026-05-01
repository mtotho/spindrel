import { Link } from "react-router-dom";
import { Hash, ShieldCheck, UserRound, UsersRound } from "lucide-react";

import { type UserActivitySummary, useAdminUserActivitySummary } from "../../../api/hooks/useAdminUsers";
import { buildChannelSessionRoute } from "../../../lib/channelSessionSurfaces";
import { useAuthStore } from "../../../stores/auth";
import { formatRelativeTime } from "../../../utils/format";
import { SectionHeading } from "./SectionHeading";

function initialsFor(user: UserActivitySummary): string {
  const source = user.display_name?.trim() || user.email;
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

function userLabel(user: UserActivitySummary): string {
  return user.display_name?.trim() || user.email;
}

function todayMeta(user: UserActivitySummary): string {
  const pieces = [
    `${user.today_message_count} msg${user.today_message_count === 1 ? "" : "s"} today`,
    user.today_session_count ? `${user.today_session_count} session${user.today_session_count === 1 ? "" : "s"}` : null,
    user.today_channel_count ? `${user.today_channel_count} channel${user.today_channel_count === 1 ? "" : "s"}` : null,
  ].filter(Boolean);
  return pieces.join(" · ");
}

function latestMeta(user: UserActivitySummary): string {
  const latest = user.latest_session;
  if (!latest) return todayMeta(user);
  const time = formatRelativeTime(user.latest_activity_at ?? latest.last_active);
  return [
    latest.channel_name,
    time,
    todayMeta(user),
  ].filter(Boolean).join(" · ");
}

function UserAvatar({ user }: { user: UserActivitySummary }) {
  if (user.avatar_url) {
    return (
      <img
        src={user.avatar_url}
        alt=""
        className="h-8 w-8 shrink-0 rounded-md border border-surface-border object-cover"
      />
    );
  }
  return (
    <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-surface-border bg-surface text-[11px] font-semibold text-text-muted">
      {initialsFor(user)}
    </span>
  );
}

function UserRow({ user, index }: { user: UserActivitySummary; index: number }) {
  const latest = user.latest_session;
  const href = latest
    ? buildChannelSessionRoute(latest.channel_id, { kind: "channel", sessionId: latest.session_id })
    : null;
  const title = latest?.label?.trim() || (latest ? `Session ${latest.session_id.slice(0, 8)}` : "No recent session");
  const preview = latest?.preview || (user.today_message_count ? "Activity recorded today." : "No activity today.");
  const content = (
    <span className="group flex min-h-[72px] min-w-0 items-start gap-3 rounded-md px-2 py-2 transition-colors hover:bg-surface-overlay/40">
      <UserAvatar user={user} />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-semibold text-text">{userLabel(user)}</span>
          {user.is_admin ? (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-surface-overlay/50 px-1.5 py-0.5 text-[10px] font-medium text-text-muted">
              <ShieldCheck size={10} />
              Admin
            </span>
          ) : null}
          {!user.is_active ? (
            <span className="shrink-0 rounded-full bg-surface-overlay/50 px-1.5 py-0.5 text-[10px] font-medium text-text-dim">
              Inactive
            </span>
          ) : null}
        </span>
        <span className="mt-1 flex min-w-0 items-center gap-1 text-xs text-text-muted">
          {latest ? <Hash size={12} className="shrink-0 text-text-dim" /> : <UserRound size={12} className="shrink-0 text-text-dim" />}
          <span className="truncate">{latest ? latestMeta(user) : todayMeta(user)}</span>
        </span>
        <span className="mt-1.5 block truncate text-xs text-text-dim">
          {title}: {preview}
        </span>
      </span>
    </span>
  );

  return (
    <div data-testid="home-user-row" className={index >= 4 ? "hidden sm:block" : ""}>
      {href ? <Link to={href}>{content}</Link> : content}
    </div>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-1">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="h-[72px] rounded-md bg-surface-overlay/30" />
      ))}
    </div>
  );
}

export function UsersSection() {
  const isAdmin = !!useAuthStore((s) => s.user?.is_admin);
  const { data, isLoading, isError } = useAdminUserActivitySummary(6, isAdmin);
  const users = data?.users ?? [];

  if (!isAdmin) return null;

  return (
    <section data-testid="home-users-section" className="space-y-2" aria-label="Users">
      <SectionHeading
        icon={<UsersRound size={12} />}
        label="Users"
        count={users.length || undefined}
      />
      <div className="rounded-md border border-surface-border bg-surface-raised p-2">
        {isLoading ? <LoadingRows /> : null}
        {!isLoading && isError ? (
          <div className="px-2 py-3 text-sm text-text-muted">Users unavailable.</div>
        ) : null}
        {!isLoading && !isError && users.length === 0 ? (
          <div className="px-2 py-3 text-sm text-text-muted">No users found.</div>
        ) : null}
        {!isLoading && !isError && users.length ? (
          <div className="space-y-1">
            {users.map((user, index) => (
              <UserRow key={user.id} user={user} index={index} />
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
