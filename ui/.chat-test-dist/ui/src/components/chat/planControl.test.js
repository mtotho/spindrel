import test from "node:test";
import assert from "node:assert/strict";
import { getComposerPlanControlState } from "./planControl.js";
test("inactive plan control is action-labeled when no plan exists", () => {
    assert.deepEqual(getComposerPlanControlState({ planMode: "chat", hasPlan: false }), {
        label: "Start plan",
        title: "Start plan mode",
        tone: "neutral",
        active: false,
        showMenu: false,
        primaryActionLabel: "Start plan",
        canApprove: false,
    });
});
test("inactive plan control resumes an existing plan without a menu affordance", () => {
    const state = getComposerPlanControlState({ planMode: null, hasPlan: true });
    assert.equal(state.label, "Resume plan");
    assert.equal(state.primaryActionLabel, "Resume plan");
    assert.equal(state.active, false);
    assert.equal(state.showMenu, false);
});
test("planning state is status-labeled and keeps approve available when supplied", () => {
    const state = getComposerPlanControlState({
        planMode: "planning",
        hasPlan: true,
        canApprovePlan: true,
    });
    assert.equal(state.label, "Planning");
    assert.equal(state.title, "Plan mode: Planning");
    assert.equal(state.tone, "warning");
    assert.equal(state.active, true);
    assert.equal(state.showMenu, true);
    assert.equal(state.primaryActionLabel, "Exit plan");
    assert.equal(state.canApprove, true);
});
test("execution states map to distinct status tones", () => {
    assert.equal(getComposerPlanControlState({ planMode: "executing", hasPlan: true }).tone, "warning");
    assert.equal(getComposerPlanControlState({ planMode: "blocked", hasPlan: true }).tone, "danger");
    assert.equal(getComposerPlanControlState({ planMode: "done", hasPlan: true }).tone, "success");
});
