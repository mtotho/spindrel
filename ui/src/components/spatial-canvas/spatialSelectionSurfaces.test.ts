import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const SPATIAL_DIR = resolve(process.cwd(), "src/components/spatial-canvas");

test("single spatial objects use Map Brief instead of the floating rail", () => {
  const source = readFileSync(resolve(SPATIAL_DIR, "useSpatialSelectionRail.tsx"), "utf8");
  assert.match(source, /return null/);
  assert.doesNotMatch(source, /kind === "channel-cluster"/);
  assert.doesNotMatch(source, /kind === "channel"/);
  assert.doesNotMatch(source, /kind === "bot"/);
  assert.doesNotMatch(source, /kind === "widget"/);
  assert.doesNotMatch(source, /kind === "landmark"/);
});

test("channel clusters focus the map instead of opening selection chrome", () => {
  const source = readFileSync(resolve(SPATIAL_DIR, "SpatialCanvasWorld.tsx"), "utf8");
  assert.match(source, /flyToWorldBounds\(cluster\.worldBounds\)/);
  assert.match(source, /setSelectedSpatialObject\(null\)/);
  assert.doesNotMatch(source, /kind: "channel-cluster"/);
});

test("attention signal keeps the ring visual-only and makes only the badge clickable", () => {
  const source = readFileSync(resolve(SPATIAL_DIR, "SpatialAttentionLayer.tsx"), "utf8");
  assert.match(source, /pointer-events-none absolute left-1\/2 top-1\/2/);
  assert.match(source, /aria-hidden/);
  assert.match(source, /pointer-events-auto absolute -right-1 -top-1/);
  assert.match(source, /<AlertTriangle size=\{12\}/);
});

test("Map Brief jump frames targets left of an open Starboard panel", () => {
  const source = readFileSync(resolve(SPATIAL_DIR, "useSpatialNavigation.tsx"), "utf8");
  assert.match(source, /spatialVisibleCenterX/);
  assert.match(source, /querySelector\("\[data-starboard-panel='true'\]"\)/);
  assert.match(source, /panelRect\?\.left/);
  assert.match(source, /rect\.left/);
});

test("selected objects get a world anchor and suppress competing hover cards", () => {
  const source = readFileSync(resolve(SPATIAL_DIR, "SpatialCanvasWorld.tsx"), "utf8");
  assert.match(source, /data-spatial-selected-anchor/);
  assert.match(source, /SelectedObjectAnchor/);
  assert.match(source, /!starboardOpen \|\| !selectedSpatialObject/);
  assert.match(source, /!channelClusterMode/);
  assert.match(source, /interactiveZoom >= 0\.65/);
  assert.match(source, /setTimeout\(\(\) => setHoverCardNodeId/);
});
