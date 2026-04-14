import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { useChatStore } from "../../stores/chat";
import { useBots } from "./useBots";

/** Timeout (ms) for in-flight turn observation — if turn_ended doesn't arrive, force-finish. */
const OBSERVER_TURN_TIMEOUT = 60_000;

/**
 * Subscribe to typed channel-event bus events via SSE.
 *
 * The wire format is `{ kind, channel_id, seq, ts, payload }` produced by
 * `app/services/channel_events.event_to_sse_dict`. This hook is the single
 * source of truth for chat streaming UI state — every concurrent agent
 * turn (primary or member bot) lives in `chatStore.channels[id].turns`
 * keyed by `payload.turn_id`.
 *
 * Reconnect-with-replay: on bus reconnect, the server resumes from `since`
 * (the last seq we saw). On `replay_lapsed` we drop everything in flight
 * for the channel and refetch from REST.
 */
export function useChannelEvents(channelId: string | undefined, primaryBotId?: string) {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const { data: bots } = useBots();

  // Bot-id → display name lookup, kept in a ref so reconnects don't churn.
  const botNamesRef = useRef<Record<string, string>>({});
  if (bots) {
    for (const b of bots) botNamesRef.current[b.id] = b.name ?? b.id;
  }

  // Keep primaryBotId current without triggering SSE reconnect.
  const primaryBotIdRef = useRef(primaryBotId);
  primaryBotIdRef.current = primaryBotId;

  // Per-turn delta batching (turn_id → { text, think })
  const pendingDeltasRef = useRef<Record<string, { text: string; think: string }>>({});
  const rafRef = useRef<number>(0);

  // Per-turn observer timeouts so a missing turn_ended doesn't leave a
  // streaming indicator stuck on screen forever.
  const observerTimeoutsRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // Last bus seq we received, for replay-on-reconnect.
  const lastSeqRef = useRef<number | null>(null);

  const flushDeltas = useCallback(
    (chId: string) => {
      rafRef.current = 0;
      const store = useChatStore.getState();
      const pending = pendingDeltasRef.current;
      for (const [turnId, deltas] of Object.entries(pending)) {
        if (!deltas.text && !deltas.think) continue;
        const ch = store.channels[chId];
        if (!ch?.turns[turnId]) continue;
        if (deltas.text) {
          store.handleTurnEvent(chId, turnId, {
            event: "text_delta",
            data: { delta: deltas.text },
          });
        }
        if (deltas.think) {
          store.handleTurnEvent(chId, turnId, {
            event: "thinking",
            data: { delta: deltas.think },
          });
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

    function clearObserverTimeout(turnId: string) {
      const timer = observerTimeoutsRef.current[turnId];
      if (timer) {
        clearTimeout(timer);
        delete observerTimeoutsRef.current[turnId];
      }
    }

    function clearAllObserverTimeouts() {
      for (const turnId of Object.keys(observerTimeoutsRef.current)) {
        clearTimeout(observerTimeoutsRef.current[turnId]);
      }
      observerTimeoutsRef.current = {};
    }

    function startObserverTimeout(chId: string, turnId: string) {
      clearObserverTimeout(turnId);
      observerTimeoutsRef.current[turnId] = setTimeout(() => {
        delete observerTimeoutsRef.current[turnId];
        // Flush pending deltas for this turn before finishing.
        const deltas = pendingDeltasRef.current[turnId];
        if (deltas && (deltas.text || deltas.think)) {
          cancelAnimationFrame(rafRef.current);
          flushDeltas(chId);
        }
        const ch = useChatStore.getState().getChannel(chId);
        if (ch.turns[turnId]) {
          useChatStore.getState().finishTurn(chId, turnId);
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        }
      }, OBSERVER_TURN_TIMEOUT);
    }

    function connect() {
      if (stopped) return;

      const token = getAuthToken();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      // Resume from the last seq we saw if reconnecting.
      const sinceParam = lastSeqRef.current != null ? `?since=${lastSeqRef.current}` : "";

      // First connect (no `since`) — clean up stale turns left over from a
      // previous mount (e.g. user navigated away mid-turn and came back).
      // Without this, the orphaned turn blocks the DB→store sync effect and
      // can produce duplicate messages. Same logic as `replay_lapsed`.
      if (lastSeqRef.current == null && channelId) {
        const store = useChatStore.getState();
        const ch = store.getChannel(channelId);
        const staleTurnIds = Object.keys(ch.turns);
        if (staleTurnIds.length > 0) {
          for (const turnId of staleTurnIds) {
            store.finishTurn(channelId, turnId);
          }
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        }
      }

      fetch(`${serverUrl}/api/v1/channels/${channelId}/events${sinceParam}`, {
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

          // Stream ended cleanly (server restart, etc.) — reconnect.
          if (!stopped) {
            retryTimer = setTimeout(connect, 1000);
          }
        })
        .catch((_err) => {
          if (stopped || ctrl.signal.aborted) return;
          const delay = Math.min(1000 * 2 ** retryCount, 30000);
          retryCount = Math.min(retryCount + 1, 10);
          retryTimer = setTimeout(connect, delay);
        });
    }

    function handleEvent(chId: string, wire: any) {
      const kind = wire?.kind;
      const payload = wire?.payload;
      if (typeof wire?.seq === "number") {
        lastSeqRef.current = wire.seq;
      }
      if (!kind) return;
      const store = useChatStore.getState();

      switch (kind) {
        case "new_message": {
          const ch = store.getChannel(chId);
          const turnActive = Object.keys(ch.turns).length > 0 || ch.isProcessing;
          const msg = payload?.message;

          // User messages are always added directly to the store.
          // The refetch path (invalidateQueries) is racy for user messages:
          // NEW_MESSAGE(user) arrives before TURN_STARTED, so turnActive is
          // false and we'd refetch — but TURN_STARTED arrives before the
          // refetch completes, and the sync effect in useChannelChat guards
          // on turnsCount === 0, so the user message never gets synced.
          // Direct-add avoids this race entirely.
          if (msg?.role === "user") {
            const existing = ch.messages;
            const isDuplicate = existing.some(
              (m) => m.id === msg.id || (m.role === "user" && m.content === msg.content &&
                Math.abs(new Date(m.created_at).getTime() - new Date(msg.created_at).getTime()) < 3000),
            );
            if (!isDuplicate) {
              store.addMessage(chId, {
                id: msg.id,
                session_id: msg.session_id,
                role: msg.role,
                content: msg.content ?? "",
                created_at: msg.created_at,
                metadata: msg.metadata,
              });
            }
            return;
          }

          // During a turn, suppress assistant new_message events to avoid
          // clobbering the synthetic streaming-content message in the store.
          if (turnActive) return;

          // No turn active — refetch session pages so the canonical row
          // appears (cheap because TanStack dedupes).
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
          return;
        }

        case "message_updated": {
          // Workflow lifecycle / step progress in-place edits.
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
          return;
        }

        case "turn_started": {
          const turnId = payload?.turn_id as string | undefined;
          const botId = payload?.bot_id as string | undefined;
          if (!turnId || !botId) return;
          const botName = botNamesRef.current[botId] ?? botId;
          const isPrimary = botId === primaryBotIdRef.current;
          // Remove any stale synthetic left by a previous mount's cleanup
          // (finishTurn on unmount/reconnect materializes the partial turn
          // as a message). Without this, the synthetic appears alongside
          // the fresh streaming indicator — a visible duplicate.
          const syntheticId = `turn-${turnId}`;
          const ch = store.getChannel(chId);
          if (ch.messages.some((m) => m.id === syntheticId)) {
            store.setMessages(chId, ch.messages.filter((m) => m.id !== syntheticId));
          }
          store.startTurn(chId, turnId, botId, botName, isPrimary);
          startObserverTimeout(chId, turnId);
          return;
        }

        case "turn_stream_token": {
          const turnId = payload?.turn_id as string | undefined;
          if (!turnId) return;
          if (!store.getChannel(chId).turns[turnId]) return;
          if (!pendingDeltasRef.current[turnId]) {
            pendingDeltasRef.current[turnId] = { text: "", think: "" };
          }
          pendingDeltasRef.current[turnId].text += (payload?.delta as string) ?? "";
          if (!rafRef.current) {
            rafRef.current = requestAnimationFrame(() => flushDeltas(chId));
          }
          return;
        }

        case "turn_stream_tool_start": {
          const turnId = payload?.turn_id as string | undefined;
          if (!turnId) return;
          // Flush any pending deltas before the tool chip appears.
          const deltas = pendingDeltasRef.current[turnId];
          if (deltas && (deltas.text || deltas.think)) {
            cancelAnimationFrame(rafRef.current);
            flushDeltas(chId);
          }
          if (!store.getChannel(chId).turns[turnId]) return;
          const argsStr =
            payload?.arguments && Object.keys(payload.arguments).length > 0
              ? JSON.stringify(payload.arguments)
              : undefined;
          store.handleTurnEvent(chId, turnId, {
            event: "tool_start",
            data: { tool: payload?.tool_name ?? "unknown", args: argsStr },
          });
          return;
        }

        case "turn_stream_tool_result": {
          const turnId = payload?.turn_id as string | undefined;
          if (!turnId) return;
          const deltas = pendingDeltasRef.current[turnId];
          if (deltas && (deltas.text || deltas.think)) {
            cancelAnimationFrame(rafRef.current);
            flushDeltas(chId);
          }
          if (!store.getChannel(chId).turns[turnId]) return;
          store.handleTurnEvent(chId, turnId, {
            event: "tool_result",
            data: {
              tool: payload?.tool_name,
              is_error: !!payload?.is_error,
              // envelope is the rendered ToolResultEnvelope dict from
              // tool_dispatch.py — drives the mimetype-keyed renderer.
              envelope: payload?.envelope,
            } as any,
          });
          return;
        }

        case "approval_requested": {
          // Prefer the explicit turn_id from the payload — set by every
          // current publisher (turn_event_emit, tool_dispatch). Fall
          // back to the most recent turn for the channel only when the
          // payload omits it (legacy / script-driven admin approvals
          // that fire outside any turn context). Without the explicit
          // routing, a member-bot turn requesting approval while the
          // primary turn is still active would land in the primary's
          // slot and never resolve.
          const ch = store.getChannel(chId);
          const turnIds = Object.keys(ch.turns);
          const explicitTurnId = payload?.turn_id as string | undefined;
          const targetTurnId =
            explicitTurnId && ch.turns[explicitTurnId]
              ? explicitTurnId
              : turnIds[turnIds.length - 1];
          if (!targetTurnId) return;
          const deltas = pendingDeltasRef.current[targetTurnId];
          if (deltas && (deltas.text || deltas.think)) {
            cancelAnimationFrame(rafRef.current);
            flushDeltas(chId);
          }
          store.handleTurnEvent(chId, targetTurnId, {
            event: "approval_request",
            data: {
              approval_id: payload?.approval_id,
              tool: payload?.tool_name,
              reason: payload?.reason,
              capability: payload?.capability,
            } as any,
          });
          return;
        }

        case "approval_resolved": {
          const ch = store.getChannel(chId);
          // Find the turn that has the matching approval id and dispatch.
          for (const [turnId, turn] of Object.entries(ch.turns)) {
            if (turn.toolCalls.some((tc) => tc.approvalId === payload?.approval_id)) {
              store.handleTurnEvent(chId, turnId, {
                event: "approval_resolved",
                data: {
                  approval_id: payload?.approval_id,
                  decision: payload?.decision,
                } as any,
              });
              return;
            }
          }
          return;
        }

        case "skill_auto_inject": {
          const turnId = payload?.turn_id as string | undefined;
          if (!turnId) return;
          if (!store.getChannel(chId).turns[turnId]) return;
          store.handleTurnEvent(chId, turnId, {
            event: "skill_auto_inject",
            data: {
              skill_id: payload?.skill_id,
              skill_name: payload?.skill_name,
              similarity: payload?.similarity,
              source: payload?.source,
            },
          });
          return;
        }

        case "turn_ended": {
          const turnId = payload?.turn_id as string | undefined;
          if (!turnId) return;
          clearObserverTimeout(turnId);
          // Flush any remaining deltas for this turn.
          const deltas = pendingDeltasRef.current[turnId];
          if (deltas && (deltas.text || deltas.think)) {
            cancelAnimationFrame(rafRef.current);
            flushDeltas(chId);
          }
          delete pendingDeltasRef.current[turnId];
          // Finalize the turn (materialize content as a synthetic message).
          if (store.getChannel(chId).turns[turnId]) {
            if (payload?.error) {
              store.setError(chId, String(payload.error));
            }
            store.finishTurn(chId, turnId);
            // Pull the canonical DB row in (replaces the synthetic message).
            queryClient.invalidateQueries({ queryKey: ["session-messages"] });
          }
          return;
        }

        case "delivery_failed": {
          // Surface as a channel-level error so the UI can render a chip.
          if (payload?.last_error) {
            store.setError(chId, `Delivery failed: ${payload.last_error}`);
          }
          return;
        }

        case "replay_lapsed": {
          // Buffer too short OR our subscriber overflowed. Either way the
          // safe move is to drop in-flight state and refetch from REST.
          // We'll reconnect cleanly on the next loop iteration.
          for (const turnId of Object.keys(observerTimeoutsRef.current)) {
            clearObserverTimeout(turnId);
          }
          pendingDeltasRef.current = {};
          rafRef.current = 0;
          const ch = store.getChannel(chId);
          for (const turnId of Object.keys(ch.turns)) {
            store.finishTurn(chId, turnId);
          }
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
          // Reset the cursor so the next connect resumes from current head.
          lastSeqRef.current = null;
          return;
        }

        case "pinned_file_updated": {
          // A pinned file's content changed — invalidate per-path query so
          // the PinnedPanel component re-fetches.
          if (payload?.path) {
            queryClient.invalidateQueries({
              queryKey: ["pinned-panel-content", payload.path],
            });
          }
          // Also refresh the channel data so pinned_panels list stays current
          queryClient.invalidateQueries({ queryKey: ["channels", chId] });
          return;
        }

        case "shutdown": {
          // Server is going down — let the reconnect backoff handle resume.
          return;
        }

        default:
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

      // Clean up any in-flight turns for this channel so they don't linger
      // as stale state in the store (e.g. user navigates away mid-turn).
      // Without SSE, we can't receive TURN_ENDED, so finishTurn now and
      // let the query refetch canonical rows on next mount.
      if (channelId) {
        const store = useChatStore.getState();
        const ch = store.getChannel(channelId);
        const turnIds = Object.keys(ch.turns);
        if (turnIds.length > 0) {
          for (const turnId of turnIds) {
            store.finishTurn(channelId, turnId);
          }
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        }
      }
    };
  }, [channelId, queryClient, flushDeltas]);
}
