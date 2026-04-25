import test from "node:test";
import assert from "node:assert/strict";

import {
  mapFromRows,
  rowsFromMap,
  shouldEmitMap,
  shouldSyncRows,
} from "./providerExtraHeadersState.js";

test("does not emit when serialized rows already match the incoming map", () => {
  const initial = { "OpenAI-Organization": "org_123" };
  const rows = rowsFromMap(initial);

  assert.equal(shouldEmitMap(initial, mapFromRows(rows)), false);
});

test("emits when the user changes a header value", () => {
  const initial = { "OpenAI-Organization": "org_123" };
  const rows = rowsFromMap(initial).map((row) =>
    row.key === "OpenAI-Organization" ? { ...row, value: "org_456" } : row
  );

  assert.equal(shouldEmitMap(initial, mapFromRows(rows)), true);
});

test("does not reset rows for identity-only incoming map churn", () => {
  const currentRows = rowsFromMap({ "HTTP-Referer": "https://example.com" });
  const sameHeadersNewObject = { "HTTP-Referer": "https://example.com" };

  assert.equal(shouldSyncRows(currentRows, sameHeadersNewObject), false);
});

test("resets rows when the incoming headers actually changed", () => {
  const currentRows = rowsFromMap({ "HTTP-Referer": "https://example.com" });
  const changedHeaders = { "HTTP-Referer": "https://other.example.com" };

  assert.equal(shouldSyncRows(currentRows, changedHeaders), true);
});
