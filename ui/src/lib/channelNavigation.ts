import type { RecentPage } from "../stores/ui";
import { buildChannelSessionRoute } from "./channelSessionSurfaces.js";
import { parseChannelRecentRoute } from "./recentPages.js";

export interface ChannelUnreadNavigationState {
  channel_id: string | null;
  session_id: string;
  unread_agent_reply_count: number;
  latest_unread_at?: string | null;
  first_unread_at?: string | null;
  last_read_at?: string | null;
}

export interface ChannelEntryNavigationInput {
  channelId: string;
  recentPages?: readonly RecentPage[] | null;
  unreadStates?: readonly ChannelUnreadNavigationState[] | null;
}

function timestampMs(value?: string | null): number {
  if (!value) return 0;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : 0;
}

function unreadSortValue(row: ChannelUnreadNavigationState): number {
  return Math.max(
    timestampMs(row.latest_unread_at),
    timestampMs(row.first_unread_at),
    timestampMs(row.last_read_at),
  );
}

export function findLatestUnreadChannelSession(
  channelId: string,
  unreadStates?: readonly ChannelUnreadNavigationState[] | null,
): ChannelUnreadNavigationState | null {
  let best: ChannelUnreadNavigationState | null = null;
  for (const row of unreadStates ?? []) {
    if (row.channel_id !== channelId) continue;
    if (row.unread_agent_reply_count <= 0) continue;
    if (!best || unreadSortValue(row) > unreadSortValue(best)) {
      best = row;
    }
  }
  return best;
}

export function findMostRecentChannelSessionHref(
  channelId: string,
  recentPages?: readonly RecentPage[] | null,
): string | null {
  for (const page of recentPages ?? []) {
    const route = parseChannelRecentRoute(page.href);
    if (!route || route.kind !== "session" || route.channelId !== channelId) continue;
    return page.href;
  }
  return null;
}

export function isGenericChannelHref(href: string): string | null {
  const route = parseChannelRecentRoute(href);
  return route?.kind === "channel" ? route.channelId : null;
}

export function resolveChannelEntryHref({
  channelId,
  recentPages,
  unreadStates,
}: ChannelEntryNavigationInput): string {
  const unread = findLatestUnreadChannelSession(channelId, unreadStates);
  if (unread) {
    return buildChannelSessionRoute(channelId, {
      kind: "channel",
      sessionId: unread.session_id,
    });
  }

  return findMostRecentChannelSessionHref(channelId, recentPages) ?? `/channels/${channelId}`;
}

export function resolveGenericChannelHref(
  href: string,
  options: Omit<ChannelEntryNavigationInput, "channelId">,
): string {
  const channelId = isGenericChannelHref(href);
  if (!channelId) return href;
  return resolveChannelEntryHref({ channelId, ...options });
}
