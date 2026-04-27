import test from "node:test";
import assert from "node:assert/strict";
import { activeAttentionStatus, canMoveSpatialNode } from "./spatialInteraction.ts";

test("spatial node move is gated by arrange mode or shift", () => {
  assert.equal(canMoveSpatialNode("browse", false), false);
  assert.equal(canMoveSpatialNode("browse", true), true);
  assert.equal(canMoveSpatialNode("arrange", false), true);
});

test("active attention excludes acknowledged and resolved statuses", () => {
  assert.equal(activeAttentionStatus("open"), true);
  assert.equal(activeAttentionStatus("responded"), true);
  assert.equal(activeAttentionStatus("acknowledged"), false);
  assert.equal(activeAttentionStatus("resolved"), false);
});
