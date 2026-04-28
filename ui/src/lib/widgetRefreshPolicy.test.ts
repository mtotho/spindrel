import test from "node:test";
import assert from "node:assert/strict";

import {
  isWidgetRefreshCapable,
  shouldRunWidgetAutoRefresh,
  widgetRefreshJitterMs,
} from "./widgetRefreshPolicy.js";

test("refresh capability follows state_poll contract when old envelopes omit refreshable", () => {
  assert.equal(isWidgetRefreshCapable({ refreshable: false }, { refresh_model: "state_poll" }), true);
  assert.equal(isWidgetRefreshCapable({ refreshable: true }, { refresh_model: "none" }), true);
  assert.equal(isWidgetRefreshCapable({ refreshable: false }, { refresh_model: "none" }), false);
});

test("auto refresh is gated by collapsed and visibility state", () => {
  assert.equal(shouldRunWidgetAutoRefresh({ refreshCapable: true }), true);
  assert.equal(shouldRunWidgetAutoRefresh({ refreshCapable: false }), false);
  assert.equal(shouldRunWidgetAutoRefresh({ refreshCapable: true, collapsed: true }), false);
  assert.equal(shouldRunWidgetAutoRefresh({ refreshCapable: true, documentVisible: false }), false);
  assert.equal(shouldRunWidgetAutoRefresh({ refreshCapable: true, elementVisible: false }), false);
  assert.equal(shouldRunWidgetAutoRefresh({ refreshCapable: true, skipHtmlAutoRefresh: true }), false);
});

test("refresh jitter is deterministic and bounded", () => {
  const first = widgetRefreshJitterMs("pin-a", 1000);
  assert.equal(first, widgetRefreshJitterMs("pin-a", 1000));
  assert.ok(first >= 0);
  assert.ok(first < 1000);
});
