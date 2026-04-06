import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { useChatStore } from "../../stores/chat";
import type { SSEEvent } from "../../types/api";

/** Timeout (ms) for observed streams — if stream_end doesn't arrive, force-finish. */
const OBSERVER_STREAM_TIMEOUT = 60_000;

/**
 * Subscribe to real-time channel events via SSE.
 *
 * Handles two kinds of events:
 * - `new_message`: invalidates TanStack Query so messages refetch from DB
 * - `stream_start/stream_event/stream_end`: relays the agent's SSE stream
 *   to observer tabs so they see real-time streaming, tool calls, thinking, etc.
 *
 * With stream_id-based demuxing, multiple bot streams can run concurrently.
 * Each stream is tracked independently in `memberStreams` (chat store).
 * The primary bot's direct SSE (useChannelChat) still uses the singular fields
 * for the local tab — member streams only go through this channel events path.
 */
export function useChannelEvents(channelId: string | undefined, primaryBotId?: string) {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const handleSSEEvent = useChatStore((s) => s.handleSSEEvent);
  const finishStreaming = useChatStore((s) => s.finishStreaming);

  // Keep primaryBotId current without triggering SSE reconnect
  const primaryBotIdRef = useRef(primaryBotId);
  primaryBotIdRef.current = primaryBotId;

  // Per-stream delta batching (stream_id → { text, think })
  const pendingDeltasRef = useRef<Record<string, { text: string; think: string }>>({});
  const rafRef = useRef<number>(0);

  // Per-stream observer timeouts
  const observerTimeoutsRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const flushDeltas = useCallback(
    (chId: string) => {
      rafRef.current = 0;
      const store = useChatStore.getState();
      const pending = pendingDeltasRef.current;
      for (const [streamId, deltas] of Object.entries(pending)) {
        if (!deltas.text && !deltas.think) continue;
        // Route to the correct member stream
        if (store.channels[chId]?.memberStreams[streamId]) {
          if (deltas.text) {
            store.handleMemberStreamEvent(chId, streamId, {
              event: "text_delta",
              data: { delta: deltas.text },
            });
          }
          if (deltas.think) {
            store.handleMemberStreamEvent(chId, streamId, {
              event: "thinking",
              data: { delta: deltas.think },
            });
          }
        }
      }
      pendingDeltasRef.current = {};
    },
    [],
  );

  useEffect(() => {
    if (!channelId) return;

    const { serverUrl } = useAuthStore.getState();
    if (!serverUrl) return;

    let retryCount = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    function clearObserverTimeout(streamId: string) {
      const timer = observerTimeoutsRef.current[streamId];
      if (timer) {
        clearTimeout(timer);
        delete observerTimeoutsRef.current[streamId];
      }
    }

    function clearAllObserverTimeouts() {
      for (const streamId of Object.keys(observerTimeoutsRef.current)) {
        clearTimeout(observerTimeoutsRef.current[streamId]);
      }
      observerTimeoutsRef.current = {};
    }

    function startObserverTimeout(chId: string, streamId: string) {
      clearObserverTimeout(streamId);
      observerTimeoutsRef.current[streamId] = setTimeout(() => {
        delete observerTimeoutsRef.current[streamId];
        const ch = useChatStore.getState().getChannel(chId);
        // Flush pending deltas for this stream
        const deltas = pendingDeltasRef.current[streamId];
        if (deltas && (deltas.text || deltas.think)) {
          cancelAnimationFrame(rafRef.current);
          flushDeltas(chId);
        }
        if (ch.memberStreams[streamId]) {
          useChatStore.getState().finishMemberStream(chId, streamId);
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        }
      }, OBSERVER_STREAM_TIMEOUT);
    }

    function connect() {
      if (stopped) return;

      const token = getAuthToken();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      fetch(`${serverUrl}/api/v1/channels/${channelId}/events`, {
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
        // Also skip if any member streams are active
        if (Object.keys(ch.memberStreams).length > 0) return;
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        return;
      }

      if (payload.type === "stream_start") {
        const streamId = payload.stream_id as string | undefined;
        if (!streamId) return; // Legacy event without stream_id — ignore

        // If this tab initiated the stream (isLocalStream), the primary bot's
        // stream_start should be ignored (already handled by useChannelChat).
        // But member bot streams always go through memberStreams.
        // Match against both respondingBotId (set by stream_meta) and the
        // channel's configured primary bot ID to avoid a race where stream_start
        // arrives before stream_meta and member bot streams get dropped.
        if (ch.isLocalStream && (
          payload.responding_bot_id === ch.respondingBotId ||
          payload.responding_bot_id === primaryBotIdRef.current
        )) {
          return;
        }

        useChatStore.getState().startMemberStream(
          chId, streamId,
          payload.responding_bot_id ?? "",
          payload.responding_bot_name ?? "",
        );
        startObserverTimeout(chId, streamId);
        return;
      }

      if (payload.type === "stream_event") {
        const streamId = payload.stream_id as string | undefined;
        const inner = payload.event;
        if (!inner || !streamId) return;

        // Check if this is a member stream we're tracking
        const latestCh = useChatStore.getState().getChannel(chId);
        if (!latestCh.memberStreams[streamId]) return;

        const eventType = inner.type as SSEEvent["event"];

        // Batch text_delta and thinking for 60fps rendering
        if (eventType === "text_delta" || eventType === "thinking") {
          if (!pendingDeltasRef.current[streamId]) {
            pendingDeltasRef.current[streamId] = { text: "", think: "" };
          }
          if (eventType === "text_delta") {
            pendingDeltasRef.current[streamId].text += inner.delta ?? "";
          } else {
            pendingDeltasRef.current[streamId].think += inner.delta ?? "";
          }
          if (!rafRef.current) {
            rafRef.current = requestAnimationFrame(() => flushDeltas(chId));
          }
          return;
        }

        // Flush pending deltas before processing other events
        const deltas = pendingDeltasRef.current[streamId];
        if (deltas && (deltas.text || deltas.think)) {
          cancelAnimationFrame(rafRef.current);
          flushDeltas(chId);
        }

        useChatStore.getState().handleMemberStreamEvent(
          chId, streamId, { event: eventType, data: inner },
        );
        return;
      }

      if (payload.type === "pending_member_stream") {
        // Legacy event — no longer needed with stream_id-based demuxing.
        // Trigger safety-net refetch for backward compat.
        const delays = [3000, 8000, 15000];
        for (const delay of delays) {
          setTimeout(() => {
            const latest = useChatStore.getState().getChannel(chId);
            if (!latest.isStreaming && Object.keys(latest.memberStreams).length === 0) {
              queryClient.invalidateQueries({ queryKey: ["session-messages"] });
            }
          }, delay);
        }
        return;
      }

      if (payload.type === "stream_end") {
        const streamId = payload.stream_id as string | undefined;
        if (!streamId) return;

        clearObserverTimeout(streamId);

        // Flush any remaining deltas for this stream
        const deltas = pendingDeltasRef.current[streamId];
        if (deltas && (deltas.text || deltas.think)) {
          cancelAnimationFrame(rafRef.current);
          flushDeltas(chId);
        }

        const latestCh = useChatStore.getState().getChannel(chId);
        if (latestCh.memberStreams[streamId]) {
          useChatStore.getState().finishMemberStream(chId, streamId);
        }
        // Always refetch — even if we didn't track this stream (e.g. stream_end
        // arrived without stream_start due to reconnection), the bot's message
        // is now persisted in the DB.
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        return;
      }
    }

    connect();

    return () => {
      stopped = true;
      abortRef.current?.abort();
      clearAllObserverTimeouts();
      if (retryTimer) clearTimeout(retryTimer);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [channelId, queryClient, handleSSEEvent, finishStreaming, flushDeltas]);
}
