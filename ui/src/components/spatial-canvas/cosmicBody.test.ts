import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  planetAtmosphereStops,
  planetBandRects,
  planetMoonProps,
  planetSpotCircles,
  planetTraits,
} from "./cosmicBody.ts";

test("planetTraits is deterministic per id", () => {
  const a = planetTraits("channel-abc");
  const b = planetTraits("channel-abc");
  assert.deepEqual(a, b);
});

test("planetTraits surface distribution covers most of the 5 types over 20 ids", () => {
  // We expect at least 3 of the 5 surface types to show up across a small
  // sample. This catches the case where a bad mod / bad bit slot pinned every
  // tile to the same surface.
  const seen = new Set<string>();
  for (let i = 0; i < 20; i++) {
    seen.add(planetTraits(`ch-${i}`).surface);
  }
  assert.ok(seen.size >= 3, `expected ≥3 surface types across 20 ids, saw ${[...seen].join(", ")}`);
});

test("planetTraits accessory distribution is roughly 50% none / 25% ring / 25% moon", () => {
  // Loose bounds — the LCG isn't statistical-grade. Goal: make sure the
  // probability split isn't 100% / 0% (broken bit slot) or 0% / 100% (broken
  // threshold).
  let none = 0;
  let ring = 0;
  let moon = 0;
  const N = 60;
  for (let i = 0; i < N; i++) {
    const acc = planetTraits(`accessory-roll-${i}`).accessory;
    if (acc === null) none++;
    else if (acc === "ring") ring++;
    else moon++;
  }
  assert.ok(none > 0 && ring > 0 && moon > 0, `expected all three accessory types over ${N} ids — got none=${none} ring=${ring} moon=${moon}`);
  assert.ok(none > N * 0.25 && none < N * 0.75, `none-rate ${(none / N).toFixed(2)} should be near 0.5`);
});

test("ringAngleDeg always lies in [-45, 45] when accessory is 'ring'", () => {
  for (let i = 0; i < 50; i++) {
    const t = planetTraits(`ring-test-${i}`);
    if (t.accessory !== "ring") continue;
    assert.ok(
      t.ringAngleDeg >= -45 && t.ringAngleDeg <= 45,
      `ring angle ${t.ringAngleDeg} out of [-45, 45] for id=ring-test-${i}`,
    );
  }
});

test("moon center lies outside the planet (≥40) but inside extended viewBox (≤60)", () => {
  for (let i = 0; i < 50; i++) {
    const t = planetTraits(`moon-test-${i}`);
    if (t.accessory !== "moon") continue;
    const moon = planetMoonProps(t, 200);
    const dist = Math.sqrt((moon.cx - 50) ** 2 + (moon.cy - 50) ** 2);
    assert.ok(
      dist >= 40 && dist <= 60,
      `moon distance ${dist.toFixed(2)} out of [40, 60] for id=moon-test-${i}`,
    );
  }
});

test("planetAtmosphereStops 'warm' has higher peak alpha than 'normal'", () => {
  // Atmosphere is donut-shaped — peak alpha sits at an interior stop (~73%)
  // and the outer stop (100%) is fully transparent so the halo doesn't pad
  // into the tile's corners. So we compare the MAX alpha across all stops,
  // not the final-stop alpha.
  const warm = planetAtmosphereStops(120, "warm");
  const normal = planetAtmosphereStops(120, "normal");
  const peakAlpha = (stops: { color: string }[]) =>
    Math.max(
      ...stops.map((s) => parseFloat(s.color.match(/,\s*([\d.]+)\)$/)?.[1] ?? "0")),
    );
  assert.ok(
    peakAlpha(warm) > peakAlpha(normal),
    `warm peak ${peakAlpha(warm)} should exceed normal peak ${peakAlpha(normal)}`,
  );
});

test("planetBandRects returns 3..5 entries when surface is 'bands'", () => {
  for (let i = 0; i < 50; i++) {
    const t = planetTraits(`bands-test-${i}`);
    if (t.surface !== "bands") continue;
    const rects = planetBandRects(t, 220);
    assert.ok(
      rects.length >= 3 && rects.length <= 5,
      `expected 3..5 bands, got ${rects.length} for id=bands-test-${i}`,
    );
  }
});

test("planetSpotCircles returns 2..4 dots, all inside the 40-radius planet", () => {
  for (let i = 0; i < 50; i++) {
    const t = planetTraits(`spots-test-${i}`);
    if (t.surface !== "spots") continue;
    const circles = planetSpotCircles(t);
    assert.ok(
      circles.length >= 2 && circles.length <= 4,
      `expected 2..4 spots, got ${circles.length} for id=spots-test-${i}`,
    );
    for (const c of circles) {
      const dist = Math.sqrt((c.cx - 50) ** 2 + (c.cy - 50) ** 2);
      assert.ok(
        dist + c.r <= 40,
        `spot at (${c.cx.toFixed(1)}, ${c.cy.toFixed(1)}) r=${c.r.toFixed(1)} extends beyond planet (dist+r=${(dist + c.r).toFixed(2)})`,
      );
    }
  }
});
