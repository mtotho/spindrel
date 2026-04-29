import assert from "node:assert/strict";
import {
  addChannelChatPane,
  addChannelSessionPanel,
  buildChannelSessionChatSource,
  buildChannelSessionPickerEntries,
  buildChannelSessionPickerGroups,
  buildChannelSessionRoute,
  buildChannelSessionTabItems,
  buildScratchChatSource,
  getScratchSessionLabel,
  isUntouchedDraftSession,
  maximizeChannelChatPane,
  minimizeChannelChatPane,
  moveChannelChatPane,
  normalizeChannelChatPaneLayout,
  normalizeChannelSessionPanels,
  normalizeChannelSessionTabLayouts,
  removeChannelSessionPanel,
  replaceFocusedChannelChatPane,
  restoreMiniChannelChatPane,
  restoreChannelChatPanes,
  resizeChannelChatPanes,
  sessionTabKeyForChatPaneLayout,
  snapshotChannelSessionTabLayout,
  splitChannelChatPaneLayout,
} from "./channelSessionSurfaces.js";

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
assert.equal(
  buildChannelSessionRoute("chan", { kind: "channel", sessionId: "old" }),
  "/channels/chan/session/old?surface=channel",
);
assert.equal(
  buildChannelSessionRoute("chan", { kind: "scratch", sessionId: "session" }),
  "/channels/chan/session/session?scratch=true",
);

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

const routePickerEntries = buildChannelSessionPickerEntries({
  channelLabel: "ops",
  selectedSessionId: "scratch-current",
  channelSessions: [
    {
      session_id: "scratch-current",
      surface_kind: "scratch",
      bot_id: "bot",
      created_at: "2026-04-24T00:00:00Z",
      last_active: "2026-04-24T00:00:00Z",
      label: "Current scratch",
      message_count: 2,
      section_count: 0,
      is_active: false,
      is_current: true,
    },
  ],
});
assert.equal(routePickerEntries[0]?.kind, "scratch");
assert.equal(routePickerEntries[0]?.selected, true);
const routePickerGroups = buildChannelSessionPickerGroups(routePickerEntries, "");
assert.deepEqual(routePickerGroups.map((group) => group.id), ["current"]);
assert.deepEqual(routePickerGroups.map((group) => group.label), ["This chat"]);

const activeSessionEntries = buildChannelSessionPickerEntries({
  selectedSessionId: null,
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
  ],
});
assert.equal(activeSessionEntries[0]?.kind, "channel");
assert.deepEqual(activeSessionEntries[0]?.surface, { kind: "channel", sessionId: "active" });
assert.equal(activeSessionEntries[0]?.selected, true);
assert.match(activeSessionEntries[0]?.meta ?? "", /5 msgs/);
assert.doesNotMatch(activeSessionEntries[0]?.meta ?? "", /Primary|Previous/);
const activeSessionGroups = buildChannelSessionPickerGroups(activeSessionEntries, "");
assert.deepEqual(activeSessionGroups.map((group) => group.id), ["current"]);

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

const routeStartedSplitLayout = splitChannelChatPaneLayout(
  { kind: "channel", sessionId: "old" },
  { kind: "primary" },
);
assert.deepEqual(routeStartedSplitLayout.panes.map((pane) => pane.id), ["channel:old", "primary"]);
assert.equal(routeStartedSplitLayout.focusedPaneId, "primary");
assert.equal(Math.round(Object.values(routeStartedSplitLayout.widths).reduce((sum, width) => sum + width, 0) * 1000), 1000);

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

const restoredMiniLayout = restoreMiniChannelChatPane(minimizedLayout);
assert.equal(restoredMiniLayout.miniPane, null);
assert.equal(restoredMiniLayout.focusedPaneId, "channel:later");
assert.deepEqual(restoredMiniLayout.panes.map((pane) => pane.id), ["primary", "channel:old", "channel:later"]);

