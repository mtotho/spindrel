import test from "node:test";
import assert from "node:assert/strict";

import { contextualNavigationState, readContextualNavigationState, sameNavigationTarget } from "./contextualNavigation";
import { attentionDeckHref, attentionHubHref, CONTEXT_BLOAT_HREF, DAILY_HEALTH_HREF, MEMORY_CENTER_HREF, widgetPinHref } from "./hubRoutes";

test("hub route helpers point mobile sections at durable surfaces", () => {
  assert.equal(attentionHubHref(), "/hub/attention");
  assert.equal(attentionHubHref("item/1"), "/hub/attention?item=item%2F1");
  assert.equal(attentionDeckHref({ channelId: "channel/1", mode: "inbox" }), "/hub/attention?channel=channel%2F1&mode=inbox");
  assert.equal(attentionDeckHref({ itemId: "item/1", channelId: "channel/1", mode: "review" }), "/hub/attention?item=item%2F1&channel=channel%2F1&mode=review");
  assert.equal(attentionDeckHref({ targetKind: "channel", targetId: "channel/1", mode: "inbox" }), "/hub/attention?mode=inbox&target_kind=channel&target_id=channel%2F1");
  assert.equal(DAILY_HEALTH_HREF, "/hub/daily-health");
  assert.equal(CONTEXT_BLOAT_HREF, "/hub/context-bloat");
  assert.equal(MEMORY_CENTER_HREF, "/admin/learning#Memory");
  assert.equal(widgetPinHref("pin/1"), "/widgets/pins/pin%2F1");
});

test("contextual navigation state round-trips simple back targets", () => {
  const state = contextualNavigationState("/", "Home");
  assert.deepEqual(readContextualNavigationState(state), { backTo: "/", backLabel: "Home" });
  assert.equal(readContextualNavigationState({ backTo: 12 }), null);
  assert.equal(sameNavigationTarget("/canvas/", "/canvas"), true);
});
