import test from "node:test";
import assert from "node:assert/strict";
import {
  resetWidgetStreamSubscriptionsForSource,
  shouldDeliverWidgetStreamEvent,
  upsertWidgetStreamSubscription,
  WIDGET_STREAM_HIGH_VOLUME_KINDS,
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

test("high-volume kinds are NOT delivered to catch-all subscribers", () => {
  // turn_stream_token at 50/sec was the dominant cost when widgets used
  // catch-all subs. Default policy is now opt-in.
  for (const kind of WIDGET_STREAM_HIGH_VOLUME_KINDS) {
    assert.equal(shouldDeliverWidgetStreamEvent({ kinds: null }, kind), false);
    assert.equal(shouldDeliverWidgetStreamEvent({ kinds: [] }, kind), false);
    assert.equal(shouldDeliverWidgetStreamEvent({ kinds: ["unrelated"] }, kind), false);
  }
});

test("high-volume kinds ARE delivered to subscribers that opt in", () => {
  assert.equal(
    shouldDeliverWidgetStreamEvent({ kinds: ["turn_stream_token"] }, "turn_stream_token"),
    true,
  );
  assert.equal(
    shouldDeliverWidgetStreamEvent(
      { kinds: ["other", "turn_stream_thinking"] },
      "turn_stream_thinking",
    ),
    true,
  );
});

test("normal-volume kinds keep the catch-all default", () => {
  // A `kinds: null` (no filter) sub still gets every non-high-volume event,
  // matching pre-gate behavior so existing widgets aren't broken.
  assert.equal(shouldDeliverWidgetStreamEvent({ kinds: null }, "widget_reload"), true);
  assert.equal(shouldDeliverWidgetStreamEvent({ kinds: null }, "tool_result"), true);
  assert.equal(
    shouldDeliverWidgetStreamEvent({ kinds: ["widget_reload"] }, "widget_reload"),
    true,
  );
  assert.equal(
    shouldDeliverWidgetStreamEvent({ kinds: ["widget_reload"] }, "tool_result"),
    false,
  );
});