const movedRightLayout = moveChannelChatPane(restoredMiniLayout, "primary", "right");
assert.deepEqual(movedRightLayout.panes.map((pane) => pane.id), ["channel:old", "primary", "channel:later"]);
assert.equal(movedRightLayout.focusedPaneId, "channel:later");
assert.equal(Math.round(Object.values(movedRightLayout.widths).reduce((sum, width) => sum + width, 0) * 1000), 1000);
const movedLeftLayout = moveChannelChatPane(movedRightLayout, "channel:later", "left");
assert.deepEqual(movedLeftLayout.panes.map((pane) => pane.id), ["channel:old", "channel:later", "primary"]);
assert.deepEqual(moveChannelChatPane(movedLeftLayout, "channel:old", "left").panes.map((pane) => pane.id), ["channel:old", "channel:later", "primary"]);

const browseGroups = buildChannelSessionPickerGroups(catalogEntries, "");
assert.deepEqual(browseGroups.map((group) => group.id), ["recent"]);
assert.deepEqual(browseGroups.map((group) => group.label), ["Recent sessions"]);
assert.deepEqual(browseGroups[0]?.entries.map((entry) => entry.id), ["old"]);

const searchGroups = buildChannelSessionPickerGroups(catalogEntries, "rollback");
assert.deepEqual(searchGroups.map((group) => group.id), ["results"]);
assert.deepEqual(searchGroups[0]?.entries.map((entry) => entry.id), ["old"]);

const sessionTabs = buildChannelSessionTabItems({
  channelId: "chan",
  currentHref: "/channels/chan/session/s2?surface=channel",
  recentPages: [
    { href: "/channels/chan/session/s1?surface=channel", label: "First pass · #ops" },
    { href: "/channels/chan", label: "ops" },
    { href: "/channels/other/session/skip?surface=channel", label: "Skip" },
    { href: "/channels/chan/session/s2?surface=channel", label: "Second pass · #ops" },
  ],
  activeSurface: { kind: "channel", sessionId: "s2" },
  activeSessionId: "s1",
  orderKeys: ["channel:s1", "channel:s2"],
  unreadStates: [
    {
      session_id: "s2",
      unread_agent_reply_count: 3,
    },
  ],
  catalog: [
    {
      session_id: "s1",
      surface_kind: "channel",
      bot_id: "bot",
      created_at: "2026-04-23T00:00:00Z",
      last_active: "2026-04-24T00:00:00Z",
      label: "Primary work",
      message_count: 9,
      section_count: 1,
      is_active: true,
      is_current: false,
    },
    {
      session_id: "s2",
      surface_kind: "channel",
      bot_id: "bot",
      created_at: "2026-04-25T00:00:00Z",
      last_active: "2026-04-25T00:00:00Z",
      label: "Second pass",
      message_count: 2,
      section_count: 0,
      is_active: false,
      is_current: false,
    },
  ],
});
assert.deepEqual(sessionTabs.map((tab) => tab.key), ["channel:s1", "channel:s2", "primary"]);
assert.equal(sessionTabs[0]?.primary, true);
assert.equal(sessionTabs[0]?.label, "Primary work");
assert.match(sessionTabs[0]?.meta ?? "", /Primary/);
assert.equal(sessionTabs[1]?.active, true);
assert.equal(sessionTabs[1]?.unreadCount, 3);

const stableOrderTabs = buildChannelSessionTabItems({
  channelId: "chan",
  currentHref: "/channels/chan/session/s1?surface=channel",
  recentPages: [
    { href: "/channels/chan/session/s1?surface=channel" },
    { href: "/channels/chan/session/s2?surface=channel" },
  ],
  activeSurface: { kind: "channel", sessionId: "s1" },
  orderKeys: ["channel:s2", "channel:s1"],
});
assert.deepEqual(stableOrderTabs.map((tab) => [tab.key, tab.active]), [
  ["channel:s2", false],
  ["channel:s1", true],
]);

