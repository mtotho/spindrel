import test from "node:test";
import assert from "node:assert/strict";
import { mergePersistedAndSyntheticMessages, shouldKeepSyntheticAssistantMessage, } from "./sessionMessageSync.js";
function makeSyntheticWidgetMessage() {
    return {
        id: "turn-1",
        session_id: "session-1",
        role: "assistant",
        content: "Succeeded on retry.",
        correlation_id: "corr-1",
        created_at: "2026-04-22T22:15:00.000Z",
        tool_calls: [
            {
                id: "call-search",
                name: "web_search",
                arguments: '{"q":"weather in Lambertville NJ today"}',
                surface: "widget",
                summary: {
                    kind: "result",
                    subject_type: "widget",
                    label: "Widget available",
                    target_label: "Web search",
                },
            },
        ],
        metadata: {
            assistant_turn_body: {
                version: 1,
                items: [{ id: "tool-search", kind: "tool_call", toolCallId: "call-search" }],
            },
            tool_results: [
                {
                    content_type: "application/vnd.spindrel.html+interactive",
                    body: "<html><body>widget</body></html>",
                    plain_body: "Web search",
                    display: "inline",
                    truncated: false,
                    record_id: "widget-1",
                    byte_size: 32,
                },
            ],
        },
    };
}
test("synthetic widget rows survive when the fetched DB row is structurally weaker", () => {
    const synthetic = makeSyntheticWidgetMessage();
    const dbRow = {
        ...synthetic,
        id: "db-1",
        tool_calls: [
            {
                id: "call-search",
                name: "web_search",
                arguments: '{"q":"weather in Lambertville NJ today"}',
                surface: "widget",
                summary: {
                    kind: "result",
                    subject_type: "widget",
                    label: "Widget available",
                    target_label: "Web search",
                },
            },
        ],
        metadata: {
            assistant_turn_body: synthetic.metadata?.assistant_turn_body,
        },
    };
    assert.equal(shouldKeepSyntheticAssistantMessage(synthetic, [dbRow]), true);
    assert.deepEqual(mergePersistedAndSyntheticMessages([dbRow], [synthetic]).map((message) => message.id), ["db-1", "turn-1"]);
});
test("synthetic widget rows are dropped once the fetched DB row is equally rich", () => {
    const synthetic = makeSyntheticWidgetMessage();
    const dbRow = {
        ...synthetic,
        id: "db-1",
    };
    assert.equal(shouldKeepSyntheticAssistantMessage(synthetic, [dbRow]), false);
    assert.deepEqual(mergePersistedAndSyntheticMessages([dbRow], [synthetic]).map((message) => message.id), ["db-1"]);
});
