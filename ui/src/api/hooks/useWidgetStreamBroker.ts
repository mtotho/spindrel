import { useCallback, useEffect, useRef } from "react";
import {
  useChannelEventSubscription,
  type ChannelEventFrame,
} from "./useChannelEvents";
import {
  resetWidgetStreamSubscriptionsForSource,
  upsertWidgetStreamSubscription,
  type WidgetStreamSubscription,
} from "./widgetStreamBrokerState";

function isPerfDebugEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return (
      window.localStorage.getItem("spindrelPerfDebug") === "1" ||
      new URLSearchParams(window.location.search).get("perf") === "1"
    );
  } catch {
    return false;
  }
}

function debugBroker(channelId: string, message: string, count: number): void {
  if (!isPerfDebugEnabled()) return;
  console.debug("[spindrel:perf] widget broker", {
    channelId,
    message,
    subscriptions: count,
  });
}

/**
 * Host-side widget stream broker.
 *
 * Widgets render in sandboxed iframes and ask for typed event streams via
 * `window.spindrel.stream(kinds, cb)`. The naive implementation opens one SSE
 * socket per widget, so a dashboard with five streaming pins ends up with six
 * SSE connections (five from widgets + the host's own channel events stream).
 * This broker collapses all iframe subscriptions onto the host's single
 * channel-events SSE via a postMessage fan-out.
 *
 * Wire protocol (all messages carry `{__spindrel: true}`):
 *
 * iframe → host:
 *   `stream_ready_probe`                              — asks host if broker is mounted
 *   `stream_subscribe  {subId, kinds, channelId}`     — open a subscription
 *   `stream_unsubscribe {subId}`                      — close it
 *
 * host → iframe:
 *   `stream_ready_ack  {channelId}`                   — response to probe; confirms broker
 *   `stream_event      {subId, event}`                — fan-out of matching event
 *
 * If no ack arrives, the preamble's `stream()` falls back to opening its own
 * `/api/v1/widget-actions/stream` SSE (dev sandbox, standalone viewers, any
 * widget outside a broker-hosting page).
 */
export function useWidgetStreamBroker(channelId: string | undefined): void {
  const subsRef = useRef<WidgetStreamSubscription[]>([]);

  // Handle inbound probe/subscribe/unsubscribe from any iframe on the page.
  useEffect(() => {
    if (!channelId) return;
    const brokerChannelId = channelId;
    function onMessage(ev: MessageEvent) {
      const msg = ev.data;
      if (!msg || typeof msg !== "object") return;
      if ((msg as { __spindrel?: unknown }).__spindrel !== true) return;
      const source = ev.source as Window | null;
      if (!source) return;
      const type = (msg as { type?: unknown }).type;

      if (type === "stream_ready_probe") {
        subsRef.current = resetWidgetStreamSubscriptionsForSource(
          subsRef.current,
          source,
        );
        debugBroker(brokerChannelId, "source probe reset", subsRef.current.length);
        try {
          source.postMessage(
            { __spindrel: true, type: "stream_ready_ack", channelId: brokerChannelId },
            "*",
          );
        } catch {
          // Cross-origin edge case (shouldn't happen for srcDoc iframes).
        }
        return;
      }

      if (type === "stream_subscribe") {
        const claimed = (msg as { channelId?: unknown }).channelId;
        if (typeof claimed === "string" && claimed !== brokerChannelId) {
          // Subscription scoped to a different channel — not ours to serve.
          return;
        }
        const subId = (msg as { subId?: unknown }).subId;
        if (typeof subId !== "string") return;
        const rawKinds = (msg as { kinds?: unknown }).kinds;
        const kinds = Array.isArray(rawKinds)
          ? rawKinds.filter((k): k is string => typeof k === "string")
          : null;
        subsRef.current = upsertWidgetStreamSubscription(subsRef.current, {
          source,
          subId,
          kinds,
        });
        debugBroker(brokerChannelId, "subscribe", subsRef.current.length);
        return;
      }

      if (type === "stream_unsubscribe") {
        const subId = (msg as { subId?: unknown }).subId;
        if (typeof subId !== "string") return;
        subsRef.current = subsRef.current.filter(
          (s) => !(s.subId === subId && s.source === source),
        );
        debugBroker(brokerChannelId, "unsubscribe", subsRef.current.length);
        return;
      }
    }
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      subsRef.current = [];
    };
  }, [channelId]);

  // Fan-out channel events to matching iframe subscriptions. Stable callback
  // so the subscription in useChannelEventSubscription doesn't re-register
  // each render.
  const onChannelEvent = useCallback((event: ChannelEventFrame) => {
    const kind = event?.kind;
    if (!kind || typeof kind !== "string") return;
    // Copy the subscriber list — postMessage is synchronous in spec but
    // defensive against a handler mutating subsRef from inside the iframe.
    const snapshot = subsRef.current.slice();
    for (const sub of snapshot) {
      if (sub.kinds && !sub.kinds.includes(kind)) continue;
      try {
        sub.source.postMessage(
          {
            __spindrel: true,
            type: "stream_event",
            subId: sub.subId,
            event,
          },
          "*",
        );
      } catch {
        // Iframe was detached or cross-origin blocked — next unsubscribe
        // (or unmount) will clean up.
      }
    }
  }, []);

  useChannelEventSubscription(channelId, onChannelEvent);
}
