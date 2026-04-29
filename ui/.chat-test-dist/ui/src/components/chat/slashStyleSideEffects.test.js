import test from "node:test";
import assert from "node:assert/strict";
import { applyChatStyleSideEffect, resolveChatModeFromStyleResult, } from "./slashStyleSideEffects.js";
test("/style side effect resolves chat mode from backend detail text", () => {
    assert.equal(resolveChatModeFromStyleResult({
        command_id: "style",
        result_type: "side_effect",
        payload: {
            effect: "style",
            scope_kind: "channel",
            scope_id: "chan-1",
            title: "Chat style: terminal",
            detail: "Chat style set to terminal.",
        },
        fallback_text: "Chat style set to terminal.",
    }), "terminal");
    assert.equal(resolveChatModeFromStyleResult({
        command_id: "style",
        result_type: "side_effect",
        payload: {
            effect: "style",
            scope_kind: "channel",
            scope_id: "chan-1",
            title: "Chat style: default",
            detail: "Chat style set to default.",
        },
        fallback_text: "Chat style set to default.",
    }), "default");
});
test("/style updates the live channel cache key used by channel pages", () => {
    let cached = { id: "chan-1", config: { chat_mode: "default", other: true } };
    const invalidations = [];
    const qc = {
        setQueryData(key, updater) {
            assert.deepEqual(key, ["channels", "chan-1"]);
            cached = updater(cached);
        },
        invalidateQueries(arg) {
            invalidations.push(arg.queryKey);
        },
    };
    applyChatStyleSideEffect(qc, "chan-1", {
        command_id: "style",
        result_type: "side_effect",
        payload: {
            effect: "style",
            scope_kind: "channel",
            scope_id: "chan-1",
            title: "Chat style: terminal",
            detail: "Chat style set to terminal.",
        },
        fallback_text: "Chat style set to terminal.",
    });
    assert.equal(cached.config.chat_mode, "terminal");
    assert.equal(cached.config.other, true);
    assert.deepEqual(invalidations, [["channels", "chan-1"], ["channels"]]);
});
