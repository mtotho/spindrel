import { buildChannelSessionRoute } from "./channelSessionSurfaces.js";
import { parseChannelRecentRoute } from "./recentPages.js";
function timestampMs(value) {
    if (!value)
        return 0;
    const ms = Date.parse(value);
    return Number.isFinite(ms) ? ms : 0;
}
function unreadSortValue(row) {
    return Math.max(timestampMs(row.latest_unread_at), timestampMs(row.first_unread_at), timestampMs(row.last_read_at));
}
export function findLatestUnreadChannelSession(channelId, unreadStates) {
    let best = null;
    for (const row of unreadStates ?? []) {
        if (row.channel_id !== channelId)
            continue;
        if (row.unread_agent_reply_count <= 0)
            continue;
        if (!best || unreadSortValue(row) > unreadSortValue(best)) {
            best = row;
        }
    }
    return best;
}
export function findMostRecentChannelSessionHref(channelId, recentPages) {
    for (const page of recentPages ?? []) {
        const route = parseChannelRecentRoute(page.href);
        if (!route || route.kind !== "session" || route.channelId !== channelId)
            continue;
        return page.href;
    }
    return null;
}
export function isGenericChannelHref(href) {
    const route = parseChannelRecentRoute(href);
    return route?.kind === "channel" ? route.channelId : null;
}
export function resolveChannelEntryHref({ channelId, recentPages, unreadStates, }) {
    const unread = findLatestUnreadChannelSession(channelId, unreadStates);
    if (unread) {
        return buildChannelSessionRoute(channelId, {
            kind: "channel",
            sessionId: unread.session_id,
        });
    }
    return findMostRecentChannelSessionHref(channelId, recentPages) ?? `/channels/${channelId}`;
}
export function resolveGenericChannelHref(href, options) {
    const channelId = isGenericChannelHref(href);
    if (!channelId)
        return href;
    return resolveChannelEntryHref({ channelId, ...options });
}
