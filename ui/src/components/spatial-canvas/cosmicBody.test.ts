import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  bodyGradients,
  bodyGradientPrimaryOnly,
  bodyParticles,
  widerOrganicBorderRadius,
} from "./cosmicBody.ts";

test("widerOrganicBorderRadius is deterministic per id", () => {
  const a = widerOrganicBorderRadius("channel-abc");
  const b = widerOrganicBorderRadius("channel-abc");
  assert.equal(a, b, "same id should produce identical border-radius string");
});

test("widerOrganicBorderRadius enforces visible asymmetry", () => {
  // Pull 12 different ids; for each, parse the 8 percentages and assert
  // that the spread between max and min is at least 30%. Asymmetry is what
  // turns "fat circle" silhouettes into recognizable organic shapes.
  const ids = [
    "abc", "def", "ghi", "jkl", "mno", "pqr",
    "stu", "vwx", "yz0", "123", "456", "789",
  ];
  for (const id of ids) {
    const radius = widerOrganicBorderRadius(id);
    const nums = (radius.match(/[\d.]+/g) ?? []).map(Number);
    assert.equal(nums.length, 8, `expected 8 percentages, got ${nums.length} for id=${id}`);
    const spread = Math.max(...nums) - Math.min(...nums);
    assert.ok(
      spread >= 30,
      `id=${id} produced spread=${spread.toFixed(1)} < 30 (radius=${radius})`,
    );
  }
});

test("widerOrganicBorderRadius percentages stay in [15, 100] band", () => {
  // Asymmetry enforcement may invert low corners (replace v with 100 - v).
  // Inverted corners can land at 100 (when v=0, but our floor is 15 → max
  // inverted is 85) but never above 100 or below 0.
  for (const id of ["x", "yy", "zzz", "channel-1", "channel-2"]) {
    const radius = widerOrganicBorderRadius(id);
    const nums = (radius.match(/[\d.]+/g) ?? []).map(Number);
    for (const n of nums) {
      assert.ok(n >= 15 && n <= 100, `corner ${n} out of range for id=${id}`);
    }
  }
});

test("bodyGradients emits exactly three radial-gradient layers", () => {
  const css = bodyGradients("channel-xyz", 200, "normal");
  const matches = css.match(/radial-gradient\(/g) ?? [];
  assert.equal(matches.length, 3, `expected 3 gradients, got ${matches.length} in ${css}`);
});

test("bodyGradients warm intensity boosts inner alphas", () => {
  const normal = bodyGradients("channel-xyz", 200, "normal");
  const warm = bodyGradients("channel-xyz", 200, "warm");
  // Pull the first alpha value from each (inside the first hsla(...) call).
  const normalAlpha = parseFloat(normal.match(/hsla\([^)]+,\s*([\d.]+)\)/)?.[1] ?? "0");
  const warmAlpha = parseFloat(warm.match(/hsla\([^)]+,\s*([\d.]+)\)/)?.[1] ?? "0");
  assert.ok(
    warmAlpha > normalAlpha,
    `warm alpha ${warmAlpha} should exceed normal alpha ${normalAlpha}`,
  );
});

test("bodyGradientPrimaryOnly emits exactly one radial-gradient", () => {
  const css = bodyGradientPrimaryOnly(120, "normal");
  const matches = css.match(/radial-gradient\(/g) ?? [];
  assert.equal(matches.length, 1);
});

test("bodyParticles is deterministic per id", () => {
  const a = bodyParticles("ch-abc", 8);
  const b = bodyParticles("ch-abc", 8);
  assert.deepEqual(a, b);
});

test("bodyParticles respects count + bounds", () => {
  const particles = bodyParticles("ch-xyz", 10);
  assert.equal(particles.length, 10);
  for (const p of particles) {
    assert.ok(p.x >= 10 && p.x <= 90, `x=${p.x} out of [10,90]`);
    assert.ok(p.y >= 10 && p.y <= 90, `y=${p.y} out of [10,90]`);
    assert.ok(p.size === 1 || p.size === 2);
  }
});
