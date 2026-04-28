import test from "node:test";
import assert from "node:assert/strict";
import { localUserMessageScrollKey, preserveReverseScrollPositionOnBottomGrowth, } from "./reverseScrollPinning.js";
test("keeps column-reverse chat pinned when already at visual bottom", () => {
    assert.equal(preserveReverseScrollPositionOnBottomGrowth({
        scrollTop: 0,
        previousBottomHeight: 100,
        nextBottomHeight: 160,
    }), 0);
});
test("preserves user position when bottom streaming content grows", () => {
    assert.equal(preserveReverseScrollPositionOnBottomGrowth({
        scrollTop: -240,
        previousBottomHeight: 100,
        nextBottomHeight: 160,
    }), -300);
});
test("does not compensate for shrinking or unchanged bottom content", () => {
    assert.equal(preserveReverseScrollPositionOnBottomGrowth({
        scrollTop: -240,
        previousBottomHeight: 160,
        nextBottomHeight: 120,
    }), -240);
});
test("identifies local user messages that should jump to newest", () => {
    assert.equal(localUserMessageScrollKey({
        id: "optimistic",
        role: "user",
        metadata: { client_local_id: "local-1", local_status: "sending" },
    }), "local-1");
    assert.equal(localUserMessageScrollKey({
        id: "queued",
        role: "user",
        metadata: { local_status: "queued" },
    }), "queued");
});
test("does not treat assistant or remote user messages as local sends", () => {
    assert.equal(localUserMessageScrollKey({
        id: "assistant",
        role: "assistant",
        metadata: { client_local_id: "local-1" },
    }), null);
    assert.equal(localUserMessageScrollKey({
        id: "slack-user",
        role: "user",
        metadata: { source: "slack", sender_type: "human" },
    }), null);
});
