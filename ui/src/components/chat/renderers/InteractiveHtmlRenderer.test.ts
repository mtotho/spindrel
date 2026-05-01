import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SOURCE = readFileSync(
  resolve(process.cwd(), "src/components/chat/renderers/InteractiveHtmlRenderer.tsx"),
  "utf8",
);

test("widget stream preamble waits briefly for broker ack before direct SSE fallback", () => {
  assert.match(SOURCE, /const __STREAM_BROKER_SETTLE_MS = 75/);
  assert.match(SOURCE, /settleTimer = setTimeout\(startBestAvailable, __STREAM_BROKER_SETTLE_MS\)/);
  assert.match(SOURCE, /activeUnsub = brokerMatches\(\) \? startBroker\(\) : startDirect\(\)/);
  assert.match(SOURCE, /clearTimeout\(settleTimer\)/);
});

test("widget direct stream fallback tracks and clears reconnect timers", () => {
  assert.match(SOURCE, /let reconnectTimer = null/);
  assert.match(SOURCE, /clearTimeout\(reconnectTimer\)/);
  assert.match(SOURCE, /reconnectTimer = setTimeout/);
  assert.match(SOURCE, /controller\.abort\(\)/);
});
