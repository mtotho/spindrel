import test from "node:test";
import assert from "node:assert/strict";
import { resolveComposerSubmitIntent } from "./composerSubmit.js";
import type { SlashCommandSpec } from "../../types/api.js";

const catalog: SlashCommandSpec[] = [
  {
    id: "find",
    label: "find",
    description: "Find messages",
    surfaces: ["channel", "session"],
    local_only: false,
    args: [{ name: "query", source: "free_text", required: true, enum: null }],
  },
  {
    id: "stop",
    label: "stop",
    description: "Stop the current session",
    surfaces: ["channel", "session"],
    local_only: false,
    args: [],
  },
  {
    id: "plugins",
    label: "plugins",
    description: "List native plugins",
    surfaces: ["channel", "session"],
    local_only: false,
    args: [{ name: "args", source: "free_text", required: false, enum: null }],
  },
];

test("composer submit resolves valid slash commands before normal sends", () => {
  assert.deepEqual(
    resolveComposerSubmitIntent({
      rawMessage: "/find release notes",
      pendingFiles: [],
      slashSurface: "channel",
      slashCatalog: catalog,
    }),
    { kind: "slash", id: "find", args: ["release", "notes"], argsText: "release notes" },
  );
});

test("composer submit reports missing slash args instead of sending as chat", () => {
  assert.deepEqual(
    resolveComposerSubmitIntent({
      rawMessage: "/find",
      pendingFiles: [],
      slashSurface: "channel",
      slashCatalog: catalog,
    }),
    { kind: "missing_slash_args", id: "find", missing: ["query"] },
  );
});

test("composer submit resolves native harness slash commands with optional args", () => {
  assert.deepEqual(
    resolveComposerSubmitIntent({
      rawMessage: "/plugins list",
      pendingFiles: [],
      slashSurface: "channel",
      slashCatalog: catalog,
    }),
    { kind: "slash", id: "plugins", args: ["list"], argsText: "list" },
  );
});

test("composer submit preserves raw slash arg text for native commands", () => {
  assert.deepEqual(
    resolveComposerSubmitIntent({
      rawMessage: '/plugins install "acme pack" --from ./local',
      pendingFiles: [],
      slashSurface: "channel",
      slashCatalog: catalog,
    }),
    {
      kind: "slash",
      id: "plugins",
      args: ["install", "\"acme", "pack\"", "--from", "./local"],
      argsText: 'install "acme pack" --from ./local',
    },
  );
});

test("composer submit sends unknown slash-looking text as chat", () => {
  assert.deepEqual(
    resolveComposerSubmitIntent({
      rawMessage: "/harness-native-slash-fixture abc123",
      pendingFiles: [],
      slashSurface: "session",
      slashCatalog: catalog,
    }),
    { kind: "send", message: "/harness-native-slash-fixture abc123", files: undefined },
  );
});

test("composer submit sends slash-looking text normally when files are attached", () => {
  const file = { name: "note.txt", base64: "eA==" };

  assert.deepEqual(
    resolveComposerSubmitIntent({
      rawMessage: "/find",
      pendingFiles: [file],
      slashSurface: "channel",
      slashCatalog: catalog,
    }),
    { kind: "send", message: "/find", files: [file] },
  );
});

test("composer submit preserves blocked and idle states", () => {
  assert.deepEqual(
    resolveComposerSubmitIntent({
      rawMessage: "hello",
      pendingFiles: [],
      disabled: true,
      slashSurface: "channel",
      slashCatalog: catalog,
    }),
    { kind: "idle" },
  );

  assert.deepEqual(
    resolveComposerSubmitIntent({
      rawMessage: "hello",
      pendingFiles: [],
      sendDisabledReason: "No model selected",
      slashSurface: "channel",
      slashCatalog: catalog,
    }),
    { kind: "blocked", reason: "No model selected" },
  );
});
