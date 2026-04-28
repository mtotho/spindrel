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
    const worldSource = readFileSync(resolve(SPATIAL_DIR, "SpatialCanvasWorld.tsx"), "utf8");
    const markerSource = readFileSync(resolve(SPATIAL_DIR, "ChannelClusterMarker.tsx"), "utf8");
    const canvasSource = readFileSync(resolve(SPATIAL_DIR, "SpatialCanvas.tsx"), "utf8");
    assert.match(worldSource, /CHANNEL_CLUSTER_FOCUS_MIN_SCALE = 0\.42/);
    assert.match(worldSource, /flyToWorldBounds\(cluster\.worldBounds, CHANNEL_CLUSTER_FOCUS_MIN_SCALE\)/);
    assert.match(worldSource, /setSelectedSpatialObject\(null\)/);
    assert.match(canvasSource, /flyToWorldBounds=\{flyToWorldBounds\}/);
    assert.doesNotMatch(worldSource, /onDiveWinner/);
    assert.doesNotMatch(worldSource, /diveToChannel\(cluster\.winner\.channel\.id/);
    assert.doesNotMatch(markerSource, /onDiveWinner/);
    assert.match(markerSource, /focusPrimaryCluster/);
    assert.match(markerSource, /onPointerDown=\{focusPrimaryCluster\}/);
    assert.match(markerSource, /onMouseDown=\{focusPrimaryCluster\}/);
    assert.match(markerSource, /onDoubleClick=\{focusPrimaryCluster\}/);
    assert.doesNotMatch(canvasSource, /kind: "channel-cluster"/);
});
test("cluster overview suppresses the focus lens hint", () => {
    const source = readFileSync(resolve(SPATIAL_DIR, "SpatialCanvasOverlays.tsx"), "utf8");
    assert.doesNotMatch(source, /LensHint/);
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
test("cluster focus can recover viewport metrics before flying bounds", () => {
    const source = readFileSync(resolve(SPATIAL_DIR, "useSpatialNavigation.tsx"), "utf8");
    assert.match(source, /querySelector\('\[data-spatial-canvas="true"\]'\)/);
    assert.match(source, /getBoundingClientRect\(\)/);
    assert.match(source, /viewportRectRef\.current = rect/);
});
test("selected objects get a world anchor and suppress competing hover cards", () => {
    const source = readFileSync(resolve(SPATIAL_DIR, "SpatialCanvasWorld.tsx"), "utf8");
    assert.match(source, /data-spatial-selected-anchor/);
    assert.match(source, /SelectedObjectAnchor/);
    assert.match(source, /ring-1 ring-offset-2/);
    assert.match(source, /!starboardOpen \|\| !selectedSpatialObject/);
    assert.match(source, /!channelClusterMode/);
    assert.match(source, /interactiveZoom >= 0\.65/);
    assert.match(source, /setTimeout\(\(\) => setHoverCardNodeId/);
});
test("Map Brief selected object uses quiet triage instead of side-stripe chrome", () => {
    const source = readFileSync(resolve(SPATIAL_DIR, "UsageDensityChrome.tsx"), "utf8");
    assert.match(source, /data-brief-tone=\{tone\}/);
    assert.match(source, /SelectedObjectMetaChips/);
    assert.match(source, /selectedInspectorToneClass/);
    assert.doesNotMatch(source, /border-l-2/);
    assert.doesNotMatch(source, /border-l-danger/);
    assert.doesNotMatch(source, /border-l-warning/);
    assert.doesNotMatch(source, /border-l-accent/);
});
