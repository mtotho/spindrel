import { useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import type { ChatRequest, SSEEvent } from "../../types/api";

interface CancelRequest {
  client_id: string;
  bot_id: string;
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
      const res = await fetch(`${serverUrl}/chat/cancel`, {
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

interface UseChatStreamOptions {
  onEvent: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
  onComplete?: () => void;
}

export function useChatStream(options: UseChatStreamOptions) {
  const abortRef = useRef<AbortController | null>(null);

  return useMutation({
    mutationFn: async (request: ChatRequest) => {
      // Abort any previous SSE stream so its stale callbacks don't fire
      abortRef.current?.abort();

      const { serverUrl } = useAuthStore.getState();
      if (!serverUrl) throw new Error("Server not configured");

      const token = getAuthToken();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      try {
        await fetchEventSource(`${serverUrl}/chat/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(request),
          signal: ctrl.signal,
          onmessage(ev) {
            if (!ev.data) return;
            try {
              const data = JSON.parse(ev.data);
              // The server sends unnamed SSE events (just `data:` lines),
              // so ev.event is always "message".  The actual event type is
              // in data.type (e.g. "response", "tool_start", etc.).
              options.onEvent({
                event: (data.type ?? ev.event) as SSEEvent["event"],
                data,
              });
            } catch {
              // keepalive or non-JSON
            }
          },
          onerror(err) {
            // Don't report abort errors — they're intentional from starting a new stream
            if (ctrl.signal.aborted) throw err;
            options.onError?.(err instanceof Error ? err : new Error(String(err)));
            throw err; // stop retrying
          },
          onclose() {
            // Don't fire onComplete for aborted streams — the new stream owns the state now
            if (!ctrl.signal.aborted) {
              options.onComplete?.();
            }
          },
          openWhenHidden: true,
        });
      } catch (err) {
        // Swallow abort errors — they're expected when a new stream replaces the old one
        if (err && (err as any).name === "AbortError") return;
        throw err;
      }
    },
  });
}
