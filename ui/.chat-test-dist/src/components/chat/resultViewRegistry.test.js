import test from "node:test";
import assert from "node:assert/strict";
import { createResultViewRegistry, contentTypeToViewKey, envelopeViewKey, } from "./resultViewRegistry.js";
import { getChatModeConfig, isTranscriptFlowComposer } from "./chatModes.js";
function envelope(fields) {
    return {
        content_type: "text/plain",
        body: "",
        plain_body: "",
        display: "badge",
        truncated: false,
        record_id: null,
        byte_size: 0,
        ...fields,
    };
}
test("result view registry resolves exact mode and never falls back to default for another mode", () => {
    const registry = createResultViewRegistry();
    registry.register("demo.view", {
        default: ({ label }) => `default:${label}`,
        terminal: ({ label }) => `terminal:${label}`,
    });
    registry.register("default.only", {
        default: ({ label }) => `default:${label}`,
    });
    assert.equal(registry.resolve("demo.view", "terminal")?.({ viewKey: "demo.view", mode: "terminal", label: "x" }), "terminal:x");
    assert.equal(registry.resolve("demo.view", "compact"), null);
    assert.equal(registry.resolve("default.only", "terminal"), null);
});
test("result view keys prefer explicit view_key and otherwise derive from content type", () => {
    assert.equal(envelopeViewKey(envelope({ view_key: "core.search_results", content_type: "application/json" })), "core.search_results");
    assert.equal(contentTypeToViewKey("application/vnd.spindrel.diff+text"), "core.diff");
    assert.equal(contentTypeToViewKey("application/vnd.spindrel.html+interactive"), "core.interactive_html");
});
test("chat mode registry keeps terminal composer in transcript flow and default as overlay", () => {
    assert.equal(getChatModeConfig("default").composerPlacement, "viewport-overlay");
    assert.equal(getChatModeConfig("terminal").composerPlacement, "transcript-flow");
    assert.equal(isTranscriptFlowComposer("terminal"), true);
    assert.equal(isTranscriptFlowComposer("default"), false);
});
