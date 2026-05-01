import test from "node:test";
import assert from "node:assert/strict";
import {
  resetWidgetStreamSubscriptionsForSource,
  upsertWidgetStreamSubscription,
} from "./widgetStreamBrokerState.ts";

function fakeWindow(label: string): Window {
  return { label } as unknown as Window;
}

test("widget broker probe reset removes stale subscriptions for the same iframe source", () => {
  const sourceA = fakeWindow("a");
  const sourceB = fakeWindow("b");
  const subscriptions = [
    { source: sourceA, subId: "reload", kinds: ["widget_reload"] },
    { source: sourceB, subId: "reload", kinds: ["widget_reload"] },
    { source: sourceA, subId: "events", kinds: null },
  ];

  const reset = resetWidgetStreamSubscriptionsForSource(subscriptions, sourceA);

  assert.deepEqual(reset, [
    { source: sourceB, subId: "reload", kinds: ["widget_reload"] },
  ]);
});

test("widget broker subscribe replaces an existing source/subId pair", () => {
  const source = fakeWindow("a");
  const other = fakeWindow("b");
  const subscriptions = [
    { source, subId: "reload", kinds: ["widget_reload"] },
    { source: other, subId: "reload", kinds: ["widget_reload"] },
  ];

  const upserted = upsertWidgetStreamSubscription(subscriptions, {
    source,
    subId: "reload",
    kinds: ["turn_delta"],
  });

  assert.deepEqual(upserted, [
    { source: other, subId: "reload", kinds: ["widget_reload"] },
    { source, subId: "reload", kinds: ["turn_delta"] },
  ]);
});
