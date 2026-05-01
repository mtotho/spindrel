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
