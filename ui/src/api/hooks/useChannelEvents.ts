import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { useChatStore } from "../../stores/chat";
import type { SSEEvent } from "../../types/api";

/**
 * Subscribe to real-time channel events via SSE.
 *
 * Handles two kinds of events:
 * - `new_message`: invalidates TanStack Query so messages refetch from DB
 * - `stream_start/stream_event/stream_end`: relays the agent's SSE stream
 *   to observer tabs so they see real-time streaming, tool calls, thinking, etc.
 *
 * The primary tab (which sent the message) sets `isLocalStream = true` in the
 * chat store.  Stream relay events are only processed when `isLocalStream` is
 * false — preventing double-processing.
 */
export function useChannelEvents(channelId: string | undefined) {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const handleSSEEvent = useChatStore((s) => s.handleSSEEvent);
  const startStreaming = useChatStore((s) => s.startStreaming);
  const finishStreaming = useChatStore((s) => s.finishStreaming);

  // Delta batching for observer streams (same pattern as useChannelChat)
  const pendingTextRef = useRef<string>("");
  const pendingThinkRef = useRef<string>("");
  const rafRef = useRef<number>(0);

  const flushDeltas = useCallback(
    (chId: string) => {
      rafRef.current = 0;
      if (pendingTextRef.current) {
        handleSSEEvent(chId, {
          event: "text_delta",
          data: { delta: pendingTextRef.current },
        });
        pendingTextRef.current = "";
      }
      if (pendingThinkRef.current) {
        handleSSEEvent(chId, {
          event: "thinking",
          data: { delta: pendingThinkRef.current },
        });
        pendingThinkRef.current = "";
      }
    },
    [handleSSEEvent],
  );

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
                handleEvent(channelId!, payload);
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
          const delay = Math.min(1000 * 2 ** retryCount, 30000);
          retryCount = Math.min(retryCount + 1, 10);
          retryTimer = setTimeout(connect, delay);
        });
    }

    function handleEvent(chId: string, payload: any) {
      const ch = useChatStore.getState().getChannel(chId);

      if (payload.type === "new_message") {
        // Skip if this channel is actively streaming (either locally or observing)
        if (ch.isStreaming || ch.isProcessing) return;
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        return;
      }

      if (payload.type === "stream_start") {
        // Only start observing if this tab didn't initiate the stream
        if (ch.isLocalStream || ch.isStreaming) return;
        // Set streaming state but mark as non-local
        useChatStore.setState((s) => ({
          channels: {
            ...s.channels,
            [chId]: {
              ...(s.channels[chId] ?? useChatStore.getState().getChannel(chId)),
              isStreaming: true,
              isLocalStream: false,
              streamingContent: "",
              thinkingContent: "",
              toolCalls: [],
              error: null,
            },
          },
        }));
        return;
      }

      if (payload.type === "stream_event") {
        // Only process if we're observing (streaming but not local)
        if (!ch.isStreaming || ch.isLocalStream) return;
        const inner = payload.event;
        if (!inner) return;

        const eventType = inner.type as SSEEvent["event"];

        // Batch text_delta and thinking for 60fps rendering
        if (eventType === "text_delta") {
          pendingTextRef.current += inner.delta ?? "";
          if (!rafRef.current) {
            rafRef.current = requestAnimationFrame(() => flushDeltas(chId));
          }
          return;
        }
        if (eventType === "thinking") {
          pendingThinkRef.current += inner.delta ?? "";
          if (!rafRef.current) {
            rafRef.current = requestAnimationFrame(() => flushDeltas(chId));
          }
          return;
        }

        // Flush pending deltas before processing other events
        if (pendingTextRef.current || pendingThinkRef.current) {
          cancelAnimationFrame(rafRef.current);
          flushDeltas(chId);
        }

        handleSSEEvent(chId, { event: eventType, data: inner });
        return;
      }

      if (payload.type === "stream_end") {
        if (!ch.isStreaming || ch.isLocalStream) return;
        // Flush any remaining deltas
        if (pendingTextRef.current || pendingThinkRef.current) {
          cancelAnimationFrame(rafRef.current);
          flushDeltas(chId);
        }
        finishStreaming(chId);
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        return;
      }
    }

    connect();

    return () => {
      stopped = true;
      abortRef.current?.abort();
      if (retryTimer) clearTimeout(retryTimer);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [channelId, queryClient, handleSSEEvent, startStreaming, finishStreaming, flushDeltas]);
}
