import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  DASHBOARD_CAMERA_MAX_SCALE,
  FREEFORM_CANVAS_MODE,
  buildFreeformGridConfig,
  clampDashboardCamera,
  clampDropToZone,
  classifyDashboardDrop,
  dashboardFrame,
  findOpenGridPlacement,
  freeformOriginForPreset,
  gridLayoutToWorldRect,
  homeFrameCamera,
  isFreeformGridConfig,
  migrateLayoutsToFreeform,
  placeDashboardNeighborGhosts,
} from "./channelDashboardFreeform.ts";
import type { GridPreset } from "./dashboardGrid.ts";

const preset = {
  id: "standard",
  label: "Standard",
  description: "",
  cols: { lg: 12, md: 6, sm: 4, xs: 2, xxs: 1 },
  rowHeight: 30,
  defaultTile: { w: 6, h: 10 },
  minTile: { w: 2, h: 3 },
  sizePresets: [],
} as GridPreset;

test("freeform grid config preserves existing dashboard settings", () => {
  const origin = freeformOriginForPreset(preset);
  const cfg = buildFreeformGridConfig(
    { borderless: true, hover_scrollbars: false, layout_mode: "grid" },
    "standard",
    origin,
  );

  assert.equal(cfg.canvas_mode, FREEFORM_CANVAS_MODE);
  assert.equal(cfg.borderless, true);
  assert.equal(cfg.hover_scrollbars, false);
  assert.equal(cfg.layout_mode, "grid");
  assert.equal(isFreeformGridConfig(cfg), true);
});

test("legacy grid layouts offset once into freeform space", () => {
  const origin = { x: 48, y: 8 };
  const patches = migrateLayoutsToFreeform(
    [
      { id: "a", zone: "grid", grid_layout: { x: 0, y: 0, w: 6, h: 10 } },
      { id: "b", zone: "rail", grid_layout: { x: 0, y: 5, w: 1, h: 6 } },
    ],
    origin,
    { x: 0, y: 0, w: 6, h: 10 },
  );

  assert.deepEqual(patches, [{ id: "a", zone: "grid", x: 48, y: 8, w: 6, h: 10 }]);
});

test("drop classifier keeps rail, dock, header, and free grid distinct", () => {
  const origin = freeformOriginForPreset(preset);
  const frame = dashboardFrame(preset, origin, 720, 900);

  assert.equal(classifyDashboardDrop({ ...frame.railRect, w: 120, h: 100 }, frame).zone, "rail");
  assert.equal(classifyDashboardDrop({ ...frame.dockRect, w: 120, h: 100 }, frame).zone, "dock");
  assert.equal(classifyDashboardDrop({ ...frame.headerRect, w: 120, h: 30 }, frame).zone, "header");

  const freeRect = gridLayoutToWorldRect({ x: origin.x + 20, y: origin.y + 20, w: 3, h: 4 }, frame);
  assert.equal(classifyDashboardDrop(freeRect, frame).zone, "grid");
});

test("header drop can fit the full top center lane", () => {
  assert.deepEqual(
    clampDropToZone("header", 0, 0, preset.cols.lg, 2, preset.cols.lg),
    { x: 0, y: 0, w: preset.cols.lg, h: 2 },
  );
});

test("open placement searches around a collided target", () => {
  const next = findOpenGridPlacement(
    { x: 4, y: 4, w: 3, h: 3 },
    [{ x: 4, y: 4, w: 3, h: 3 }],
  );

  assert.notDeepEqual(next, { x: 4, y: 4, w: 3, h: 3 });
  assert.equal(next.w, 3);
  assert.equal(next.h, 3);
});

test("dashboard camera never zooms past current dashboard scale", () => {
  const camera = clampDashboardCamera({ x: 1, y: 2, scale: 8 });

  assert.equal(camera.scale, DASHBOARD_CAMERA_MAX_SCALE);
});

