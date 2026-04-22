import test from "node:test";
import assert from "node:assert/strict";

import { useChatStore } from "./chat.js";

test("tool results reconcile by tool_call_id when the same tool name appears multiple times", () => {
  useChatStore.setState({ channels: {} });
  const store = useChatStore.getState();

  store.startTurn("channel-1", "turn-1", "bot-1", "Bot", true);
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_start",
    data: {
      tool: "file",
      tool_call_id: "call-1",
      args: "{\"operation\":\"edit\",\"path\":\"a.md\"}",
      surface: "transcript",
    },
  });
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_start",
    data: {
      tool: "file",
      tool_call_id: "call-2",
      args: "{\"operation\":\"edit\",\"path\":\"b.md\"}",
      surface: "transcript",
    },
  });

  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_result",
    data: {
      tool: "file",
      tool_call_id: "call-2",
      surface: "transcript",
      envelope: {
        content_type: "application/vnd.spindrel.diff+text",
        body: "@@ -1 +1 @@\n-old-b\n+new-b",
        plain_body: "Edited b.md",
        display: "inline",
        truncated: false,
        record_id: "result-b",
        byte_size: 24,
      },
    },
  });
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_result",
    data: {
      tool: "file",
      tool_call_id: "call-1",
      surface: "transcript",
      envelope: {
        content_type: "application/vnd.spindrel.diff+text",
        body: "@@ -1 +1 @@\n-old-a\n+new-a",
        plain_body: "Edited a.md",
        display: "inline",
        truncated: false,
        record_id: "result-a",
        byte_size: 24,
      },
    },
  });

  const toolCalls = useChatStore.getState().getChannel("channel-1").turns["turn-1"]?.toolCalls ?? [];
  assert.equal(toolCalls.length, 2);
  assert.equal(toolCalls[0]?.id, "call-1");
  assert.equal(toolCalls[0]?.envelope?.record_id, "result-a");
  assert.equal(toolCalls[1]?.id, "call-2");
  assert.equal(toolCalls[1]?.envelope?.record_id, "result-b");
});
