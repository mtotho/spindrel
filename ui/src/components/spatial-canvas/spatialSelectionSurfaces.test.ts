import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const SPATIAL_DIR = resolve(process.cwd(), "src/components/spatial-canvas");

test("single spatial objects use Map Brief instead of the floating rail", () => {
  const source = readFileSync(resolve(SPATIAL_DIR, "useSpatialSelectionRail.tsx"), "utf8");
  assert.match(source, /kind === "channel-cluster"/);
  assert.doesNotMatch(source, /kind === "channel"/);
  assert.doesNotMatch(source, /kind === "bot"/);
  assert.doesNotMatch(source, /kind === "widget"/);
  assert.doesNotMatch(source, /kind === "landmark"/);
});

test("attention signal keeps the ring visual-only and makes only the badge clickable", () => {
  const source = readFileSync(resolve(SPATIAL_DIR, "SpatialAttentionLayer.tsx"), "utf8");
  assert.match(source, /pointer-events-none absolute left-1\/2 top-1\/2/);
  assert.match(source, /aria-hidden/);
  assert.match(source, /pointer-events-auto absolute -right-1 -top-1/);
  assert.match(source, /<AlertTriangle size=\{12\}/);
});

