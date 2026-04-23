import test from "node:test";
import assert from "node:assert/strict";

import { deriveNativeWidgetLayoutProfile } from "./nativeWidgetLayout.js";

test("header, chip, and rail layouts collapse to compact mode", () => {
  assert.equal(deriveNativeWidgetLayoutProfile("header", { width: 640, height: 140 }).mode, "compact");
  assert.equal(deriveNativeWidgetLayoutProfile("chip", { width: 220, height: 32 }).mode, "compact");
  assert.equal(deriveNativeWidgetLayoutProfile("rail", { width: 280, height: 320 }).mode, "compact");
});

test("narrow or short grid tiles fall back to compact mode", () => {
  assert.equal(deriveNativeWidgetLayoutProfile("grid", { width: 300, height: 220 }).mode, "compact");
  assert.equal(deriveNativeWidgetLayoutProfile("grid", { width: 420, height: 150 }).mode, "compact");
});

test("wide tiles win before tall tiles", () => {
  const profile = deriveNativeWidgetLayoutProfile("grid", { width: 720, height: 320 });
  assert.equal(profile.mode, "wide");
  assert.equal(profile.wide, true);
});

test("tall tiles become tall when not wide", () => {
  const profile = deriveNativeWidgetLayoutProfile("grid", { width: 420, height: 320 });
  assert.equal(profile.mode, "tall");
  assert.equal(profile.tall, true);
});

test("widgets can override thresholds", () => {
  const profile = deriveNativeWidgetLayoutProfile(
    "grid",
    { width: 360, height: 190 },
    { compactMaxWidth: 280, compactMaxHeight: 140, wideMinWidth: 720, tallMinHeight: 360 },
  );
  assert.equal(profile.mode, "standard");
});
