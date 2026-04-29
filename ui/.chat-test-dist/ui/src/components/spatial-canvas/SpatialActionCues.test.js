import assert from "node:assert/strict";
import test from "node:test";
import { objectNearViewport, shouldRenderCueMarker, shouldShowCueHalo, topActionCompassItems, } from "./SpatialActionCues.js";
function item(id, intent, priority, x, y, distance = 0) {
    return {
        id,
        label: id,
        kind: "channel",
        worldX: x,
        worldY: y,
        worldW: 100,
        worldH: 80,
        distance,
        onSelect: () => undefined,
        workState: {
            id,
            kind: "channel",
            label: id,
            status: intent === "quiet" ? "idle" : "warning",
            severity: intent === "investigate" ? "error" : "info",
            primary_signal: null,
            counts: { upcoming: 0, recent: 0, warnings: intent === "investigate" ? 1 : 0 },
            next: null,
            recent: [],
            warnings: [],
            cue: {
                intent,
                label: intent,
                reason: `${intent} reason`,
                priority,
                target_surface: "channel",
                signal_kind: null,
                signal_title: null,
            },
            source: {},
            attached: {},
        },
    };
}
test("cue markers render only for actionable objects and suppress selected halos", () => {
    const investigate = item("investigate", "investigate", 95, 0, 0);
    const quiet = item("quiet", "quiet", 0, 0, 0);
    assert.equal(shouldRenderCueMarker(investigate), true);
    assert.equal(shouldRenderCueMarker(quiet), false);
    assert.equal(shouldShowCueHalo(investigate, null, 0.55), true);
    assert.equal(shouldShowCueHalo(investigate, "investigate", 0.55), false);
    assert.equal(shouldShowCueHalo(investigate, null, 0.2), false);
});
test("action compass ranks by cue priority before viewport bias", () => {
    const viewport = { minX: -100, minY: -100, maxX: 100, maxY: 100 };
    const highOffscreen = item("high-offscreen", "investigate", 95, 900, 900, 900);
    const lowerVisible = item("lower-visible", "investigate", 80, 0, 0, 0);
    const nextVisible = item("next-visible", "next", 90, 10, 10, 10);
    const quietVisible = item("quiet-visible", "quiet", 0, 0, 0, 0);
    assert.equal(objectNearViewport(lowerVisible, viewport), true);
    assert.equal(objectNearViewport(highOffscreen, viewport), false);
    assert.deepEqual(topActionCompassItems([quietVisible, nextVisible, lowerVisible, highOffscreen], viewport, 3).map((entry) => entry.id), ["high-offscreen", "lower-visible", "next-visible"]);
});
