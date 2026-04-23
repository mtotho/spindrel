import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  resolveHeaderMetrics,
  resolveRouteSessionChrome,
} from "./sessionHeaderChrome.js";

test("session header metrics fall back to session stats when live context budget is missing", () => {
  const metrics = resolveHeaderMetrics(null, {
    utilization: 0.21,
    consumedTokens: 20_480,
    totalTokens: 100_000,
    grossPromptTokens: 20_480,
    currentPromptTokens: 19_200,
    cachedPromptTokens: 1_280,
    completionTokens: 64,
    contextProfile: "chat",
    turnsInContext: 22,
    turnsUntilCompaction: 18,
  });

  assert.equal(metrics.hasTokenMetrics, true);
  assert.equal(metrics.gross, 20_480);
  assert.equal(metrics.total, 100_000);
  assert.equal(metrics.current, 19_200);
  assert.equal(metrics.cached, 1_280);
  assert.equal(metrics.turnsInContext, 22);
  assert.equal(metrics.turnsUntilCompaction, 18);
});

test("session header metrics still expose token usage when total budget is unavailable", () => {
  const metrics = resolveHeaderMetrics(null, {
    utilization: null,
    consumedTokens: 18_240,
    totalTokens: null,
    grossPromptTokens: null,
    currentPromptTokens: null,
    cachedPromptTokens: null,
    completionTokens: null,
    contextProfile: null,
    turnsInContext: 2,
    turnsUntilCompaction: 38,
  });

  assert.equal(metrics.hasTokenMetrics, false);
  assert.equal(metrics.hasAnyTokenUsage, true);
  assert.equal(metrics.gross, 18_240);
  assert.equal(metrics.turnsInContext, 2);
  assert.equal(metrics.turnsUntilCompaction, 38);
});

test("route session chrome distinguishes primary from session routes", () => {
  assert.deepEqual(resolveRouteSessionChrome(false, "Ignored"), {
    modeLabel: "Primary",
    inlineTitle: null,
    inlineMeta: null,
    subtitleIdentity: null,
  });

  assert.deepEqual(resolveRouteSessionChrome(true, "  Investigate QA flow  ", "Apr 23, 09:05 AM"), {
    modeLabel: "Session",
    inlineTitle: "Investigate QA flow",
    inlineMeta: "Apr 23, 09:05 AM",
    subtitleIdentity: null,
  });

  assert.deepEqual(resolveRouteSessionChrome(true, null), {
    modeLabel: "Session",
    inlineTitle: null,
    inlineMeta: null,
    subtitleIdentity: "session",
  });
});

test("route session chrome compacts long titles", () => {
  const chrome = resolveRouteSessionChrome(
    true,
    "ok i want to plan to make some widget updates. can you review the @skill:widgets and come up with some improvements?",
    "Apr 23, 09:05 AM",
  );

  assert.equal(chrome.modeLabel, "Session");
  assert.equal(chrome.inlineMeta, "Apr 23, 09:05 AM");
  assert.ok(chrome.inlineTitle);
  assert.ok(chrome.inlineTitle.endsWith("..."));
  assert.ok(chrome.inlineTitle.length <= 56);
});

test("machine target chip stays session-scoped and does not own target deletion", () => {
  const chip = readFileSync(resolve(process.cwd(), "app/(app)/channels/[channelId]/MachineTargetChip.tsx"), "utf8");

  assert.doesNotMatch(chip, /useDeleteMachineTarget/);
  assert.doesNotMatch(chip, /Trash2/);
  assert.match(chip, /provider_id: target\.provider_id/);
});
