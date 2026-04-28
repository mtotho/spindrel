import test from "node:test";
import assert from "node:assert/strict";
import { shouldShowComposerPlanControl } from "./planControlVisibility.js";

test("auto hides dormant plan control for non-harness channels", () => {
  assert.equal(
    shouldShowComposerPlanControl({
      canTogglePlanMode: true,
      planMode: "chat",
      planModeControl: "auto",
      harnessRuntime: null,
    }),
    false,
  );
});

test("auto shows dormant plan control for harness channels", () => {
  assert.equal(
    shouldShowComposerPlanControl({
      canTogglePlanMode: true,
      planMode: "chat",
      planModeControl: "auto",
      harnessRuntime: "codex",
    }),
    true,
  );
});

test("active plan state stays visible even when dormant control is hidden", () => {
  assert.equal(
    shouldShowComposerPlanControl({
      canTogglePlanMode: true,
      planMode: "planning",
      planModeControl: "hide",
      harnessRuntime: null,
    }),
    true,
  );
});

test("explicit show keeps the dormant plan control visible", () => {
  assert.equal(
    shouldShowComposerPlanControl({
      canTogglePlanMode: true,
      planMode: "chat",
      planModeControl: "show",
      harnessRuntime: null,
    }),
    true,
  );
});
