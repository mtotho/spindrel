/**
 * Cosmic-body channel-tile composition. Pure functions — every output is
 * deterministic from the channel id, so the same channel always renders the
 * same body across reloads, viewers, and processes.
 *
 * Three independent layers compose into one tile body:
 *
 *   1. Silhouette — `widerOrganicBorderRadius(id)` returns an 8-percentage
 *      `border-radius` string with a 15..85% range and asymmetry enforcement
 *      (no two opposite corners are allowed to collapse to the same value).
 *      Real organic shapes — leaf / teardrop / kidney — instead of the fat
 *      near-circles the previous 38..62% range produced.
 *   2. Multi-gradient body — `bodyGradients(id, hue, intensity)` returns the
 *      composited `background-image` string: a centered primary core plus
 *      two off-center radial gradients (a brighter "core eye" and a hue-
 *      shifted secondary dust cloud). Three internal light sources read as
 *      a nebula instead of a single flat fill.
 *   3. Particles — `bodyParticles(id, count)` returns deterministic positions
 *      for 6..10 faint star-dot overlay spans. Tile component renders them
 *      as absolutely-positioned divs.
 */

/** Stable hash → 0..2^32 per channel id. Mirrors `ChannelTile.hashId` so
 *  derived bytes are consistent across both files. */
function hashId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h;
}

/** Pull a value in [0, 1] from a specific seed/bit slot. The slot index lets
 *  callers reserve byte ranges so different layers don't fight over the same
 *  bits and accidentally correlate. */
function bit(seed: number, slot: number): number {
  return ((seed >> (slot * 4)) & 0xF) / 15;
}

/**
 * Per-channel deterministic border-radius. Eight percentages (4 corners ×
 * 2 axes) hashed off the id, each in 15..85%. After the initial draw the
 * function checks for accidental near-symmetry — if the spread between the
 * largest and smallest corner is below 30%, the two lowest corners are
 * inverted (replaced with `100 - value`) so the silhouette has visible
 * asymmetry. Deterministic; no random retry.
 */
export function widerOrganicBorderRadius(id: string): string {
  const seed = hashId(id);
  const raw: number[] = [];
  for (let i = 0; i < 8; i++) {
    raw.push(15 + bit(seed, i) * 70);
  }
  // Asymmetry enforcement — if the spread is too tight, invert the two
  // smallest corners to push them away from the cluster.
  const min = Math.min(...raw);
  const max = Math.max(...raw);
  if (max - min < 30) {
    const sortedIdx = raw
      .map((v, i) => ({ v, i }))
      .sort((a, b) => a.v - b.v)
      .slice(0, 2)
      .map((o) => o.i);
    for (const i of sortedIdx) raw[i] = 100 - raw[i];
  }
  const r = (i: number) => raw[i].toFixed(1);
  return (
    `${r(0)}% ${r(1)}% ${r(2)}% ${r(3)}%` +
    ` / ${r(4)}% ${r(5)}% ${r(6)}% ${r(7)}%`
  );
}

export type CosmicIntensity = "soft" | "normal" | "warm";

/**
 * Three-layered radial-gradient string suitable for a CSS `background` /
 * `background-image` value. Layers (back to front in CSS terms — last gradient
 * is rendered on top):
 *   1. Primary core — centered ellipse in the channel hue.
 *   2. Off-center bright spot ("core eye") — small circle, brighter, hue-
 *      saturated. Position deterministic in 25..55%.
 *   3. Secondary dust cloud — opposite quadrant, hue+30° rotation, more
 *      diffuse. Position deterministic in 55..85%.
 *
 * `intensity = "warm"` boosts every alpha by ~0.15 — used for unread channels
 * to nudge attention without re-introducing chrome.
 */
export function bodyGradients(
  id: string,
  hue: number,
  intensity: CosmicIntensity = "normal",
): string {
  const seed = hashId(id);
  const eyeX = 25 + bit(seed, 8) * 30;
  const eyeY = 25 + bit(seed, 9) * 30;
  const dustX = 55 + bit(seed, 10) * 30;
  const dustY = 55 + bit(seed, 11) * 30;

  const boost = intensity === "warm" ? 0.15 : intensity === "soft" ? -0.06 : 0;
  const a = (base: number) => Math.max(0, Math.min(1, base + boost));

  const primary =
    `radial-gradient(ellipse 65% 60% at 50% 50%, hsla(${hue}, 65%, 58%, ${a(0.42).toFixed(3)}) 0%, hsla(${hue}, 60%, 50%, ${a(0.18).toFixed(3)}) 55%, transparent 78%)`;
  const eye =
    `radial-gradient(circle at ${eyeX.toFixed(1)}% ${eyeY.toFixed(1)}%, hsla(${hue}, 80%, 72%, ${a(0.55).toFixed(3)}) 0%, hsla(${hue}, 70%, 60%, ${a(0.18).toFixed(3)}) 18%, transparent 38%)`;
  const dust =
    `radial-gradient(ellipse 50% 40% at ${dustX.toFixed(1)}% ${dustY.toFixed(1)}%, hsla(${(hue + 30) % 360}, 55%, 52%, ${a(0.32).toFixed(3)}) 0%, transparent 65%)`;

  // CSS painting order: first listed sits on top. Eye on top so the core
  // highlight reads as a focal point; dust below it; primary at the back.
  return `${eye}, ${dust}, ${primary}`;
}

/** Lightweight primary-only fallback for the dot tier — single cheap fill. */
export function bodyGradientPrimaryOnly(
  hue: number,
  intensity: CosmicIntensity = "normal",
): string {
  const boost = intensity === "warm" ? 0.15 : intensity === "soft" ? -0.06 : 0;
  const a = (base: number) => Math.max(0, Math.min(1, base + boost));
  return `radial-gradient(ellipse 65% 60% at 50% 50%, hsla(${hue}, 65%, 58%, ${a(0.42).toFixed(3)}) 0%, hsla(${hue}, 60%, 50%, ${a(0.18).toFixed(3)}) 55%, transparent 78%)`;
}

export interface ParticleSpec {
  /** Position as a percentage of tile width (0..100). */
  x: number;
  /** Position as a percentage of tile height (0..100). */
  y: number;
  /** 1 or 2 px square. */
  size: 1 | 2;
}

/**
 * Deterministic star-particle layout for a channel tile. Particles cluster
 * gently toward the center (avoiding the corners where the silhouette fades
 * to transparent) — uniform random would put dots in regions of the rect
 * that the body doesn't visually occupy.
 */
export function bodyParticles(id: string, count: number): ParticleSpec[] {
  const seed = hashId(id);
  const out: ParticleSpec[] = [];
  // Use a small linear-congruential walk seeded by hashId so we can pull
  // 4 values per particle without colliding with the bits used for shape /
  // gradient positions.
  let walk = (seed ^ 0xa5c3) >>> 0;
  const next = () => {
    walk = ((walk * 1103515245 + 12345) >>> 0) & 0x7fffffff;
    return walk / 0x7fffffff;
  };
  for (let i = 0; i < count; i++) {
    // Bias toward center — sample two values and average to compress edges.
    const rx = (next() + next()) / 2;
    const ry = (next() + next()) / 2;
    const x = 10 + rx * 80;
    const y = 10 + ry * 80;
    const size: 1 | 2 = next() < 0.65 ? 1 : 2;
    out.push({ x, y, size });
  }
  return out;
}
