import test from "node:test";
import assert from "node:assert/strict";

import {
  DASHBOARD_CAMERA_MAX_SCALE,
  FREEFORM_CANVAS_MODE,
  buildFreeformGridConfig,
  clampDashboardCamera,
  classifyDashboardDrop,
  dashboardFrame,
  findOpenGridPlacement,
  freeformOriginForPreset,
  gridLayoutToWorldRect,
  isFreeformGridConfig,
  migrateLayoutsToFreeform,
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
