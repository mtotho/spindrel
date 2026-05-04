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
      surface: "rich_result",
    },
  });
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_start",
    data: {
      tool: "file",
      tool_call_id: "call-2",
      args: "{\"operation\":\"edit\",\"path\":\"b.md\"}",
      surface: "rich_result",
    },
  });

  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_result",
    data: {
      tool: "file",
      tool_call_id: "call-2",
      surface: "rich_result",
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
      surface: "rich_result",
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

test("processing ack arriving after turn start does not leave a stale background indicator", () => {
  useChatStore.setState({ channels: {} });
  const store = useChatStore.getState();

  store.startTurn("channel-1", "turn-1", "bot-1", "Rolland", true);
  store.setProcessing("channel-1", "task-late-ack");

  const ch = useChatStore.getState().getChannel("channel-1");
  assert.equal(Object.keys(ch.turns).length, 1);
  assert.equal(ch.isProcessing, false);
  assert.equal(ch.queuedTaskId, null);
});

test("discardTurn removes stale tool streams without materializing a message", () => {
  useChatStore.setState({ channels: {} });
  const store = useChatStore.getState();

  store.startTurn("session-1", "turn-1", "dev_bot", "Dev Bot", false);
  store.handleTurnEvent("session-1", "turn-1", {
    event: "tool_start",
    data: {
      tool: "memory",
      tool_call_id: "call-memory-1",
      args: "{\"operation\":\"append\",\"path\":\"memory/reference/qa-memory-codes.md\"}",
      surface: "rich_result",
    },
  });
  store.handleTurnEvent("session-1", "turn-1", {
    event: "tool_result",
    data: {
      tool: "memory",
      tool_call_id: "call-memory-1",
      surface: "rich_result",
      envelope: {
        content_type: "text/markdown",
        body: "Created memory/reference/qa-memory-codes.md",
        plain_body: "Created memory/reference/qa-memory-codes.md",
        display: "inline",
        truncated: false,
        byte_size: 42,
      },
    },
  });

  store.discardTurn("session-1", "turn-1");

  const ch = useChatStore.getState().getChannel("session-1");
  assert.equal(Object.keys(ch.turns).length, 0);
  assert.equal(ch.messages.length, 0);
});

test("finishTurn materializes the canonical assistant turn body", () => {
  useChatStore.setState({ channels: {} });
  const store = useChatStore.getState();

  store.startTurn("channel-1", "turn-1", "bot-1", "Bot", true);
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_start",
    data: {
      tool: "file",
      tool_call_id: "call-edit-1",
      args: "{\"operation\":\"edit\",\"path\":\"a.md\"}",
      surface: "rich_result",
      summary: {
        kind: "diff",
        subject_type: "file",
        label: "Edited a.md",
        path: "a.md",
        diff_stats: { additions: 1, deletions: 1 },
      },
    },
  });
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_result",
    data: {
      tool: "file",
      tool_call_id: "call-edit-1",
      surface: "rich_result",
      summary: {
        kind: "diff",
        subject_type: "file",
        label: "Edited a.md",
        path: "a.md",
        diff_stats: { additions: 1, deletions: 1 },
      },
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
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "text_delta",
    data: { delta: "Checking the current time.\n" },
  });
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_start",
    data: {
      tool: "get_current_local_time",
      tool_call_id: "call-time",
      args: "{}",
      surface: "transcript",
      summary: {
        kind: "result",
        subject_type: "generic",
        label: "Got current local time",
        preview_text: "2026-04-22 14:05 EDT",
      },
    },
  });
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_result",
    data: {
      tool: "get_current_local_time",
      tool_call_id: "call-time",
      surface: "transcript",
      summary: {
        kind: "result",
        subject_type: "generic",
        label: "Got current local time",
        preview_text: "2026-04-22 14:05 EDT",
      },
      envelope: {
        content_type: "text/plain",
        body: "2026-04-22 14:05 EDT",
        plain_body: "2026-04-22 14:05 EDT",
        display: "badge",
        truncated: false,
        record_id: "result-time",
        byte_size: 20,
      },
    },
  });
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_start",
    data: {
      tool: "file",
      tool_call_id: "call-edit-2",
      args: "{\"operation\":\"edit\",\"path\":\"b.md\"}",
      surface: "rich_result",
      summary: {
        kind: "diff",
        subject_type: "file",
        label: "Edited b.md",
        path: "b.md",
        diff_stats: { additions: 1, deletions: 0 },
      },
    },
  });
  store.handleTurnEvent("channel-1", "turn-1", {
    event: "tool_result",
    data: {
      tool: "file",
      tool_call_id: "call-edit-2",
      surface: "rich_result",
      summary: {
        kind: "diff",
        subject_type: "file",
        label: "Edited b.md",
        path: "b.md",
        diff_stats: { additions: 1, deletions: 0 },
      },
      envelope: {
        content_type: "application/vnd.spindrel.diff+text",
        body: "@@ -1 +1 @@\n old\n+new-b",
        plain_body: "Edited b.md",
        display: "inline",
        truncated: false,
        record_id: "result-b",
        byte_size: 21,
      },
    },
  });

  store.finishTurn("channel-1", "turn-1");

  const messages = useChatStore.getState().getChannel("channel-1").messages;
  assert.equal(messages.length, 1);
  const metadata = messages[0]?.metadata ?? {};
  assert.deepEqual(metadata.assistant_turn_body, {
    version: 1,
    items: [
      { id: "tool:call-edit-1", kind: "tool_call", toolCallId: "call-edit-1" },
      { id: "text:2", kind: "text", text: "Checking the current time.\n" },
      { id: "tool:call-time", kind: "tool_call", toolCallId: "call-time" },
      { id: "tool:call-edit-2", kind: "tool_call", toolCallId: "call-edit-2" },
    ],
  });
  assert.equal(metadata.tool_results?.[0]?.record_id, "result-a");
  assert.equal(metadata.tool_results?.[1]?.record_id, "result-time");
  assert.equal(metadata.tool_results?.[2]?.record_id, "result-b");
});

