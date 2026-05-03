import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getAuthToken } from "../../stores/auth";
import { getApiBase, isApiConfigured } from "../client";
import { useChatStore } from "../../stores/chat";
import { useBots } from "./useBots";
import type { Message } from "../../types/api";
import {
  isHarnessQuestionMessage,
  isHarnessQuestionTransportMessage,
} from "../../components/chat/harnessQuestionMessages";

/** Timeout (ms) for in-flight turn observation — if no SSE event arrives
 *  for a given turn in this window, force-finish. Resets on every event
 *  dispatched to the turn (TURN_STARTED, TEXT_DELTA, TOOL_CALL_*, etc.).
 *
 *  Tuned to 180s because: single long-running tool calls (deep file reads,
 *  multi-sub-call tools like `file 1/6`, or slow external APIs like
 *  search/preview) can legitimately go silent for over a minute before the
 *  next progress event. 60s was reaping live turns and producing the
 *  "assistant poofs to nothing" bug users saw for weeks. A missing
 *  turn_ended is genuinely abnormal — a 3-minute grace window is still
 *  short enough to clean up after a real server crash. */
const OBSERVER_TURN_TIMEOUT = 180_000;

// ---------------------------------------------------------------------------
// Module-level subscriber registry. Lets outside consumers tap the raw event
// stream without the hook having to re-dispatch through zustand or a context.
// The WidgetStreamBroker uses this to piggyback on the channel's existing SSE
// connection and fan events out to iframes via postMessage, so we don't pay
// one SSE socket per streaming widget on a dashboard.
//
// Subscribers fire AFTER the session filter (so a run-view modal's subscribers
// only see in-scope events) but BEFORE the switch dispatch (so subscribers
// don't depend on store reduction ordering). Events like replay_lapsed /
// shutdown pass through — subscribers can react directly.
// ---------------------------------------------------------------------------

export type ChannelEventFrame = {
  kind: string;
  channel_id?: string;
  seq?: number;
  ts?: number;
  payload?: unknown;
  [k: string]: unknown;
};

type ChannelEventCallback = (event: ChannelEventFrame) => void;

const channelEventSubscribers = new Map<string, Set<ChannelEventCallback>>();

// Last SSE bus seq seen per subscription, persisted across hook remounts so a
// dock that unmounts mid-turn (e.g. spatial-canvas mini-chat dismissed to look
// at the map) can resume from `?since=N` instead of starting at the live tail.
// Keyed by `${subscribePath}:${channelId}` so the channel-events and
// session-events streams don't collide. Stale entries (channel goes idle for
// hours, server's 256-event ring rolls past) trigger `replay_lapsed` on the
// next connect and the existing recovery path reseeds via /state.
const lastSeqByChannel = new Map<string, number>();
function seqMapKey(subscribePath: "channels" | "sessions", channelId: string): string {
  return `${subscribePath}:${channelId}`;
}

function normalizeEventMessage(message: any): Message {
  return {
    id: message.id,
    session_id: message.session_id,
    role: message.role,
    content: message.content ?? "",
    created_at: message.created_at,
    ...(message.correlation_id ? { correlation_id: message.correlation_id } : {}),
    ...(message.metadata ? { metadata: message.metadata } : {}),
    ...(message.attachments ? { attachments: message.attachments } : {}),
    ...(message.tool_calls ? { tool_calls: message.tool_calls } : {}),
  };
}

function isCompactionRunMessage(message: any): boolean {
  return message?.role === "assistant" && message?.metadata?.kind === "compaction_run";
}

function invalidateCompactionDerivedQueries(queryClient: ReturnType<typeof useQueryClient>, channelId: string): void {
  queryClient.invalidateQueries({ queryKey: ["session-header-stats", channelId] });
  queryClient.invalidateQueries({ queryKey: ["channel-context-breakdown", channelId] });
}

function publishChannelEvent(channelId: string, wire: ChannelEventFrame): void {
  const subs = channelEventSubscribers.get(channelId);
  if (!subs || subs.size === 0) return;
  for (const cb of subs) {
    try {
      cb(wire);
    } catch (err) {
      console.error("channel event subscriber threw:", err);
    }
  }
}

/**
 * Observe raw channel-event frames for a given channel. The primary
 * `useChannelEvents` hook still owns the SSE connection + store dispatch;
 * this hook is a pure observer tap for consumers that need to react to events
 * without re-opening their own SSE socket (e.g. the widget stream broker).
 *
 * Callback receives the full wire frame (`{kind, seq, ts, payload, ...}`).
 * Cleanup on unmount is automatic. Pass a stable callback (useCallback) or
 * expect the subscription to re-register on every render.
 */
