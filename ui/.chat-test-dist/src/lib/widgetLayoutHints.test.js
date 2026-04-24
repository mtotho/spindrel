import test from "node:test";
import assert from "node:assert/strict";
import { getSuggestedWidgetSize, getWidgetLayoutBounds } from "./widgetLayoutHints.js";
test("getWidgetLayoutBounds uses host-zone bounds for editor resizing", () => {
    const bounds = getWidgetLayoutBounds({
        presentation_family: "card",
        layout_hints: {
            preferred_zone: "grid",
            min_cells: { w: 4, h: 3 },
            max_cells: { w: 12, h: 8 },
        },
    }, "grid", 12);
    assert.deepEqual(bounds, { minW: 1, minH: 1, maxW: 12 });
});
test("getWidgetLayoutBounds keeps header editor resize inside the two-row rail", () => {
    const bounds = getWidgetLayoutBounds({
        presentation_family: "card",
        layout_hints: {
            preferred_zone: "header",
            min_cells: { w: 6, h: 2 },
            max_cells: { w: 12, h: 5 },
        },
    }, "header", 12);
    assert.deepEqual(bounds, { minW: 1, minH: 1, maxW: 12, maxH: 2 });
});
test("getSuggestedWidgetSize preserves chip defaults in the header rail", () => {
    const size = getSuggestedWidgetSize({
        presentation_family: "chip",
        layout_hints: {
            preferred_zone: "chip",
            min_cells: { w: 4, h: 1 },
            max_cells: { w: 4, h: 1 },
        },
    }, "header", { w: 6, h: 2 }, 12);
    assert.deepEqual(size, { w: 4, h: 1 });
});
test("getSuggestedWidgetSize clamps oversized defaults to authored max cells", () => {
    const size = getSuggestedWidgetSize({
        presentation_family: "card",
        layout_hints: {
            preferred_zone: "grid",
            min_cells: { w: 4, h: 3 },
            max_cells: { w: 12, h: 8 },
        },
    }, "grid", { w: 6, h: 10 }, 12);
    assert.deepEqual(size, { w: 6, h: 8 });
});
test("getSuggestedWidgetSize ignores chip max cells after moving to grid", () => {
    const size = getSuggestedWidgetSize({
        presentation_family: "chip",
        layout_hints: {
            preferred_zone: "chip",
            max_cells: { w: 4, h: 1 },
        },
    }, "grid", { w: 6, h: 10 }, 12);
    assert.deepEqual(size, { w: 6, h: 10 });
});
