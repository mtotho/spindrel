import assert from "node:assert/strict";
import {
  addChannelSessionPanel,
  buildChannelSessionPickerEntries,
  buildChannelSessionRoute,
  buildScratchChatSource,
  getScratchSessionLabel,
  isUntouchedDraftSession,
  normalizeChannelSessionPanels,
  removeChannelSessionPanel,
} from "./channelSessionSurfaces.js";

assert.deepEqual(normalizeChannelSessionPanels(null), []);
assert.deepEqual(normalizeChannelSessionPanels([
  { kind: "scratch", sessionId: "a" },
  { kind: "thread", sessionId: "b" },
  { kind: "scratch", sessionId: "" },
  { kind: "scratch", sessionId: "c" },
  { kind: "scratch", sessionId: "d" },
]), [
  { kind: "scratch", sessionId: "a" },
  { kind: "scratch", sessionId: "c" },
]);

assert.deepEqual(addChannelSessionPanel([], "a"), [{ kind: "scratch", sessionId: "a" }]);
assert.deepEqual(addChannelSessionPanel([
  { kind: "scratch", sessionId: "a" },
  { kind: "scratch", sessionId: "b" },
], "a"), [
  { kind: "scratch", sessionId: "b" },
  { kind: "scratch", sessionId: "a" },
]);
assert.deepEqual(addChannelSessionPanel([
  { kind: "scratch", sessionId: "a" },
  { kind: "scratch", sessionId: "b" },
], "c"), [
  { kind: "scratch", sessionId: "b" },
  { kind: "scratch", sessionId: "c" },
]);
assert.deepEqual(removeChannelSessionPanel([
  { kind: "scratch", sessionId: "a" },
  { kind: "scratch", sessionId: "b" },
], "a"), [{ kind: "scratch", sessionId: "b" }]);

assert.equal(buildChannelSessionRoute("chan", { kind: "primary" }), "/channels/chan");
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

