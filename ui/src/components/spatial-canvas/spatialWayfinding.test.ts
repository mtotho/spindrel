import test from "node:test";
import assert from "node:assert/strict";

import { computeEdgeBeaconPosition } from "./spatialWayfinding.ts";

test("edge beacon is hidden when target is onscreen", () => {
  assert.equal(
    computeEdgeBeaconPosition({ x: 400, y: 300 }, { w: 800, h: 600 }),
    null,
  );
});

test("edge beacon lands on the left edge for far-left landmarks", () => {
  const pos = computeEdgeBeaconPosition({ x: -120, y: 300 }, { w: 800, h: 600 }, 40);

  assert.ok(pos);
  assert.equal(pos.side, "left");
  assert.equal(pos.x, 40);
  assert.equal(pos.y, 300);
});

test("edge beacon lands on the bottom edge for deep landmarks", () => {
  const pos = computeEdgeBeaconPosition({ x: 400, y: 760 }, { w: 800, h: 600 }, 40);

  assert.ok(pos);
  assert.equal(pos.side, "bottom");
  assert.equal(pos.x, 400);
  assert.equal(pos.y, 560);
});

test("edge beacon is hidden when target is too far beyond the edge", () => {
  assert.equal(
    computeEdgeBeaconPosition({ x: -1200, y: 300 }, { w: 800, h: 600 }, 40),
    null,
  );
});
