import test from "node:test";
import assert from "node:assert/strict";
import { mergeUnreadStateUpdates, recomputeUnreadChannels } from "./unreadStateCache.js";
function state(sessionId, channelId, count, latest) {
    return {
        user_id: "user",
        session_id: sessionId,
        channel_id: channelId,
        last_read_message_id: null,
        last_read_at: null,
        first_unread_at: latest,
        latest_unread_at: latest,
        latest_unread_message_id: null,
        latest_unread_correlation_id: null,
        unread_agent_reply_count: count,
        reminder_due_at: null,
        reminder_sent_at: null,
    };
}
test("recomputeUnreadChannels rolls multiple sessions into one channel count", () => {
    assert.deepEqual(recomputeUnreadChannels([
        state("s1", "channel-a", 2, "2026-04-28T10:00:00Z"),
        state("s2", "channel-a", 3, "2026-04-28T11:00:00Z"),
        state("s3", "channel-b", 1, "2026-04-28T09:00:00Z"),
    ]), [
        { channel_id: "channel-a", unread_agent_reply_count: 5, latest_unread_at: "2026-04-28T11:00:00Z" },
        { channel_id: "channel-b", unread_agent_reply_count: 1, latest_unread_at: "2026-04-28T09:00:00Z" },
    ]);
});
test("mergeUnreadStateUpdates upserts sessions and refreshes channel rollups without refetch", () => {
    const merged = mergeUnreadStateUpdates({
        states: [
            state("s1", "channel-a", 2, "2026-04-28T10:00:00Z"),
            state("s2", "channel-a", 3, "2026-04-28T11:00:00Z"),
        ],
        channels: [
            { channel_id: "channel-a", unread_agent_reply_count: 5, latest_unread_at: "2026-04-28T11:00:00Z" },
        ],
    }, [
        state("s1", "channel-a", 0, null),
    ]);
    assert.equal(merged?.states.find((row) => row.session_id === "s1")?.unread_agent_reply_count, 0);
    assert.deepEqual(merged?.channels, [
        { channel_id: "channel-a", unread_agent_reply_count: 3, latest_unread_at: "2026-04-28T11:00:00Z" },
    ]);
});
