import { useChannelEvents } from "./useChannelEvents";

/**
 * Subscribe to a sub-session's turns/messages by filtering events on the
 * parent channel's SSE stream.
 *
 * The pipeline run-view modal uses this to mount ``ChatMessageArea``
 * against a ``run_session_id`` while still tapping the in-process bus
 * (which is channel-keyed). The backend (``sub_session_bus``) republishes
 * sub-session Messages + turn events on the parent channel's bus; this
 * hook discriminates by ``payload.session_id`` so only the run's events
 * reach the chat store — and dispatches them under a store key equal to
 * ``runSessionId`` so the modal's state lives in a separate namespace
 * from the parent channel's chat slot.
 */
export function useSessionEvents(
  parentChannelId: string | undefined,
  runSessionId: string | undefined,
  botId?: string,
) {
  useChannelEvents(parentChannelId, botId, {
    sessionFilter: runSessionId,
    dispatchChannelId: runSessionId,
  });
}
