import { buildChannelSessionRoute } from "./channelSessionSurfaces.js";

export interface UnreadNavigationState {
  channel_id: string | null;
  session_id: string;
}

export function unreadStateHref(row: UnreadNavigationState): string | undefined {
  if (!row.channel_id) return undefined;
  return buildChannelSessionRoute(row.channel_id, {
    kind: "channel",
    sessionId: row.session_id,
  });
}
