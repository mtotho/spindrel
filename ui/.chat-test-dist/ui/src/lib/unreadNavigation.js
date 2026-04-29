import { buildChannelSessionRoute } from "./channelSessionSurfaces.js";
export function unreadStateHref(row) {
    if (!row.channel_id)
        return undefined;
    return buildChannelSessionRoute(row.channel_id, {
        kind: "channel",
        sessionId: row.session_id,
    });
}
