import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  projectBodyTraits,
  projectHue,
  projectMoonRenderProps,
} from "./projectCosmicBody.ts";

test("projectBodyTraits is deterministic per project id and channel count", () => {
  const a = projectBodyTraits("project-alpha", 4);
  const b = projectBodyTraits("project-alpha", 4);
  assert.deepEqual(a, b);
});

test("projectBodyTraits clamps visible channel moons and reports overflow", () => {
  const empty = projectBodyTraits("project-empty", 0);
  assert.equal(empty.moons.length, 0);
  assert.equal(empty.overflowCount, 0);

  const crowded = projectBodyTraits("project-crowded", 9);
  assert.equal(crowded.moons.length, 5);
  assert.equal(crowded.overflowCount, 4);
});

test("project moons stay in the local project system viewBox", () => {
  for (let i = 0; i < 40; i++) {
    const traits = projectBodyTraits(`project-moon-${i}`, 5);
    for (const moon of traits.moons) {
      const render = projectMoonRenderProps(moon, traits.hue);
      assert.ok(render.cx - render.r >= 0 && render.cx + render.r <= 220, `moon cx ${render.cx} out of bounds`);
      assert.ok(render.cy - render.r >= 0 && render.cy + render.r <= 180, `moon cy ${render.cy} out of bounds`);
      assert.ok(render.r >= 4 && render.r <= 9, `moon size ${render.r} out of bounds`);
    }
  }
});

test("project hue varies across nearby ids", () => {
  const seen = new Set<number>();
  for (let i = 0; i < 16; i++) seen.add(projectHue(`project-${i}`));
  assert.ok(seen.size >= 8, `expected varied project hues, saw ${seen.size}`);
});
