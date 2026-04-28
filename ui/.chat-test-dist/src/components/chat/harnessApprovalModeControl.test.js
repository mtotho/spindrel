import test from "node:test";
import assert from "node:assert/strict";
import { getHarnessApprovalModeControlState, getNextHarnessApprovalMode, normalizeHarnessApprovalMode, } from "./harnessApprovalModeControl.js";
test("approval mode control normalizes unknown modes to bypass", () => {
    assert.equal(normalizeHarnessApprovalMode(null), "bypassPermissions");
    assert.equal(normalizeHarnessApprovalMode("unexpected"), "bypassPermissions");
});
test("approval mode control cycles in the UI order", () => {
    assert.equal(getNextHarnessApprovalMode("bypassPermissions"), "acceptEdits");
    assert.equal(getNextHarnessApprovalMode("acceptEdits"), "default");
    assert.equal(getNextHarnessApprovalMode("default"), "plan");
    assert.equal(getNextHarnessApprovalMode("plan"), "bypassPermissions");
});
test("approval mode control exposes label, title, and tone", () => {
    const state = getHarnessApprovalModeControlState("acceptEdits");
    assert.equal(state.mode, "acceptEdits");
    assert.equal(state.label, "edits");
    assert.equal(state.tone, "warning");
    assert.match(state.title, /Harness permission mode:/);
    assert.match(state.title, /Click to cycle/);
});