test("upsertMessage replaces an existing persisted row in place", () => {
  useChatStore.setState({ channels: {} });
  const store = useChatStore.getState();

  store.addMessage("channel-1", {
    id: "msg-1",
    session_id: "session-1",
    role: "assistant",
    content: "",
    created_at: "2026-04-23T12:00:00Z",
    metadata: {
      kind: "compaction_run",
      compaction_status: "running",
    },
  });

  store.upsertMessage("channel-1", {
    id: "msg-1",
    session_id: "session-1",
    role: "assistant",
    content: "",
    created_at: "2026-04-23T12:00:00Z",
    metadata: {
      kind: "compaction_run",
      compaction_status: "completed",
      compaction_summary_text: "Updated summary",
    },
  });

  const messages = useChatStore.getState().getChannel("channel-1").messages;
  assert.equal(messages.length, 1);
  assert.equal(messages[0]?.metadata?.compaction_status, "completed");
  assert.equal(messages[0]?.metadata?.compaction_summary_text, "Updated summary");
});

test("finishTurn materializes an error-only turn", () => {
  useChatStore.setState({ channels: {} });
  const store = useChatStore.getState();

  store.startTurn("channel-1", "turn-err", "bot-1", "Bot", true);
  store.handleTurnEvent("channel-1", "turn-err", {
    event: "error",
    data: { message: "InternalServerError: context window exceeded" },
  });

  store.finishTurn("channel-1", "turn-err");

  const messages = useChatStore.getState().getChannel("channel-1").messages;
  assert.equal(messages.length, 1);
  assert.equal(messages[0]?.content, "Turn failed: InternalServerError: context window exceeded");
  assert.equal(messages[0]?.metadata?.turn_error, true);
  assert.equal(
    messages[0]?.metadata?.turn_error_message,
    "InternalServerError: context window exceeded",
  );
});

test("finishTurn keeps partial streamed text while tagging terminal errors", () => {
  useChatStore.setState({ channels: {} });
  const store = useChatStore.getState();

  store.startTurn("channel-1", "turn-partial", "bot-1", "Bot", true);
  store.handleTurnEvent("channel-1", "turn-partial", {
    event: "text_delta",
    data: { delta: "partial answer" },
  });
  store.handleTurnEvent("channel-1", "turn-partial", {
    event: "error",
    data: { message: "InternalServerError: context window exceeded" },
  });

  store.finishTurn("channel-1", "turn-partial");

  const messages = useChatStore.getState().getChannel("channel-1").messages;
  assert.equal(messages.length, 1);
  assert.equal(messages[0]?.content, "partial answer");
  assert.equal(messages[0]?.metadata?.turn_error, true);
  assert.equal(
    messages[0]?.metadata?.turn_error_message,
    "InternalServerError: context window exceeded",
  );
});

test("finishTurn removes typing-only cancelled turns", () => {
  useChatStore.setState({ channels: {} });
  const store = useChatStore.getState();

  store.startTurn("channel-1", "turn-cancel-empty", "bot-1", "Bot", true);
  store.handleTurnEvent("channel-1", "turn-cancel-empty", {
    event: "error",
    data: { message: "cancelled" },
  });
  store.finishTurn("channel-1", "turn-cancel-empty");

  const ch = useChatStore.getState().getChannel("channel-1");
  assert.equal(ch.messages.length, 0);
  assert.equal(Object.keys(ch.turns).length, 0);
});

test("finishTurn keeps partial cancelled responses without red error metadata", () => {
  useChatStore.setState({ channels: {} });
  const store = useChatStore.getState();

  store.startTurn("channel-1", "turn-cancel-partial", "bot-1", "Bot", true);
  store.handleTurnEvent("channel-1", "turn-cancel-partial", {
    event: "text_delta",
    data: { delta: "partial answer" },
  });
  store.handleTurnEvent("channel-1", "turn-cancel-partial", {
    event: "error",
    data: { message: "cancelled" },
  });
  store.finishTurn("channel-1", "turn-cancel-partial");

  const messages = useChatStore.getState().getChannel("channel-1").messages;
  assert.equal(messages.length, 1);
  assert.equal(messages[0]?.content, "partial answer");
  assert.equal(messages[0]?.metadata?.turn_cancelled, true);
  assert.equal(messages[0]?.metadata?.turn_error, undefined);
});
