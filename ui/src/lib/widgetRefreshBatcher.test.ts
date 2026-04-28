import test from "node:test";
import assert from "node:assert/strict";

import { createWidgetRefreshBatcher } from "./widgetRefreshBatcherCore.js";

test("widget refresh batcher flushes queued refreshes in one request", async () => {
  const calls: unknown[] = [];
  const batcher = createWidgetRefreshBatcher(async (body) => {
    calls.push(body);
    return {
      ok: true,
      results: body.requests.map((request) => ({
        request_id: request.request_id,
        ok: true,
        envelope: {
          content_type: "application/vnd.spindrel.components+json",
          body: "{\"components\":[]}",
          plain_body: "",
          display: "inline" as const,
          truncated: false,
          record_id: null,
          byte_size: 2,
        },
      })),
    };
  }, 1);

  const first = batcher.request({ tool_name: "get_weather", display_label: "Paris" });
  const second = batcher.request({ tool_name: "get_weather", display_label: "Paris" });
  const results = await Promise.all([first, second]);

  assert.equal(calls.length, 1);
  assert.equal(results.length, 2);
  assert.ok(results.every((result) => result.ok));
});

test("widget refresh batcher maps missing response rows to per-request errors", async () => {
  const batcher = createWidgetRefreshBatcher(async () => ({ ok: false, results: [] }), 1);

  const result = await batcher.request({ tool_name: "get_weather" });

  assert.equal(result.ok, false);
  assert.equal(result.error, "Refresh response missing result");
});
