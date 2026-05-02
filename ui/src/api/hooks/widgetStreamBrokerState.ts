export type WidgetStreamSubscription = {
  source: Window;
  subId: string;
  kinds: string[] | null;
};

export function resetWidgetStreamSubscriptionsForSource(
  subscriptions: WidgetStreamSubscription[],
  source: Window,
): WidgetStreamSubscription[] {
  return subscriptions.filter((sub) => sub.source !== source);
}

export function upsertWidgetStreamSubscription(
  subscriptions: WidgetStreamSubscription[],
  next: WidgetStreamSubscription,
): WidgetStreamSubscription[] {
  return [
    ...subscriptions.filter(
      (sub) => !(sub.source === next.source && sub.subId === next.subId),
    ),
    next,
  ];
}

// High-volume event kinds — delivered only to subscribers that explicitly
// listed them in `kinds`. A catch-all (`kinds: null`) subscription does NOT
// receive them. Streaming text deltas were the dominant main-thread cost
// when widgets pinned to a chat surface used catch-all subscriptions.
export const WIDGET_STREAM_HIGH_VOLUME_KINDS = new Set<string>([
  "turn_stream_token",
  "turn_stream_thinking",
]);

/** Returns true when this subscription should receive an event of `kind`. */
export function shouldDeliverWidgetStreamEvent(
  sub: Pick<WidgetStreamSubscription, "kinds">,
  kind: string,
): boolean {
  if (WIDGET_STREAM_HIGH_VOLUME_KINDS.has(kind)) {
    return !!sub.kinds && sub.kinds.includes(kind);
  }
  if (!sub.kinds) return true;
  return sub.kinds.includes(kind);
}
