import test from "node:test";
import assert from "node:assert/strict";

import {
  DASHBOARD_CANVAS_MIN_HEIGHT_FALLBACK,
  resolveDashboardCanvasMinHeight,
} from "./dashboardCanvasHeight.js";

test("resolveDashboardCanvasMinHeight fills the remaining viewport when the canvas starts above the fold", () => {
  const minHeight = resolveDashboardCanvasMinHeight({
    viewportHeight: 900,
    canvasTop: 180,
  });

  assert.equal(minHeight, 720);
});

test("resolveDashboardCanvasMinHeight never shrinks below the dashboard floor", () => {
  const minHeight = resolveDashboardCanvasMinHeight({
    viewportHeight: 480,
    canvasTop: 340,
  });

  assert.equal(minHeight, DASHBOARD_CANVAS_MIN_HEIGHT_FALLBACK);
});

test("resolveDashboardCanvasMinHeight tolerates missing canvas measurements", () => {
  const minHeight = resolveDashboardCanvasMinHeight({
    viewportHeight: 900,
    canvasTop: null,
  });

  assert.equal(minHeight, DASHBOARD_CANVAS_MIN_HEIGHT_FALLBACK);
});
