import test from "node:test";
import assert from "node:assert/strict";

import {
  isWidgetRefreshCapable,
  shouldSchedulePinnedInitialRefresh,
  shouldMountPinnedInteractiveIframe,
  shouldShowPinnedWidgetIframeSkeleton,
  shouldShowPinnedWidgetRefreshOverlay,
  shouldRenderPinnedWidgetLoadShell,
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

test("refreshable pinned widgets keep chrome available while first poll runs", () => {
  assert.equal(
    shouldRenderPinnedWidgetLoadShell({
      hasRenderableBody: true,
      awaitingFirstPollForRefreshable: true,
    }),
    false,
  );
  assert.equal(
    shouldRenderPinnedWidgetLoadShell({
      hasRenderableBody: false,
      awaitingFirstPollForRefreshable: true,
    }),
    true,
  );
});

test("refreshable pinned widgets do not cover already-rendered content with a refresh skeleton", () => {
  assert.equal(
    shouldShowPinnedWidgetRefreshOverlay({
      hasRenderableBody: true,
      awaitingFirstPollForRefreshable: true,
    }),
    false,
  );
});

test("cancelled delayed initial refreshes remain eligible to reschedule", () => {
  assert.equal(
    shouldSchedulePinnedInitialRefresh({
      widgetId: "pin-a",
      refreshedForWidgetId: null,
      shouldRefreshOnMount: true,
    }),
    true,
  );
  assert.equal(
    shouldSchedulePinnedInitialRefresh({
      widgetId: "pin-a",
      refreshedForWidgetId: null,
      shouldRefreshOnMount: true,
    }),
    true,
  );
  assert.equal(
    shouldSchedulePinnedInitialRefresh({
      widgetId: "pin-a",
      refreshedForWidgetId: "pin-a",
      shouldRefreshOnMount: true,
    }),
    false,
  );
});

test("interactive iframe preload skeleton has a watchdog cutoff", () => {
  assert.equal(
    shouldShowPinnedWidgetIframeSkeleton({
      isHtmlInteractive: true,
      iframeReady: false,
      preloadElapsedMs: 500,
      preloadWatchdogMs: 2500,
    }),
    true,
  );
  assert.equal(
    shouldShowPinnedWidgetIframeSkeleton({
      isHtmlInteractive: true,
      iframeReady: false,
      preloadElapsedMs: 2500,
      preloadWatchdogMs: 2500,
    }),
    false,
  );
});

test("interactive HTML iframes wait until the tile has been visible", () => {
  assert.equal(
    shouldMountPinnedInteractiveIframe({
      isHtmlInteractive: false,
      hasEverBeenVisible: false,
    }),
    true,
  );
  assert.equal(
    shouldMountPinnedInteractiveIframe({
      isHtmlInteractive: true,
      hasEverBeenVisible: false,
    }),
    false,
  );
  assert.equal(
    shouldMountPinnedInteractiveIframe({
      isHtmlInteractive: true,
      hasEverBeenVisible: true,
    }),
    true,
  );
});

test("refresh jitter is deterministic and bounded", () => {
  const first = widgetRefreshJitterMs("pin-a", 1000);
  assert.equal(first, widgetRefreshJitterMs("pin-a", 1000));
  assert.ok(first >= 0);
  assert.ok(first < 1000);
});