export function useChannelEventSubscription(
  channelId: string | undefined,
  cb: ChannelEventCallback,
): void {
  useEffect(() => {
    if (!channelId) return;
    let subs = channelEventSubscribers.get(channelId);
    if (!subs) {
      subs = new Set();
      channelEventSubscribers.set(channelId, subs);
    }
    subs.add(cb);
    return () => {
      const current = channelEventSubscribers.get(channelId);
      if (!current) return;
      current.delete(cb);
      if (current.size === 0) channelEventSubscribers.delete(channelId);
    };
  }, [channelId, cb]);
}

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
export interface UseChannelEventsOptions {
  /** When set, drop events whose `payload.session_id` does not match. Used
   *  by the run-view modal to subscribe to the parent channel's SSE stream
   *  but dispatch only the sub-session's turns/messages into the store. */
  sessionFilter?: string;
  /** When set, dispatch chat-store mutations under this key instead of
   *  ``channelId``. The modal passes ``runSessionId`` so its turns/messages
   *  land in a separate store namespace from the parent channel's. */
  dispatchChannelId?: string;
  /** Which SSE endpoint family to subscribe on. Defaults to "channels"
   *  (``/api/v1/channels/{id}/events``). Set to "sessions" for channel-less
   *  ephemeral sessions — the id passed as ``channelId`` is then a session_id
   *  and the hook subscribes to ``/api/v1/sessions/{id}/events``. */
  subscribePath?: "channels" | "sessions";
}

