import test from "node:test";
import assert from "node:assert/strict";
import { groupAdjacentTranscriptItems } from "./orderedTranscriptGrouping.js";
function entry(id) {
    return {
        id,
        kind: "activity",
        label: id,
        isError: false,
        detailKind: "none",
    };
}
test("groups adjacent transcript items into one row run", () => {
    const items = [
        { kind: "transcript", key: "a", entries: [entry("a1")] },
        { kind: "transcript", key: "b", entries: [entry("b1"), entry("b2")] },
    ];
    const grouped = groupAdjacentTranscriptItems(items);
    assert.equal(grouped.length, 1);
    assert.equal(grouped[0].kind, "transcript");
    assert.deepEqual(grouped[0].kind === "transcript" ? grouped[0].entries.map((x) => x.id) : [], ["a1", "b1", "b2"]);
});
test("does not group transcript items across text or rich items", () => {
    const items = [
        { kind: "transcript", key: "a", entries: [entry("a1")] },
        { kind: "text", key: "text", text: "hello" },
        { kind: "transcript", key: "b", entries: [entry("b1")] },
        {
            kind: "root_rich_result",
            key: "root",
            envelope: {
                content_type: "text/plain",
                body: "ok",
                plain_body: "ok",
                display: "inline",
                truncated: false,
                record_id: "root-result",
                byte_size: 2,
            },
        },
        { kind: "transcript", key: "c", entries: [entry("c1")] },
    ];
    const grouped = groupAdjacentTranscriptItems(items);
    assert.equal(grouped.length, 5);
    assert.deepEqual(grouped.map((item) => item.kind), [
        "transcript",
        "text",
        "transcript",
        "root_rich_result",
        "transcript",
    ]);
});
