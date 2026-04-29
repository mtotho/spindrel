import test from "node:test";
import assert from "node:assert/strict";
import { terminalTranscriptRole } from "./messageUtils.js";
function message(role, metadata = {}) {
    return { role, metadata };
}
test("terminal transcript role follows persisted message role, not display ownership", () => {
    assert.equal(terminalTranscriptRole(message("user", { source: "e2e-test", sender_type: "human" })), "user");
    assert.equal(terminalTranscriptRole(message("assistant", { sender_display_name: "Kodex" })), "assistant");
});
