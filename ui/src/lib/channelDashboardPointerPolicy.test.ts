import test from "node:test";
import assert from "node:assert/strict";

import {
  floatingHeaderOverlayClass,
  floatingHeaderTileClass,
} from "./channelDashboardPointerPolicy.js";

test("floating header overlay stays click-through so grid widgets under it can drag", () => {
  assert.equal(floatingHeaderOverlayClass(), "pointer-events-none");
});

test("floating header tiles restore pointer events for real header widgets", () => {
  assert.equal(floatingHeaderTileClass(), "pointer-events-auto");
});
