import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_CAMERA,
  MAX_SCALE,
  clampCamera,
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
