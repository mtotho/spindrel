import test from "node:test";
import assert from "node:assert/strict";
import { buildChatCancelRequest } from "./chatCancelRequest.js";
test("cancel request targets the visible channel session", () => {
    assert.deepEqual(buildChatCancelRequest({
        clientId: "client-1",
        botId: "bot-1",
        channelId: "channel-1",
        sessionId: "session-1",
    }), {
        client_id: "client-1",
        bot_id: "bot-1",
        channel_id: "channel-1",
        session_id: "session-1",
    });
});
test("cancel request keeps legacy client fallback without blank optional ids", () => {
    assert.deepEqual(buildChatCancelRequest({
        botId: "bot-1",
        clientId: null,
        channelId: null,
        sessionId: null,
    }), {
        client_id: "",
        bot_id: "bot-1",
    });
});
