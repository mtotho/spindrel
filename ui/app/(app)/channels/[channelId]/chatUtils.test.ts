import test from "node:test";
import assert from "node:assert/strict";

import { getTurnMessages, getTurnText, stringifyTurnMessages } from "./chatUtils.js";
import type { Message } from "@/src/types/api.js";

function makeMessage(overrides: Partial<Message>): Message {
  return {
    id: overrides.id ?? "message-id",
    session_id: overrides.session_id ?? "session-1",
    role: overrides.role ?? "assistant",
    content: overrides.content ?? "",
    tool_calls: overrides.tool_calls ?? undefined,
    correlation_id: overrides.correlation_id ?? "corr-1",
    created_at: overrides.created_at ?? "2026-04-22T22:00:00Z",
    metadata: overrides.metadata ?? { sender_id: "bot:test-bot" },
    attachments: overrides.attachments ?? [],
  };
}

test("getTurnMessages returns grouped assistant rows in chronological order", () => {
  const invertedData: Message[] = [
    makeMessage({
      id: "assistant-newer",
      content: "Second chunk",
      created_at: "2026-04-22T22:00:10Z",
    }),
    makeMessage({
      id: "assistant-header",
      content: "First chunk",
      created_at: "2026-04-22T22:00:00Z",
    }),
    makeMessage({
      id: "user-1",
      role: "user",
      content: "prompt",
      created_at: "2026-04-22T21:59:00Z",
      metadata: {},
    }),
  ];

  const messages = getTurnMessages(invertedData, 1);

  assert.deepEqual(messages?.map((message) => message.id), [
    "assistant-header",
    "assistant-newer",
  ]);
  assert.equal(getTurnText(invertedData, 1), "First chunk\n\nSecond chunk");
  assert.equal(
    stringifyTurnMessages(messages),
    JSON.stringify(messages, null, 2),
  );
});

test("single-row assistant responses still produce a json bundle", () => {
  const invertedData: Message[] = [
    makeMessage({
      id: "assistant-only",
      content: "Only chunk",
      created_at: "2026-04-22T22:00:00Z",
    }),
    makeMessage({
      id: "user-1",
      role: "user",
      content: "prompt",
      created_at: "2026-04-22T21:59:00Z",
      metadata: {},
    }),
  ];

  const messages = getTurnMessages(invertedData, 0);

  assert.deepEqual(messages?.map((message) => message.id), ["assistant-only"]);
  assert.equal(getTurnText(invertedData, 0), undefined);
  assert.equal(
    stringifyTurnMessages(messages),
    JSON.stringify(messages, null, 2),
  );
});
