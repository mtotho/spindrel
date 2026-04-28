import test from "node:test";
import assert from "node:assert/strict";
import { unreadStateHref } from "./unreadNavigation.js";

test("unread rows link to the specific channel session instead of channel primary", () => {
  assert.equal(
    unreadStateHref({ channel_id: "chan-1", session_id: "session-1" }),
    "/channels/chan-1/session/session-1?surface=channel",
  );
});

test("unread rows without a channel stay non-navigable", () => {
  assert.equal(unreadStateHref({ channel_id: null, session_id: "session-1" }), undefined);
});