export function useChannelEvents(
  channelId: string | undefined,
  primaryBotId?: string,
  options?: UseChannelEventsOptions,
) {
  const sessionFilter = options?.sessionFilter;
  const dispatchChannelId = options?.dispatchChannelId;
  const subscribePath = options?.subscribePath ?? "channels";
  const subscribePathRef = useRef(subscribePath);
  subscribePathRef.current = subscribePath;
  // Keep latest values in refs so reconnect doesn't churn.
  const sessionFilterRef = useRef(sessionFilter);
  sessionFilterRef.current = sessionFilter;
  const dispatchChannelIdRef = useRef(dispatchChannelId);
  dispatchChannelIdRef.current = dispatchChannelId;
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

  // Last bus seq we received, for replay-on-reconnect. Seeded from the
  // module-level cache on mount so a remount (dock close + reopen) resumes
  // from where the previous mount left off rather than skipping to the live
  // tail. Lazy init runs only on first render of this hook instance.
  const lastSeqRef = useRef<number | null>(null);
  const seqInitRef = useRef(false);
  if (!seqInitRef.current && channelId) {
    const cached = lastSeqByChannel.get(seqMapKey(subscribePath, channelId));
    if (typeof cached === "number") lastSeqRef.current = cached;
    seqInitRef.current = true;
  }

  const flushDeltas = useCallback(
    (chId: string) => {
      rafRef.current = 0;
      const store = useChatStore.getState();
      const pending = pendingDeltasRef.current;
      const storeKey = dispatchChannelIdRef.current ?? chId;
      for (const [turnId, deltas] of Object.entries(pending)) {
        if (!deltas.text && !deltas.think) continue;
        const ch = store.channels[storeKey];
        if (!ch?.turns[turnId]) continue;
        if (deltas.text) {
          store.handleTurnEvent(storeKey, turnId, {
            event: "text_delta",
            data: { delta: deltas.text },
          });
        }
        if (deltas.think) {
          store.handleTurnEvent(storeKey, turnId, {
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

    if (!isApiConfigured()) return;

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
      const storeKey = dispatchChannelIdRef.current ?? chId;
      observerTimeoutsRef.current[turnId] = setTimeout(() => {
        delete observerTimeoutsRef.current[turnId];
        // Flush pending deltas for this turn before finishing.
        const deltas = pendingDeltasRef.current[turnId];
        if (deltas && (deltas.text || deltas.think)) {
          cancelAnimationFrame(rafRef.current);
          flushDeltas(chId);
        }
        const ch = useChatStore.getState().getChannel(storeKey);
        if (ch.turns[turnId]) {
          useChatStore.getState().finishTurn(storeKey, turnId);
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

      // First connect (no `since`) — ask for a fresh state snapshot instead
      // of materializing any local in-flight turn. The turn may still be
      // streaming on another route, and finishing it here drops live text /
      // tool rows before SSE or /state can catch up.
      if (lastSeqRef.current == null && channelId) {
        queryClient.invalidateQueries({ queryKey: ["channel-state", channelId] });
        const storeKey = dispatchChannelIdRef.current;
        if (storeKey) {
          queryClient.invalidateQueries({ queryKey: ["session-state", storeKey] });
        }
      }

      fetch(`${getApiBase()}/api/v1/${subscribePathRef.current}/${channelId}/events${sinceParam}`, {
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
        lastSeqByChannel.set(seqMapKey(subscribePathRef.current, chId), wire.seq);
      }
      if (!kind) return;
      // Session filter: drop events whose payload doesn't match the target
      // session. Used by the run-view modal so only the sub-session's
      // turns/messages dispatch into the store — the parent channel's
      // events (outside the sub-session) are ignored by this subscription.
      const filter = sessionFilterRef.current;
      if (filter) {
        const msgSid = payload?.message?.session_id;
        const payloadSid = payload?.session_id;
        const eventSid = msgSid ?? payloadSid;
        // Treat both ``undefined`` (field absent on wire) and ``null``
        // (field present but unset — the default when ``TurnStartedPayload``
        // / ``TurnEndedPayload`` were extended with an optional
        // ``session_id``) as "no session tag, let it through". The
        // discriminator only fires when the payload actively claims a
        // different session than the one this subscription is filtering
        // for.
        if (eventSid != null && eventSid !== filter) return;
        // Events without any session_id (replay_lapsed, shutdown,
        // delivery_failed, legacy turn-lifecycle publishes) pass
        // through — they're connection-scoped.
      }
      // Fan out to observer subscribers (e.g. WidgetStreamBroker). Fires
      // BEFORE store reduction so the broker doesn't depend on our dispatch
      // order; widgets just want the raw frame.
      publishChannelEvent(chId, wire);
      const store = useChatStore.getState();
      // Dispatch key — the modal uses the sub-session's id so its state
      // doesn't collide with the parent channel's chat-store slot.
      const storeKey = dispatchChannelIdRef.current ?? chId;

      switch (kind) {
        case "new_message": {
          const ch = store.getChannel(storeKey);
          const turnActive = Object.keys(ch.turns).length > 0 || ch.isProcessing;
          const msg = payload?.message;
          const normalizedMessage = msg ? normalizeEventMessage(msg) : null;

          if (normalizedMessage && isHarnessQuestionTransportMessage(normalizedMessage)) {
            queryClient.invalidateQueries({ queryKey: ["session-messages"] });
            return;
          }

          // User messages are always added directly to the store.
          // The refetch path (invalidateQueries) is racy for user messages:
          // NEW_MESSAGE(user) arrives before TURN_STARTED, so turnActive is
          // false and we'd refetch — but TURN_STARTED arrives before the
          // refetch completes, and the sync effect in useChannelChat guards
          // on turnsCount === 0, so the user message never gets synced.
          // Direct-add avoids this race entirely.
          if (msg?.role === "user") {
            const existing = ch.messages;
            const incomingClientLocalId = normalizedMessage?.metadata?.client_local_id;
            const isDuplicate = existing.some(
              (m) => m.id === msg.id ||
                (incomingClientLocalId && m.metadata?.client_local_id === incomingClientLocalId) ||
                (m.role === "user" && m.content === msg.content &&
                Math.abs(new Date(m.created_at).getTime() - new Date(msg.created_at).getTime()) < 3000),
            );
            // Replace any optimistic user message (msg-*) created within 5s
            // of the server message, preferring the stable client-local id.
            // Content may differ (e.g. typed text vs "[User sent attachment(s)]")
            // so timestamp proximity stays as a fallback.
            const serverTs = new Date(msg.created_at).getTime();
            const withoutOptimistic = existing.filter(
              (m) => !(m.id.startsWith("msg-") && m.role === "user" && (
                (incomingClientLocalId && m.metadata?.client_local_id === incomingClientLocalId) ||
                Math.abs(new Date(m.created_at).getTime() - serverTs) < 5000
              )),
            );
            if (withoutOptimistic.length < existing.length) {
              // Had an optimistic message — replace it with the server version
              store.setMessages(storeKey, [...withoutOptimistic, normalizedMessage!]);
            } else if (!isDuplicate) {
              store.addMessage(storeKey, normalizedMessage!);
            }
            return;
          }

          if (normalizedMessage && isCompactionRunMessage(normalizedMessage)) {
            store.upsertMessage(storeKey, normalizedMessage);
            queryClient.invalidateQueries({ queryKey: ["session-messages"] });
            if (subscribePathRef.current === "channels") {
              invalidateCompactionDerivedQueries(queryClient, chId);
            }
            return;
          }

          if (
            normalizedMessage
            && isHarnessQuestionMessage(normalizedMessage)
          ) {
            store.upsertMessage(storeKey, normalizedMessage);
            queryClient.invalidateQueries({ queryKey: ["session-messages"] });
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
          const msg = payload?.message;
          if (msg && isCompactionRunMessage(msg)) {
            store.upsertMessage(storeKey, normalizeEventMessage(msg));
            if (subscribePathRef.current === "channels") {
              invalidateCompactionDerivedQueries(queryClient, chId);
            }
          } else if (msg) {
            const normalizedMessage = normalizeEventMessage(msg);
            if (isHarnessQuestionMessage(normalizedMessage)) {
              store.upsertMessage(storeKey, normalizedMessage);
            }
          }
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
          const ch = store.getChannel(storeKey);
          if (ch.messages.some((m) => m.id === syntheticId)) {
            store.setMessages(storeKey, ch.messages.filter((m) => m.id !== syntheticId));
          }
          store.startTurn(storeKey, turnId, botId, botName, isPrimary);
          startObserverTimeout(chId, turnId);
          return;
        }

        case "turn_stream_token": {
          const turnId = payload?.turn_id as string | undefined;
          if (!turnId) return;
          if (!store.getChannel(storeKey).turns[turnId]) return;
          // Any alive-proof event resets the 60s observer so long
          // generations / slow tools don't get force-finished.
          startObserverTimeout(chId, turnId);
          if (!pendingDeltasRef.current[turnId]) {
            pendingDeltasRef.current[turnId] = { text: "", think: "" };
          }
          pendingDeltasRef.current[turnId].text += (payload?.delta as string) ?? "";
          if (!rafRef.current) {
            rafRef.current = requestAnimationFrame(() => flushDeltas(chId));
          }
          return;
        }

        case "turn_stream_thinking": {
          // Reasoning deltas from providers that stream summary text
          // (OpenAI Responses, Anthropic thinking_delta, DeepSeek <think>).
          // Batched with the same RAF flush as text_delta so a single frame
          // dispatches both streams to the store.
          const turnId = payload?.turn_id as string | undefined;
          const deltaStr = (payload?.delta as string) ?? "";
          if (!turnId) return;
          if (!store.getChannel(storeKey).turns[turnId]) return;
          startObserverTimeout(chId, turnId);
          if (!pendingDeltasRef.current[turnId]) {
            pendingDeltasRef.current[turnId] = { text: "", think: "" };
          }
          pendingDeltasRef.current[turnId].think += deltaStr;
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
          if (!store.getChannel(storeKey).turns[turnId]) return;
          startObserverTimeout(chId, turnId);
          const argsStr =
            payload?.arguments && Object.keys(payload.arguments).length > 0
              ? JSON.stringify(payload.arguments)
              : undefined;
          store.handleTurnEvent(storeKey, turnId, {
            event: "tool_start",
            data: {
              tool: payload?.tool_name ?? "unknown",
              tool_call_id: payload?.tool_call_id,
              args: argsStr,
              surface: payload?.surface,
              summary: payload?.summary,
            },
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
          if (!store.getChannel(storeKey).turns[turnId]) return;
          startObserverTimeout(chId, turnId);
          store.handleTurnEvent(storeKey, turnId, {
            event: "tool_result",
            data: {
              tool: payload?.tool_name,
              tool_call_id: payload?.tool_call_id,
              is_error: !!payload?.is_error,
              envelope: payload?.envelope,
              surface: payload?.surface,
              summary: payload?.summary,
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
          const ch = store.getChannel(storeKey);
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
          startObserverTimeout(chId, targetTurnId);
          store.handleTurnEvent(storeKey, targetTurnId, {
            event: "approval_request",
            data: {
              approval_id: payload?.approval_id,
              tool: payload?.tool_name,
              reason: payload?.reason,
              capability: payload?.capability,
            } as any,
          });
          // Also refresh the orphan-approvals list so background/post-refresh
          // approvals that don't map to a live turn still surface inline.
          queryClient.invalidateQueries({ queryKey: ["approvals", "channel", chId] });
          queryClient.invalidateQueries({ queryKey: ["approvals", undefined, "pending"] });
          return;
        }

        case "approval_resolved": {
          const ch = store.getChannel(storeKey);
          // Find the turn that has the matching approval id and dispatch.
          for (const [turnId, turn] of Object.entries(ch.turns)) {
            if (turn.toolCalls.some((tc) => tc.approvalId === payload?.approval_id)) {
              startObserverTimeout(chId, turnId);
              store.handleTurnEvent(storeKey, turnId, {
                event: "approval_resolved",
                data: {
                  approval_id: payload?.approval_id,
                  decision: payload?.decision,
                } as any,
              });
              break;
            }
          }
          queryClient.invalidateQueries({ queryKey: ["approvals", "channel", chId] });
          queryClient.invalidateQueries({ queryKey: ["approvals", undefined, "pending"] });
          return;
        }

        case "skill_auto_inject": {
          const turnId = payload?.turn_id as string | undefined;
          if (!turnId) return;
          if (!store.getChannel(storeKey).turns[turnId]) return;
          startObserverTimeout(chId, turnId);
          store.handleTurnEvent(storeKey, turnId, {
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

        case "llm_status": {
          const turnId = payload?.turn_id as string | undefined;
          if (!turnId) return;
          if (!store.getChannel(storeKey).turns[turnId]) return;
          // Reset the observer timeout — the server is still working
          // (retrying / falling back). Prevents the 60s timeout from
          // killing the turn during long rate-limit waits.
          startObserverTimeout(chId, turnId);
          store.handleTurnEvent(storeKey, turnId, {
            event: "llm_status",
            data: {
              status: payload?.status,
              model: payload?.model,
              reason: payload?.reason,
              attempt: payload?.attempt,
              max_retries: payload?.max_retries,
              wait_seconds: payload?.wait_seconds,
              fallback_model: payload?.fallback_model,
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
          if (store.getChannel(storeKey).turns[turnId]) {
            if (payload?.error) {
              const error = String(payload.error);
              store.handleTurnEvent(storeKey, turnId, {
                event: "error",
                data: { message: error },
              });
              if (error !== "cancelled") {
                store.setError(storeKey, error);
              }
            }
            store.finishTurn(storeKey, turnId);
          } else if (payload?.error && String(payload.error) !== "cancelled") {
            // Slot may have been reaped early (e.g. snapshot ghost-kill)
            // but the error still needs to surface.
            store.setError(storeKey, String(payload.error));
          }
          // Always pull the canonical DB row in. Even when the slot is
          // already gone, the assistant Message has just landed — without
          // this invalidate, a prematurely-reaped turn stays visible only
          // as its partial synthetic until the user navigates away.
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
          queryClient.invalidateQueries({ queryKey: ["session-harness-status"] });
          return;
        }

        case "delivery_failed": {
          // Surface as a channel-level error so the UI can render a chip.
          if (payload?.last_error) {
            store.setError(storeKey, `Delivery failed: ${payload.last_error}`);
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
          const ch = store.getChannel(storeKey);
          for (const turnId of Object.keys(ch.turns)) {
            store.finishTurn(storeKey, turnId);
          }
          queryClient.invalidateQueries({ queryKey: ["session-messages"] });
          // Refetch the channel-state snapshot so in-flight turns (tool
          // calls, awaiting-approval cards, auto-injected skills) rehydrate
          // instead of waiting for the next SSE event. Phase 3: together
          // with the mount-seed this deprecates the 256-event replay buffer.
          queryClient.invalidateQueries({ queryKey: ["channel-state", chId] });
          if (storeKey) {
            queryClient.invalidateQueries({ queryKey: ["session-state", storeKey] });
          }
          // Reset the cursor so the next connect resumes from current head.
          // Also drop the persisted entry — otherwise a remount would resubmit
          // a `since` the server already told us is out of range.
          lastSeqRef.current = null;
          lastSeqByChannel.delete(seqMapKey(subscribePathRef.current, chId));
          return;
        }

        case "pinned_file_updated": {
          // A pinned file's content changed — invalidate the pinned-files
          // widget preview query for that path.
          if (payload?.path) {
            queryClient.invalidateQueries({
              queryKey: ["pinned-files-preview", chId, payload.path],
            });
          }
          return;
        }

        case "context_budget": {
          // Mid-turn context budget snapshot emitted by the agent loop.
          // Feeds the session header's token/utilization read-out via
          // ``chatState.contextBudget`` (see sessionHeaderChrome.ts).
          // Payload shape lives at app/domain/payloads.py::ContextBudgetPayload.
          const consumed = payload?.consumed_tokens;
          const total = payload?.total_tokens;
          const utilization = payload?.utilization;
          if (
            typeof consumed === "number" &&
            typeof total === "number" &&
            typeof utilization === "number"
          ) {
            store.setContextBudget(storeKey, { utilization, consumed, total });
          }
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
    };
  }, [channelId, queryClient, flushDeltas]);
}
