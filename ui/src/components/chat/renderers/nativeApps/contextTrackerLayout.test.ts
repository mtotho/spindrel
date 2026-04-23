import test from "node:test";
import assert from "node:assert/strict";

import { deriveContextTrackerLayoutProfile } from "./contextTrackerLayout.js";

test("header and chip layouts always resolve to compact mode", () => {
  const header = deriveContextTrackerLayoutProfile("header", { width: 640, height: 140 });
  const chip = deriveContextTrackerLayoutProfile("chip", { width: 220, height: 32 });

  assert.equal(header.mode, "compact");
  assert.equal(chip.mode, "compact");
  assert.equal(header.activityLimit, 0);
});

test("very narrow or short tiles resolve to compact mode even outside header", () => {
  const narrow = deriveContextTrackerLayoutProfile("grid", { width: 280, height: 220 });
  const short = deriveContextTrackerLayoutProfile("grid", { width: 420, height: 150 });

  assert.equal(narrow.mode, "compact");
  assert.equal(short.mode, "compact");
  assert.equal(narrow.statColumns, 2);
});

test("tall tiles prioritize stacked detail", () => {
  const tall = deriveContextTrackerLayoutProfile("grid", { width: 360, height: 320 });

  assert.equal(tall.mode, "tall");
  assert.equal(tall.statColumns, 4);
  assert.equal(tall.activityLimit, 4);
  assert.equal(tall.showTurnsInContext, true);
});

test("wide tiles unlock split secondary content", () => {
  const wide = deriveContextTrackerLayoutProfile("grid", { width: 720, height: 220 });

  assert.equal(wide.mode, "wide");
  assert.equal(wide.statColumns, 4);
  assert.equal(wide.splitSecondary, true);
  assert.equal(wide.activityLimit, 3);
});

test("mid-sized grid tiles stay on the standard layout", () => {
  const standard = deriveContextTrackerLayoutProfile("grid", { width: 420, height: 220 });

  assert.equal(standard.mode, "standard");
  assert.equal(standard.statColumns, 3);
  assert.equal(standard.activityLimit, 2);
  assert.equal(standard.showTurnsInContext, false);
});
