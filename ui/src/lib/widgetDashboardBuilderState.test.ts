import test from "node:test";
import assert from "node:assert/strict";

import { applyBuilderPinSuccessParams } from "./widgetDashboardBuilderState.ts";

test("applyBuilderPinSuccessParams closes the builder and enables edit mode", () => {
  const params = new URLSearchParams({
    builder: "1",
    builder_tab: "presets",
    builder_q: "light",
    builder_preset: "homeassistant-light-card",
    builder_step: "preview",
  });

  const next = applyBuilderPinSuccessParams(params);

  assert.equal(next.get("edit"), "true");
  assert.equal(next.get("builder"), null);
  assert.equal(next.get("builder_tab"), null);
  assert.equal(next.get("builder_q"), null);
  assert.equal(next.get("builder_preset"), null);
  assert.equal(next.get("builder_step"), null);
});

test("applyBuilderPinSuccessParams preserves unrelated dashboard params", () => {
  const params = new URLSearchParams({
    slug: "channel:abc",
    dock: "expanded",
    kiosk: "1",
  });

  const next = applyBuilderPinSuccessParams(params);

  assert.equal(next.get("slug"), "channel:abc");
  assert.equal(next.get("dock"), "expanded");
  assert.equal(next.get("kiosk"), "1");
  assert.equal(next.get("edit"), "true");
});
