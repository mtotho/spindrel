import test from "node:test";
import assert from "node:assert/strict";

import { getSuggestedWidgetSize, getWidgetLayoutBounds } from "./widgetLayoutHints.js";

test("getWidgetLayoutBounds applies authored min/max inside zone bounds", () => {
  const bounds = getWidgetLayoutBounds(
    {
      presentation_family: "card",
      layout_hints: {
        preferred_zone: "grid",
        min_cells: { w: 4, h: 3 },
        max_cells: { w: 12, h: 8 },
      },
    },
    "grid",
    12,
  );
  assert.deepEqual(bounds, { minW: 4, minH: 3, maxW: 12, maxH: 8 });
});

test("getWidgetLayoutBounds keeps header widgets inside the two-row rail", () => {
  const bounds = getWidgetLayoutBounds(
    {
      presentation_family: "card",
      layout_hints: {
        preferred_zone: "header",
        min_cells: { w: 6, h: 2 },
        max_cells: { w: 12, h: 5 },
      },
    },
    "header",
    12,
  );
  assert.deepEqual(bounds, { minW: 6, minH: 2, maxW: 12, maxH: 2 });
});

test("getSuggestedWidgetSize preserves chip defaults in the header rail", () => {
  const size = getSuggestedWidgetSize(
    {
      presentation_family: "chip",
      layout_hints: {
        preferred_zone: "chip",
        min_cells: { w: 4, h: 1 },
        max_cells: { w: 4, h: 1 },
      },
    },
    "header",
    { w: 6, h: 2 },
    12,
  );
  assert.deepEqual(size, { w: 4, h: 1 });
});

test("getSuggestedWidgetSize clamps oversized defaults to authored max cells", () => {
  const size = getSuggestedWidgetSize(
    {
      presentation_family: "card",
      layout_hints: {
        preferred_zone: "grid",
        min_cells: { w: 4, h: 3 },
        max_cells: { w: 12, h: 8 },
      },
    },
    "grid",
    { w: 6, h: 10 },
    12,
  );
  assert.deepEqual(size, { w: 6, h: 8 });
});
