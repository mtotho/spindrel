import test from "node:test";
import assert from "node:assert/strict";

import { buildHashTabUrl, writeHashTabHistory } from "./useHashTabHistory.js";

test("buildHashTabUrl preserves pathname and search while encoding the hash tab", () => {
  assert.equal(
    buildHashTabUrl("/channels/abc/settings", "?from=dashboard", "memory tools"),
    "/channels/abc/settings?from=dashboard#memory%20tools",
  );
});

test("writeHashTabHistory replaces history by default so tab switches do not trap Back", () => {
  const calls: Array<{ method: string; url: string | URL | null | undefined }> = [];
  const history = {
    pushState: (_data: unknown, _unused: string, url?: string | URL | null) => {
      calls.push({ method: "push", url });
    },
    replaceState: (_data: unknown, _unused: string, url?: string | URL | null) => {
      calls.push({ method: "replace", url });
    },
  };

  writeHashTabHistory(history, "/channels/abc/settings", "", "memory");

  assert.deepEqual(calls, [{ method: "replace", url: "/channels/abc/settings#memory" }]);
});

test("writeHashTabHistory can still opt into push mode when a caller explicitly wants navigation history", () => {
  const calls: Array<{ method: string; url: string | URL | null | undefined }> = [];
  const history = {
    pushState: (_data: unknown, _unused: string, url?: string | URL | null) => {
      calls.push({ method: "push", url });
    },
    replaceState: (_data: unknown, _unused: string, url?: string | URL | null) => {
      calls.push({ method: "replace", url });
    },
  };

  writeHashTabHistory(history, "/channels/abc/settings", "?from=dashboard", "presentation", "push");

  assert.deepEqual(calls, [{ method: "push", url: "/channels/abc/settings?from=dashboard#presentation" }]);
});
