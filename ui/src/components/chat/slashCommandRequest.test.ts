import test from "node:test";
import assert from "node:assert/strict";

import { buildSlashCommandExecuteBody } from "./slashCommandRequest.js";

test("channel surface carries the current session id when present", () => {
  assert.deepEqual(
    buildSlashCommandExecuteBody({
      commandId: "compact",
      surface: "channel",
      channelId: "channel-1",
      sessionId: "session-1",
    }),
    {
      command_id: "compact",
      channel_id: "channel-1",
      session_id: null,
      current_session_id: "session-1",
      surface: "web",
      args: [],
    },
  );
});

test("session surface prefers session scope even when a channel id is present", () => {
  assert.deepEqual(
    buildSlashCommandExecuteBody({
      commandId: "context",
      surface: "session",
      channelId: "channel-1",
      sessionId: "session-1",
    }),
    {
      command_id: "context",
      channel_id: null,
      session_id: "session-1",
      current_session_id: null,
      surface: "web",
      args: [],
    },
  );
});

test("args are forwarded when provided (e.g. /effort high)", () => {
  assert.deepEqual(
    buildSlashCommandExecuteBody({
      commandId: "effort",
      surface: "channel",
      channelId: "channel-1",
      args: ["high"],
    }),
    {
      command_id: "effort",
      channel_id: "channel-1",
      session_id: null,
      current_session_id: null,
      surface: "web",
      args: ["high"],
    },
  );
});

test("returns null when the requested surface has no matching scope id", () => {
  assert.equal(
    buildSlashCommandExecuteBody({
      commandId: "compact",
      surface: "channel",
      sessionId: "session-1",
    }),
    null,
  );
  assert.equal(
    buildSlashCommandExecuteBody({
      commandId: "context",
      surface: "session",
      channelId: "channel-1",
    }),
    null,
  );
});