const splitTabLayout = splitChannelChatPaneLayout(
  { kind: "primary" },
  { kind: "channel", sessionId: "s2" },
);
const splitTabKey = sessionTabKeyForChatPaneLayout(splitTabLayout);
assert.equal(splitTabKey, "split:primary|channel:s2");
assert.deepEqual(snapshotChannelSessionTabLayout(splitTabLayout)?.layout.panes.map((pane) => pane.id), [
  "primary",
  "channel:s2",
]);
const splitTabs = buildChannelSessionTabItems({
  channelId: "chan",
  currentHref: "/channels/chan/session/s2?surface=channel",
  recentPages: [
    { href: "/channels/chan/session/s1?surface=channel", label: "First pass · #ops" },
    { href: "/channels/chan/session/s2?surface=channel", label: "Second pass · #ops" },
  ],
  activeSurface: { kind: "channel", sessionId: "s2" },
  activeSessionId: "s1",
  activeLayout: splitTabLayout,
  savedLayouts: [],
  orderKeys: ["channel:s1", splitTabKey!, "channel:s2"],
  unreadStates: [{ session_id: "s2", unread_agent_reply_count: 4 }],
  catalog: [
    {
      session_id: "s1",
      surface_kind: "channel",
      bot_id: "bot",
      created_at: "2026-04-23T00:00:00Z",
      last_active: "2026-04-24T00:00:00Z",
      label: "Primary work",
      message_count: 9,
      section_count: 1,
      is_active: true,
      is_current: false,
    },
    {
      session_id: "s2",
      surface_kind: "channel",
      bot_id: "bot",
      created_at: "2026-04-25T00:00:00Z",
      last_active: "2026-04-25T00:00:00Z",
      label: "Second pass",
      message_count: 2,
      section_count: 0,
      is_active: false,
      is_current: false,
    },
  ],
});
assert.deepEqual(splitTabs.map((tab) => [tab.key, tab.kind, tab.active]), [
  ["channel:s1", "surface", false],
  ["split:primary|channel:s2", "split", true],
  ["channel:s2", "surface", false],
]);
const splitTab = splitTabs.find((tab) => tab.kind === "split");
assert.equal(splitTab?.unreadCount, 4);
assert.deepEqual(splitTab?.kind === "split" ? splitTab.panes.map((pane) => [pane.id, pane.label, pane.primary, pane.focused]) : [], [
  ["primary", "Primary work", true, false],
  ["channel:s2", "Second pass", false, true],
]);
const savedSplitLayouts = normalizeChannelSessionTabLayouts([
  { key: "ignored", layout: splitTabLayout },
  { key: "bad", layout: { panes: [{ id: "primary", surface: { kind: "primary" } }], focusedPaneId: "primary", widths: { primary: 1 }, maximizedPaneId: null, miniPane: null } },
]);
assert.deepEqual(savedSplitLayouts.map((layout) => layout.key), ["split:primary|channel:s2"]);
const hiddenSplitTabs = buildChannelSessionTabItems({
  channelId: "chan",
  currentHref: "/channels/chan/session/s2?surface=channel",
  recentPages: [
    { href: "/channels/chan/session/s1?surface=channel" },
    { href: "/channels/chan/session/s2?surface=channel" },
  ],
  activeSurface: { kind: "channel", sessionId: "s2" },
  activeLayout: splitTabLayout,
  savedLayouts: savedSplitLayouts,
  hiddenKeys: ["split:primary|channel:s2"],
});
assert.deepEqual(hiddenSplitTabs.map((tab) => tab.key), ["channel:s2", "channel:s1"]);

const hiddenTabs = buildChannelSessionTabItems({
  channelId: "chan",
  currentHref: "/channels/chan/session/s2?surface=channel",
  recentPages: [
    { href: "/channels/chan/session/s1?surface=channel" },
    { href: "/channels/chan/session/s2?surface=channel" },
  ],
  activeSurface: { kind: "channel", sessionId: "s2" },
  hiddenKeys: ["channel:s2", "channel:s1"],
});
assert.deepEqual(hiddenTabs, []);

const scratchTabs = buildChannelSessionTabItems({
  channelId: "chan",
  currentHref: "/channels/chan/session/scratch?scratch=true",
  activeSurface: { kind: "scratch", sessionId: "scratch" },
  recentPages: [
    { href: "/channels/chan/session/scratch?scratch=true", label: "Scratch idea · #ops" },
  ],
});
assert.deepEqual(scratchTabs.map((tab) => [tab.key, tab.label, tab.active]), [
  ["scratch:scratch", "Scratch idea", true],
]);
