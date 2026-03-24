import { useMutation } from "@tanstack/react-query";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import type { ChatRequest, SSEEvent } from "../../types/api";

interface UseChatStreamOptions {
  onEvent: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
  onComplete?: () => void;
}

export function useChatStream(options: UseChatStreamOptions) {
  return useMutation({
    mutationFn: async (request: ChatRequest) => {
      const { serverUrl } = useAuthStore.getState();
      if (!serverUrl) throw new Error("Server not configured");

      const token = getAuthToken();
      const ctrl = new AbortController();

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
            options.onEvent({
              event: ev.event as SSEEvent["event"],
              data,
            });
          } catch {
            // keepalive or non-JSON
          }
        },
        onerror(err) {
          options.onError?.(err instanceof Error ? err : new Error(String(err)));
          throw err; // stop retrying
        },
        onclose() {
          options.onComplete?.();
        },
        openWhenHidden: true,
      });
    },
  });
}
