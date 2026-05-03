import { useMutation, useQuery } from "@tanstack/react-query";
import { getApiBase } from "../client";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { apiFetch } from "../client";
import type { ChatRequest } from "../../types/api";

interface CancelRequest {
  client_id: string;
  bot_id: string;
  session_id?: string;
  channel_id?: string;
}

interface CancelResponse {
  cancelled: boolean;
  queued_tasks_cancelled: number;
}

export function useCancelChat() {
  return useMutation({
    mutationFn: async (req: CancelRequest): Promise<CancelResponse> => {
      const { serverUrl } = useAuthStore.getState();
      if (!serverUrl) throw new Error("Server not configured");
      const token = getAuthToken();
      const res = await fetch(`${getApiBase()}/chat/cancel`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`Cancel failed: ${res.status}`);
      return res.json();
    },
  });
}

/** Response shape from POST /chat (202). */
export interface ChatSubmitResponse {
  session_id: string;
  channel_id: string;
  turn_id?: string;
  queued?: boolean;
  task_id?: string;
  session_scoped?: boolean;
}

/**
 * Submit a chat turn. Returns the 202 acknowledgement; all streaming UI
 * state is driven by the typed channel-events bus via `useChannelEvents`.
 *
 * The legacy `useChatStream` long-poll consumer is gone — POST /chat
 * accepts the request and the worker publishes typed events on the bus.
 */
export function useSubmitChat() {
  return useMutation({
    mutationFn: async (request: ChatRequest): Promise<ChatSubmitResponse> => {
      const { serverUrl } = useAuthStore.getState();
      if (!serverUrl) throw new Error("Server not configured");
      const token = getAuthToken();
      const res = await fetch(`${getApiBase()}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(request),
      });
      if (!res.ok) {
        // Surface the body if the server gave one (validation errors etc.).
        let detail = `Submit failed: ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail) detail = String(body.detail);
        } catch {
          // ignore
        }
        throw new Error(detail);
      }
      return res.json();
    },
  });
}

interface SessionStatus {
  processing: boolean;
  pending_tasks: number;
}

/** Session-status safety net while a background turn is active.
 *
 *  The channel SSE stream (``turn_ended``) is the primary signal that
 *  drives ``clearProcessing`` in the chat store. This poll is a fallback
 *  for the narrow window where a background task finishes without a
 *  turn-ended event (e.g. queued dispatch completed ahead of the worker
 *  publishing). Cadence is deliberately slow — SSE carries real-time. */
export function useSessionStatus(channelId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["session-status", channelId],
    queryFn: () => apiFetch<SessionStatus>(`/api/v1/channels/${channelId}/session-status`),
    enabled: !!channelId && enabled,
    refetchInterval: enabled ? 15000 : false,
  });
}
