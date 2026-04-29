import assert from "node:assert/strict";
import test from "node:test";
import {
  type SpatialActionCueObject,
  objectNearViewport,
  shouldRenderCueMarker,
  topActionCompassItems,
} from "./SpatialActionCues.js";

function item(
  id: string,
  intent: "investigate" | "next" | "recent" | "quiet",
  priority: number,
  x: number,
  y: number,
  distance = 0,
): SpatialActionCueObject {
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
    } as any,
  };
}

test("cue markers render only for actionable objects", () => {
  const investigate = item("investigate", "investigate", 95, 0, 0);
  const quiet = item("quiet", "quiet", 0, 0, 0);
  assert.equal(shouldRenderCueMarker(investigate), true);
  assert.equal(shouldRenderCueMarker(quiet), false);
});

test("action compass ranks by cue priority before viewport bias", () => {
  const viewport = { minX: -100, minY: -100, maxX: 100, maxY: 100 };
  const highOffscreen = item("high-offscreen", "investigate", 95, 900, 900, 900);
  const lowerVisible = item("lower-visible", "investigate", 80, 0, 0, 0);
  const nextVisible = item("next-visible", "next", 90, 10, 10, 10);
  const quietVisible = item("quiet-visible", "quiet", 0, 0, 0, 0);
  assert.equal(objectNearViewport(lowerVisible, viewport), true);
  assert.equal(objectNearViewport(highOffscreen, viewport), false);
  assert.deepEqual(
    topActionCompassItems([quietVisible, nextVisible, lowerVisible, highOffscreen], viewport, 3).map((entry) => entry.id),
    ["high-offscreen", "lower-visible", "next-visible"],
  );
});