test("home dashboard camera keeps the native dashboard scale", () => {
  const frame = dashboardFrame(preset, freeformOriginForPreset(preset), 720, 900);
  const camera = homeFrameCamera(frame, { w: 1800, h: 760 });
  const minX = Math.min(frame.railRect.x, frame.headerRect.x, frame.centerRect.x);
  const maxX = Math.max(frame.dockRect.x + frame.dockRect.w, frame.headerRect.x + frame.headerRect.w);
  const frameWidth = maxX - minX;

  assert.equal(camera.scale, DASHBOARD_CAMERA_MAX_SCALE);
  assert.equal(camera.x, 1800 / 2 - (minX + frameWidth / 2));
  assert.equal(camera.y, 24 - frame.headerRect.y);
});

test("home dashboard camera keeps the left edge visible on narrow containers", () => {
  const frame = dashboardFrame(preset, freeformOriginForPreset(preset), 1080, 900);
  const camera = homeFrameCamera(frame, { w: 900, h: 760 });
  const minX = Math.min(frame.railRect.x, frame.headerRect.x, frame.centerRect.x);

  assert.equal(camera.scale, DASHBOARD_CAMERA_MAX_SCALE);
  assert.equal(camera.x, 24 - minX);
});

test("dashboard camera supports deep zoom-out before spatial handoff CTA", () => {
  const camera = clampDashboardCamera({ x: 1, y: 2, scale: 0.01 });

  assert.equal(camera.scale, 0.08);
});

test("neighbor ghosts stay outside the guided dashboard frame", () => {
  const origin = freeformOriginForPreset(preset);
  const frame = dashboardFrame(preset, origin, 720, 900);
  const ghosts = placeDashboardNeighborGhosts(frame, [
    { id: "near", channelId: "c1", dx: 12, dy: 12 },
    { id: "far", channelId: "c2", dx: -90, dy: 30 },
  ]);

  for (const ghost of ghosts) {
    const insideX = ghost.x >= frame.railRect.x && ghost.x <= frame.dockRect.x + frame.dockRect.w;
    const insideY = ghost.y >= frame.headerRect.y && ghost.y <= frame.centerRect.y + frame.centerRect.h;
    assert.equal(insideX && insideY, false);
  }
});

test("freeform dashboard canvas has one lock reset outside the canvas controls", () => {
  const source = readFileSync(new URL("../../app/(app)/widgets/ChannelDashboardFreeformCanvas.tsx", import.meta.url), "utf8");
  const routeSource = readFileSync(new URL("../../app/(app)/widgets/index.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(source, /useDraggable/);
  assert.doesNotMatch(source, /CanvasControls/);
  assert.doesNotMatch(source, /Fit dashboard/);
  assert.match(source, /function classifyDashboardPointer/);
  assert.match(source, /pointInRect\(point, frame\.railRect, 28\)/);
  assert.match(source, /const target = classifyDashboardPointer\(pointerWorld, movedRect, frame\)/);
  assert.match(source, /const fromNarrowZoneToGrid = normalizeZone\(pin\) !== "grid" && target\.zone === "grid"/);
  assert.doesNotMatch(source, /findOpenGridPlacement\(desired, gridOccupancy\(pins, layouts, pinId\)\)/);
  assert.match(source, /const snappedRect = zonedLayoutToWorldRect\(target\.zone, next, frame\)/);
  assert.match(source, /rect: settleCollision \|\| target\.zone !== "grid"\s+\? snappedRect\s+: \{ \.\.\.movedRect, w: snappedRect\.w, h: snappedRect\.h \}/);
  assert.match(source, /clampDropToZone\("header", 0, 0, preset\.cols\.lg, DASHBOARD_HEADER_ROWS, preset\.cols\.lg\)/);
  assert.match(source, /cursor: viewLocked \? "default" : isPanning \? "grabbing" : "grab"/);
  assert.match(routeSource, /viewLocked=\{dashboardViewLocked\}/);
  assert.match(routeSource, /aria-pressed=\{dashboardViewLocked\}/);
  assert.match(routeSource, /Lock canvas view/);
  assert.match(routeSource, /overflow-hidden p-0/);
});
