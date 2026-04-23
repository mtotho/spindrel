import test from "node:test";
import assert from "node:assert/strict";

import type { Message } from "../../types/api.js";
import { compactMessagesForJsonCopy } from "./messageJsonCopy.js";

test("copy-json compacts bulky interactive widget bodies but preserves ownership metadata", () => {
  const message: Message = {
    id: "msg-1",
    session_id: "session-1",
    role: "assistant",
    content: "Done.",
    created_at: "2026-04-23T01:47:52.082562Z",
    tool_calls: [
      {
        id: "call-search",
        name: "web_search",
        arguments: '{"query":"latest Google news","num_results":5}',
        surface: "widget",
      },
    ],
    metadata: {
      tool_results: [
        {
          tool_call_id: "call-search",
          content_type: "application/vnd.spindrel.html+interactive",
          body: `<script>window.spindrel.toolResult = ${JSON.stringify({ query: "latest Google news" })};</script>${"x".repeat(4000)}`,
          plain_body: "Widget: web_search",
          display: "inline",
          truncated: false,
          record_id: null,
          byte_size: 4096,
          display_label: "Web search",
        },
      ],
    },
  };

  const compact = compactMessagesForJsonCopy([message]);
  const result = compact[0]?.metadata?.tool_results?.[0];

  assert.equal(result.tool_call_id, "call-search");
  assert.equal(result.content_type, "application/vnd.spindrel.html+interactive");
  assert.equal(result.display_label, "Web search");
  assert.equal(result.byte_size, 4096);
  assert.equal(result.body, null);
  assert.equal(result.body_omitted, true);
  assert.match(result.body_preview, /window\.spindrel\.toolResult/);
});
