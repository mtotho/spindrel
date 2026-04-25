import assert from "node:assert/strict";
import { addChannelChatPane, addChannelSessionPanel, buildChannelSessionChatSource, buildChannelSessionPickerEntries, buildChannelSessionPickerGroups, buildChannelSessionRoute, buildScratchChatSource, getScratchSessionLabel, isUntouchedDraftSession, maximizeChannelChatPane, minimizeChannelChatPane, normalizeChannelChatPaneLayout, normalizeChannelSessionPanels, removeChannelSessionPanel, replaceFocusedChannelChatPane, restoreChannelChatPanes, resizeChannelChatPanes, } from "./channelSessionSurfaces.js";
assert.deepEqual(normalizeChannelSessionPanels(null), []);
assert.deepEqual(normalizeChannelSessionPanels([
    { kind: "scratch", sessionId: "a" },
    { kind: "channel", sessionId: "old" },
    { kind: "thread", sessionId: "b" },
    { kind: "scratch", sessionId: "" },
    { kind: "scratch", sessionId: "c" },
    { kind: "scratch", sessionId: "d" },
]), [
    { kind: "scratch", sessionId: "a" },
    { kind: "channel", sessionId: "old" },
]);
assert.deepEqual(addChannelSessionPanel([], { kind: "scratch", sessionId: "a" }), [{ kind: "scratch", sessionId: "a" }]);
assert.deepEqual(addChannelSessionPanel([
    { kind: "scratch", sessionId: "a" },
    { kind: "scratch", sessionId: "b" },
], { kind: "scratch", sessionId: "a" }), [
    { kind: "scratch", sessionId: "b" },
    { kind: "scratch", sessionId: "a" },
]);
assert.deepEqual(addChannelSessionPanel([
    { kind: "scratch", sessionId: "a" },
    { kind: "scratch", sessionId: "b" },
], { kind: "channel", sessionId: "c" }), [
    { kind: "scratch", sessionId: "b" },
    { kind: "channel", sessionId: "c" },
]);
assert.deepEqual(removeChannelSessionPanel([
    { kind: "channel", sessionId: "a" },
    { kind: "scratch", sessionId: "a" },
    { kind: "scratch", sessionId: "b" },
], { kind: "scratch", sessionId: "a" }), [
    { kind: "channel", sessionId: "a" },
    { kind: "scratch", sessionId: "b" },
]);
assert.equal(buildChannelSessionRoute("chan", { kind: "primary" }), "/channels/chan");
assert.equal(buildChannelSessionRoute("chan", { kind: "channel", sessionId: "old" }), "/channels/chan");
assert.equal(buildChannelSessionRoute("chan", { kind: "scratch", sessionId: "session" }), "/channels/chan/session/session?scratch=true");
assert.deepEqual(buildScratchChatSource({ channelId: "chan", botId: "bot", sessionId: "session" }), {
    kind: "ephemeral",
    sessionStorageKey: "channel:chan:scratch",
    parentChannelId: "chan",
    defaultBotId: "bot",
    context: {
        page_name: "channel_scratch",
        payload: { channel_id: "chan" },
    },
    scratchBoundChannelId: "chan",
    pinnedSessionId: "session",
});
assert.deepEqual(buildChannelSessionChatSource({ channelId: "chan", botId: "bot", sessionId: "session" }), {
    kind: "session",
    sessionId: "session",
    parentChannelId: "chan",
    botId: "bot",
    externalDelivery: "none",
});
assert.equal(getScratchSessionLabel({ title: "  Title  ", summary: "Summary", preview: "Preview" }), "Title");
assert.equal(getScratchSessionLabel({ summary: "  Summary  ", preview: "Preview" }), "Summary");
assert.equal(getScratchSessionLabel({ preview: "  Preview  " }), "Preview");
assert.equal(getScratchSessionLabel({}), "Untitled session");
assert.equal(isUntouchedDraftSession({ message_count: 0, section_count: 0 }), true);
assert.equal(isUntouchedDraftSession({ message_count: 1, section_count: 0 }), false);
assert.equal(isUntouchedDraftSession({ message_count: 0, section_count: 0, title: "named" }), false);
const entries = buildChannelSessionPickerEntries({
    channelLabel: "ops",
    selectedSessionId: "s2",
    query: "second",
    history: [
        { session_id: "s1", message_count: 1, preview: "First" },
        { session_id: "s2", message_count: 2, title: "Second" },
    ],
});
assert.equal(entries.length, 1);
assert.equal(entries[0]?.kind, "scratch");
assert.equal(entries[0]?.selected, true);
assert.deepEqual(entries[0]?.surface, { kind: "scratch", sessionId: "s2" });
const catalogEntries = buildChannelSessionPickerEntries({
    selectedSessionId: null,
    query: "rollback",
    channelSessions: [
        {
            session_id: "active",
            surface_kind: "channel",
            bot_id: "bot",
            created_at: "2026-04-24T00:00:00Z",
            last_active: "2026-04-24T00:00:00Z",
            label: "Current work",
            message_count: 5,
            section_count: 0,
            is_active: true,
            is_current: false,
        },
        {
            session_id: "old",
            surface_kind: "channel",
            bot_id: "bot",
            created_at: "2026-04-23T00:00:00Z",
            last_active: "2026-04-23T00:00:00Z",
            label: "Previous work",
            message_count: 3,
            section_count: 1,
            is_active: false,
            is_current: false,
        },
    ],
    deepMatches: [
        {
            session_id: "old",
            surface_kind: "channel",
            bot_id: "bot",
            created_at: "2026-04-23T00:00:00Z",
            last_active: "2026-04-23T00:00:00Z",
            label: "Previous work",
            message_count: 3,
            section_count: 1,
            is_active: false,
            is_current: false,
            matches: [{ kind: "message", source: "content", preview: "rollback checklist" }],
        },
    ],
});
assert.equal(catalogEntries.length, 1);
assert.equal(catalogEntries[0]?.kind, "channel");
assert.deepEqual(catalogEntries[0]?.surface, { kind: "channel", sessionId: "old" });
assert.equal(catalogEntries[0]?.matches?.[0]?.preview, "rollback checklist");
const migratedLayout = normalizeChannelChatPaneLayout(null, [
    { kind: "scratch", sessionId: "scratch-a" },
    { kind: "channel", sessionId: "old" },
]);
assert.deepEqual(migratedLayout.panes.map((pane) => pane.id), ["primary", "scratch:scratch-a", "channel:old"]);
assert.equal(migratedLayout.focusedPaneId, "primary");
assert.equal(migratedLayout.maximizedPaneId, null);
assert.equal(migratedLayout.miniPane, null);
const splitLayout = addChannelChatPane(migratedLayout, { kind: "scratch", sessionId: "scratch-a" });
assert.deepEqual(splitLayout.panes.map((pane) => pane.id), ["primary", "scratch:scratch-a", "channel:old"]);
assert.equal(splitLayout.focusedPaneId, "scratch:scratch-a");
const replacedLayout = replaceFocusedChannelChatPane(splitLayout, { kind: "channel", sessionId: "later" });
assert.deepEqual(replacedLayout.panes.map((pane) => pane.id), ["primary", "channel:later", "channel:old"]);
assert.equal(replacedLayout.focusedPaneId, "channel:later");
const resizedLayout = resizeChannelChatPanes(replacedLayout, "primary", "channel:later", 0.1);
assert.equal(Math.round(Object.values(resizedLayout.widths).reduce((sum, width) => sum + width, 0) * 1000), 1000);
assert.ok(resizedLayout.widths.primary > replacedLayout.widths.primary);
const maximizedLayout = maximizeChannelChatPane(resizedLayout, "channel:later");
assert.equal(maximizedLayout.maximizedPaneId, "channel:later");
assert.equal(maximizedLayout.focusedPaneId, "channel:later");
assert.deepEqual(maximizedLayout.panes.map((pane) => pane.id), resizedLayout.panes.map((pane) => pane.id));
const restoredLayout = restoreChannelChatPanes(maximizedLayout);
assert.equal(restoredLayout.maximizedPaneId, null);
assert.deepEqual(restoredLayout.panes.map((pane) => pane.id), resizedLayout.panes.map((pane) => pane.id));
const minimizedLayout = minimizeChannelChatPane(restoredLayout, "channel:later");
assert.equal(minimizedLayout.miniPane?.id, "channel:later");
assert.deepEqual(minimizedLayout.panes.map((pane) => pane.id), ["primary", "channel:old"]);
assert.equal(minimizedLayout.maximizedPaneId, null);
const browseGroups = buildChannelSessionPickerGroups(catalogEntries, "");
assert.deepEqual(browseGroups.map((group) => group.id), ["previous"]);
assert.deepEqual(browseGroups.map((group) => group.label), ["Previous chats"]);
assert.deepEqual(browseGroups[0]?.entries.map((entry) => entry.id), ["old"]);
const searchGroups = buildChannelSessionPickerGroups(catalogEntries, "rollback");
assert.deepEqual(searchGroups.map((group) => group.id), ["results"]);
assert.deepEqual(searchGroups[0]?.entries.map((entry) => entry.id), ["old"]);
