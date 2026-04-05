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
        // Skip if this tab initiated the current stream and no member bot is pending.
        // When pendingMemberStream is true, we allow stream_start through even during
        // isLocalStream — this handles the race where stream_start arrives before
        // onComplete clears isLocalStream.
        if (ch.isLocalStream && !ch.pendingMemberStream) return;
        if (ch.isStreaming && !ch.isLocalStream) return; // Already observing another stream

        // If we're transitioning from a local stream to observing a member bot,
        // materialize the current streaming content as a message first.
        useChatStore.setState((s) => {
          const prev = s.channels[chId] ?? useChatStore.getState().getChannel(chId);
          let messages = prev.messages;
          if (prev.isLocalStream && prev.streamingContent) {
            const toolsUsed = prev.toolCalls.length > 0
              ? prev.toolCalls.map((tc) => tc.name)
              : undefined;
            const metadata = toolsUsed ? { tools_used: toolsUsed } : undefined;
            messages = [
              ...messages,
              {
                id: `msg-${Date.now()}`,
                session_id: "",
                role: "assistant" as const,
                content: prev.streamingContent,
                created_at: new Date().toISOString(),
                correlation_id: prev.correlationId ?? undefined,
                metadata,
              },
            ];
          }
          return {
            channels: {
              ...s.channels,
              [chId]: {
                ...prev,
                messages,
                isStreaming: true,
                isLocalStream: false,
                pendingMemberStream: false,
                streamingContent: "",
                thinkingContent: "",
                toolCalls: [],
                correlationId: null,
                error: null,
                respondingBotId: payload.responding_bot_id ?? null,
                respondingBotName: payload.responding_bot_name ?? null,
              },
            },
          };
        });
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
