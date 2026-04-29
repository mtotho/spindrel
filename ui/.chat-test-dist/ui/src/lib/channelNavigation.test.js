import test from "node:test";
import assert from "node:assert/strict";
import { resolveChannelEntryHref } from "./channelNavigation.js";
function recent(href) {
    return { href };
}
test("channel entry navigation opens the latest unread session first", () => {
    const href = resolveChannelEntryHref({
        channelId: "chan-1",
        recentPages: [
            recent("/channels/chan-1/session/recent-1?surface=channel"),
        ],
        unreadStates: [
            {
                channel_id: "chan-1",
                session_id: "older-unread",
                unread_agent_reply_count: 1,
                latest_unread_at: "2026-04-20T10:00:00Z",
            },
            {
                channel_id: "chan-1",
                session_id: "newer-unread",
                unread_agent_reply_count: 2,
                latest_unread_at: "2026-04-20T11:00:00Z",
            },
        ],
    });
    assert.equal(href, "/channels/chan-1/session/newer-unread?surface=channel");
});
test("channel entry navigation falls back to the most recent channel session", () => {
    const href = resolveChannelEntryHref({
        channelId: "chan-1",
        recentPages: [
            recent("/channels/other/session/skip-me?surface=channel"),
            recent("/channels/chan-1/session/scratch-1?scratch=true"),
            recent("/channels/chan-1/session/older?surface=channel"),
        ],
        unreadStates: [],
    });
    assert.equal(href, "/channels/chan-1/session/scratch-1?scratch=true");
});
test("channel entry navigation uses the base route without unread or recent sessions", () => {
    const href = resolveChannelEntryHref({
        channelId: "chan-1",
        recentPages: [recent("/channels/chan-1")],
        unreadStates: [],
    });
    assert.equal(href, "/channels/chan-1");
});
