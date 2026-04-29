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
      args_text: "",
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
      args_text: "",
    },
  );
});

test("args and raw arg text are forwarded when provided (e.g. /plugins install)", () => {
  assert.deepEqual(
    buildSlashCommandExecuteBody({
      commandId: "plugins",
      surface: "channel",
      channelId: "channel-1",
      args: ["install", "fixture plugin"],
      argsText: 'install "fixture plugin"',
    }),
    {
      command_id: "plugins",
      channel_id: "channel-1",
      session_id: null,
      current_session_id: null,
      surface: "web",
      args: ["install", "fixture plugin"],
      args_text: 'install "fixture plugin"',
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
