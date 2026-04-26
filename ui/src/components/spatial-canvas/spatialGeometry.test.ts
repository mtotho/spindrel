import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_CAMERA,
  MAX_SCALE,
  bboxOverlaps,
  clampCamera,
  getViewportWorldBbox,
  intersectBbox,
  parseStoredCamera,
  projectFisheye,
  radiusForMinutes,
} from "./spatialGeometry.ts";

test("stored camera parsing rejects invalid persisted scale", () => {
  assert.deepEqual(parseStoredCamera(null), DEFAULT_CAMERA);
  assert.deepEqual(parseStoredCamera(JSON.stringify({ x: 1, y: 2, scale: 1.5 })), {
    x: 1,
    y: 2,
    scale: 1.5,
  });
  assert.deepEqual(parseStoredCamera(JSON.stringify({ x: 1, y: 2, scale: MAX_SCALE + 1 })), DEFAULT_CAMERA);
});

test("camera clamps programmatic camera moves to the persisted range", () => {
  assert.equal(clampCamera({ x: 10, y: 20, scale: MAX_SCALE + 10 }).scale, MAX_SCALE);
});

test("fisheye is identity inside radius and compresses outside radius", () => {
  const inside = projectFisheye(10, 0, { x: 0, y: 0, scale: 1 }, { x: 0, y: 0 }, 20);
  assert.deepEqual(inside, { dxWorld: 0, dyWorld: 0, sizeFactor: 1 });

  const outside = projectFisheye(200, 0, { x: 0, y: 0, scale: 1 }, { x: 0, y: 0 }, 50);
  assert.ok(outside.dxWorld < 0);
  assert.equal(outside.dyWorld, 0);
  assert.ok(outside.sizeFactor < 1);
});

test("now-well radius is monotonic and capped at the outer ring", () => {
  assert.ok(radiusForMinutes(60) > radiusForMinutes(1));
  assert.equal(radiusForMinutes(60 * 24 * 14), radiusForMinutes(60 * 24 * 7));
});

test("now-well week horizon gives multi-day items visible separation", () => {
  const oneDay = radiusForMinutes(60 * 24);
  const threeDays = radiusForMinutes(60 * 24 * 3);
  const oneWeek = radiusForMinutes(60 * 24 * 7);

  assert.ok(threeDays - oneDay >= 100);
  assert.ok(oneWeek - threeDays >= 100);
});

test("getViewportWorldBbox identity at scale=1, no translation, no margin", () => {
  const b = getViewportWorldBbox({ x: 0, y: 0, scale: 1 }, { w: 800, h: 600 });
  // Use +/-0-tolerant equality: `-0 / 1 === -0` per IEEE 754, and we don't
  // care about the sign of zero for bbox math.
  assert.equal(b.minX, 0);
  assert.equal(b.minY, 0);
  assert.equal(b.maxX, 800);
  assert.equal(b.maxY, 600);
});

test("getViewportWorldBbox accounts for camera translation", () => {
  // Camera offset (-100, -50) means the viewport origin sits at world (100, 50).
  const b = getViewportWorldBbox({ x: -100, y: -50, scale: 1 }, { w: 200, h: 100 });
  assert.deepEqual(b, { minX: 100, minY: 50, maxX: 300, maxY: 150 });
});

test("getViewportWorldBbox compresses world span when zoomed in", () => {
  // At scale 2.0, a 400-px viewport covers only 200 world units.
  const b = getViewportWorldBbox({ x: 0, y: 0, scale: 2 }, { w: 400, h: 400 });
  assert.equal(b.maxX - b.minX, 200);
  assert.equal(b.maxY - b.minY, 200);
});

test("getViewportWorldBbox margin is in screen-pixels, scaled into world units", () => {
  const b = getViewportWorldBbox({ x: 0, y: 0, scale: 2 }, { w: 100, h: 100 }, 40);
  // 40 screen-px / 2 scale = 20 world-px overdraw on every side.
  assert.equal(b.minX, -20);
  assert.equal(b.minY, -20);
  assert.equal(b.maxX, 70);
  assert.equal(b.maxY, 70);
});

test("intersectBbox returns the overlap rectangle when boxes overlap", () => {
  const a = { minX: 0, minY: 0, maxX: 100, maxY: 100 };
  const b = { minX: 50, minY: 50, maxX: 200, maxY: 200 };
  assert.deepEqual(intersectBbox(a, b), { minX: 50, minY: 50, maxX: 100, maxY: 100 });
});

test("intersectBbox returns null when boxes do not overlap", () => {
  const a = { minX: 0, minY: 0, maxX: 10, maxY: 10 };
  const b = { minX: 20, minY: 20, maxX: 30, maxY: 30 };
  assert.equal(intersectBbox(a, b), null);
});

test("intersectBbox treats edge-touching boxes as non-overlapping", () => {
  // Edge-touch is degenerate (zero area) — null lets callers skip rendering.
  const a = { minX: 0, minY: 0, maxX: 10, maxY: 10 };
  const b = { minX: 10, minY: 0, maxX: 20, maxY: 10 };
  assert.equal(intersectBbox(a, b), null);
});

test("bboxOverlaps mirrors intersectBbox truthiness", () => {
  const a = { minX: 0, minY: 0, maxX: 100, maxY: 100 };
  const inside = { minX: 10, minY: 10, maxX: 20, maxY: 20 };
  const outside = { minX: 200, minY: 200, maxX: 300, maxY: 300 };
  assert.equal(bboxOverlaps(a, inside), true);
  assert.equal(bboxOverlaps(a, outside), false);
});
