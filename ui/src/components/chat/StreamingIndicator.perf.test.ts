import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SOURCE = readFileSync(
  resolve(process.cwd(), "src/components/chat/StreamingIndicator.tsx"),
  "utf8",
);

test("streaming indicator throttles large active render payloads", () => {
  assert.match(SOURCE, /const STREAMING_RENDER_THROTTLE_CHARS = 8_000/);
  assert.match(SOURCE, /const STREAMING_RENDER_THROTTLE_MS = 100/);
  assert.match(SOURCE, /useThrottledStreamingValue/);
  assert.match(SOURCE, /assistantTurnBodyTextLength/);
  assert.match(SOURCE, /renderedAssistantTurnBody/);
});
