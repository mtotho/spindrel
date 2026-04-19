import { useChannelEvents } from "./useChannelEvents";

/**
 * Subscribe to a sub-session's turns/messages.
 *
 * Two modes:
 *
 * 1. **With parent channel** (pipeline runs, channel-scoped ephemerals): the
 *    backend republishes sub-session events on the parent channel's bus
 *    tagged with ``payload.session_id``. This hook subscribes to the parent
 *    channel's SSE stream and filters by session_id, dispatching under a
 *    store key equal to ``runSessionId`` so the modal's state lives in a
 *    separate namespace from the parent channel's chat slot.
 *
 * 2. **Without parent channel** (channel-less ephemerals — widget dashboard
 *    dock, etc.): the backend publishes on ``session_id`` as the bus key
 *    itself, and exposes a dedicated SSE route at
 *    ``/api/v1/sessions/{session_id}/events``. The hook points
 *    ``useChannelEvents`` at that path via ``subscribePath: "sessions"``.
 */
export function useSessionEvents(
  parentChannelId: string | undefined,
  runSessionId: string | undefined,
  botId?: string,
) {
  const channelLess = !parentChannelId && !!runSessionId;
  useChannelEvents(channelLess ? runSessionId : parentChannelId, botId, {
    // In channel-less mode the session_id IS the bus key, so no filter is
    // needed (every event on that key belongs to this session). In the
    // channel-scoped mode we filter on session_id to ignore the parent
    // channel's own events.
    sessionFilter: channelLess ? undefined : runSessionId,
    // Always dispatch into the store under runSessionId — that's the key
    // SessionChatView + EphemeralSession read from.
    dispatchChannelId: runSessionId,
    subscribePath: channelLess ? "sessions" : "channels",
  });
}
