import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { useChatStore } from "../../stores/chat";

/**
 * Subscribe to real-time channel events via SSE.
 *
 * On "new_message" events, invalidates TanStack Query so messages refetch
 * from DB — unless the channel is currently streaming/processing (the
 * existing SSE handles those updates).
 */
export function useChannelEvents(channelId: string | undefined) {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!channelId) return;

    const { serverUrl } = useAuthStore.getState();
    if (!serverUrl) return;

    let retryCount = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    function connect() {
      if (stopped) return;

      const token = getAuthToken();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      fetch(`${serverUrl}/channels/${channelId}/events`, {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          Accept: "text/event-stream",
        },
        signal: ctrl.signal,
      })
        .then(async (res) => {
          if (!res.ok || !res.body) {
            throw new Error(`SSE connect failed: ${res.status}`);
          }

          // Reset retry count on successful connection
          retryCount = 0;

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done || stopped) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";

            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              try {
                const payload = JSON.parse(line.slice(6));
                if (payload.type === "new_message") {
                  // Skip invalidation if this channel is actively streaming
                  const ch = useChatStore.getState().getChannel(channelId!);
                  if (ch.isStreaming || ch.isProcessing) continue;
                  queryClient.invalidateQueries({
                    queryKey: ["session-messages"],
                  });
                }
              } catch {
                // Non-JSON (keepalive comment) — ignore
              }
            }
          }

          // Stream ended cleanly (server restart, etc.) — reconnect
          if (!stopped) {
            retryTimer = setTimeout(connect, 1000);
          }
        })
        .catch((err) => {
          if (stopped || ctrl.signal.aborted) return;
          // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s max
          const delay = Math.min(1000 * 2 ** retryCount, 30000);
          retryCount = Math.min(retryCount + 1, 10);
          retryTimer = setTimeout(connect, delay);
        });
    }

    connect();

    return () => {
      stopped = true;
      abortRef.current?.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [channelId, queryClient]);
}
