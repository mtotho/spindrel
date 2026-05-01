import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const settingsSource = readFileSync(
  resolve(process.cwd(), "app/(app)/channels/[channelId]/settings.tsx"),
  "utf8",
);

test("channel settings back targets the owning channel instead of browser history", () => {
  assert.match(settingsSource, /export function channelSettingsBackTarget/);
  assert.match(settingsSource, /fromDashboard\s*\?\s*`\/widgets\/channel\/\$\{channelId\}`\s*:\s*`\/channels\/\$\{channelId\}`/);
  assert.match(settingsSource, /navigate\(backTarget,\s*\{\s*replace:\s*true\s*\}\)/);
  assert.doesNotMatch(settingsSource, /useGoBack\(/);
  assert.doesNotMatch(settingsSource, /navigate\(-1\)/);
});

test("channel settings header exposes a direct channel link", () => {
  assert.match(settingsSource, /const channelTarget = channelId \? `\/channels\/\$\{channelId\}` : "\/"/);
  assert.match(settingsSource, /Open channel/);
  assert.match(settingsSource, /navigate\(channelTarget,\s*\{\s*replace:\s*true\s*\}\)/);
});
