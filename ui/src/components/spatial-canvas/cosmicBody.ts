/**
 * Channel-tile planet composition. Pure functions — every output is
 * deterministic from the channel id, so the same channel always renders the
 * same planet across reloads, viewers, and processes.
 *
 * The previous "blob" approach (organic border-radius silhouettes + layered
 * radial gradients) failed the readability bar at the on-screen tile sizes
 * that actually matter. A blob with internal nebula structure looks like a
 * misshapen colored splotch when it's only ~80–120px tall. Planets win by
 * making the SHAPE the identity: round silhouette + lit-side/terminator +
 * optional ring or moon. Identity comes from accessories and surface
 * pattern — high-contrast structure that reads at any zoom.
 *
 * The actual SVG composition lives in `ChannelTile.tsx`. This module returns
 * all the deterministic geometry and colors that the SVG renderer plugs in.
 */

/** Stable hash → 0..2^32 per channel id. */
function hashId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h;
}

/** Build an LCG walker seeded from `hashId(id) ^ salt` so different concerns
 *  (high-level traits vs. surface-specific scatter) can pull from independent
 *  pseudo-random streams. The single-nibble `bit(seed, slot)` approach this
 *  replaces clustered badly across small sequential id pools because the
 *  upper nibbles of `hashId` barely vary when ids share a common prefix. */
function lcgWalker(seed: number, salt: number): () => number {
  let walk = (seed ^ salt) >>> 0;
  return () => {
    walk = ((walk * 1103515245 + 12345) >>> 0) & 0x7fffffff;
    return walk / 0x7fffffff;
  };
}

export type CosmicIntensity = "soft" | "normal" | "warm";

export type PlanetSurface = "smooth" | "bands" | "swirl" | "spots" | "mottled";
export type PlanetAccessory = null | "ring" | "moon";

export interface BandSeed {
  /** y-center in SVG coords (0..100). */
  y: number;
  /** Band thickness in SVG coords. */
  height: number;
  /** HSL lightness 0..100 used for the band fill. */
  lightness: number;
  /** Alpha 0..1 for the band fill. */
  alpha: number;
}

export interface SpotSeed {
  /** x in SVG coords (0..100). */
  x: number;
  /** y in SVG coords (0..100). */
  y: number;
  /** Radius in SVG coords. */
  r: number;
}

export interface PlanetTraits {
  surface: PlanetSurface;
  accessory: PlanetAccessory;
  /** -45..+45 — ring tilt, only meaningful when accessory === "ring". */
  ringAngleDeg: number;
  /** 5..10 — vertical radius of the ring ellipse, slight per-channel variation. */
  ringRy: number;
  /** 0..360 — orbital position of the moon, only meaningful when accessory === "moon". */
  moonAngleDeg: number;
  /** 48..56 — moon orbit radius from planet center, just outside the 40-radius sphere. */
  moonRadius: number;
  /** 3..5 — moon size. */
  moonR: number;
  /** 3..5 entries when surface === "bands". */
  bands: BandSeed[];
  /** 2..4 entries when surface === "spots". */
  spots: SpotSeed[];
  /** Per-id swirl orientation + brightness, only meaningful when surface === "swirl". */
  swirl: { angle: number; brightness: number };
  /** 5..8 entries when surface === "mottled". */
  mottled: SpotSeed[];
}

const SURFACE_TYPES: PlanetSurface[] = ["smooth", "bands", "swirl", "spots", "mottled"];

/**
 * Derive the full set of per-channel planet traits from the channel id.
 * Every nibble of `hashId(id)` is reserved for a specific trait so callers
 * across reloads / viewers / processes always render the same planet.
 *
 * Surface-specific arrays (band positions, spot scatter, mottled noise) use
 * a small linear-congruential walk seeded from a constant XOR of the hash so
 * they don't fight with the bits used for high-level traits (surface +
 * accessory) or for the actual hue / dot-color derivation in `ChannelTile`.
 */
export function planetTraits(id: string): PlanetTraits {
  const seed = hashId(id);
  // Two independent streams: `top` for high-level traits (surface, accessory,
  // ring/moon position), `surf` for the per-surface scatter (band positions,
  // spot positions, etc.). Independent salts so the same nibble can't bias
  // two decisions toward correlated outcomes.
  const top = lcgWalker(seed, 0xa17e);
  const surf = lcgWalker(seed, 0xc1d3);

  const surface = SURFACE_TYPES[Math.floor(top() * 5) % SURFACE_TYPES.length];

  const accessoryRoll = top();
  const accessory: PlanetAccessory =
    accessoryRoll < 0.5 ? null : accessoryRoll < 0.75 ? "ring" : "moon";

  const ringAngleDeg = -45 + top() * 90;
  const ringRy = 5 + top() * 5;
  const moonAngleDeg = top() * 360;
  const moonRadius = 48 + top() * 8;
  const moonR = 3 + top() * 2;

  const bands: BandSeed[] = [];
  const spots: SpotSeed[] = [];
  const mottled: SpotSeed[] = [];
  let swirl = { angle: 0, brightness: 65 };

  if (surface === "bands") {
    const bandCount = 3 + Math.floor(surf() * 3);
    for (let i = 0; i < bandCount; i++) {
      const yCenter = 25 + (i + 0.5) * (50 / bandCount);
      const height = 4 + surf() * 4;
      const lightness = 40 + surf() * 30;
      const alpha = 0.3 + surf() * 0.2;
      bands.push({ y: yCenter, height, lightness, alpha });
    }
  } else if (surface === "spots") {
    const spotCount = 2 + Math.floor(surf() * 3);
    for (let i = 0; i < spotCount; i++) {
      const x = 32 + surf() * 28;
      const y = 32 + surf() * 28;
      const r = 2 + surf() * 3;
      spots.push({ x, y, r });
    }
  } else if (surface === "swirl") {
    swirl = {
      angle: -30 + surf() * 60,
      brightness: 60 + surf() * 15,
    };
  } else if (surface === "mottled") {
    const count = 5 + Math.floor(surf() * 4);
    for (let i = 0; i < count; i++) {
      const x = 25 + surf() * 50;
      const y = 25 + surf() * 50;
      const r = 1.5 + surf() * 2.5;
      mottled.push({ x, y, r });
    }
  }

  return {
    surface,
    accessory,
    ringAngleDeg,
    ringRy,
    moonAngleDeg,
    moonRadius,
    moonR,
    bands,
    spots,
    swirl,
    mottled,
  };
}

export interface GradientStop {
  offset: string;
  color: string;
}

/**
 * Atmosphere glow: transparent through 78%, ramps to a soft outer halo in
 * the channel hue at 100%. Replaces the old `boxShadow: inset 0 0 28px ...`
 * — this halo is what makes a read tile distinguishable from the dark
 * canvas background. Warm intensity (unread) roughly doubles the outer alpha.
 */
export function planetAtmosphereStops(hue: number, intensity: CosmicIntensity): GradientStop[] {
  const finalAlpha = intensity === "warm" ? 0.5 : intensity === "soft" ? 0.1 : 0.22;
  return [
    { offset: "0%", color: `hsla(${hue}, 70%, 60%, 0)` },
    { offset: "78%", color: `hsla(${hue}, 70%, 60%, 0)` },
    { offset: "92%", color: `hsla(${hue}, 80%, 70%, ${(finalAlpha * 0.55).toFixed(3)})` },
    { offset: "100%", color: `hsla(${hue}, 80%, 72%, ${finalAlpha.toFixed(3)})` },
  ];
}

/**
 * Sphere lighting: lit edge in the upper-left → mid-tones → terminator →
 * dark side. The light source position is fixed across all planets so they
 * read as a coherent solar system rather than a chaotic gallery.
 */
export function planetSphereStops(hue: number): GradientStop[] {
  return [
    { offset: "0%", color: `hsl(${hue}, 70%, 78%)` },
    { offset: "45%", color: `hsl(${hue}, 60%, 55%)` },
    { offset: "85%", color: `hsl(${hue}, 50%, 28%)` },
    { offset: "100%", color: `hsl(${hue}, 45%, 18%)` },
  ];
}

export interface BandRect {
  y: number;
  height: number;
  fill: string;
}

export function planetBandRects(traits: PlanetTraits, hue: number): BandRect[] {
  return traits.bands.map((b) => ({
    y: b.y - b.height / 2,
    height: b.height,
    fill: `hsla(${hue}, 55%, ${b.lightness.toFixed(1)}%, ${b.alpha.toFixed(3)})`,
  }));
}

export interface PlanetCircle {
  cx: number;
  cy: number;
  r: number;
  fill: string;
}

export function planetSpotCircles(traits: PlanetTraits): PlanetCircle[] {
  return traits.spots.map((s) => ({
    cx: s.x,
    cy: s.y,
    r: s.r,
    fill: "rgba(0, 0, 0, 0.32)",
  }));
}

export function planetMottledCircles(traits: PlanetTraits, hue: number): PlanetCircle[] {
  return traits.mottled.map((s, i) => ({
    cx: s.x,
    cy: s.y,
    r: s.r,
    fill:
      i % 2 === 0
        ? `hsla(${hue}, 50%, 32%, 0.42)`
        : `hsla(${hue}, 65%, 72%, 0.28)`,
  }));
}

export interface PlanetSwirl {
  /** SVG path "d" attribute for a single curved cloud band. */
  d: string;
  fill: string;
  /** Degrees to rotate around the planet center. */
  rotate: number;
}

export function planetSwirlPath(traits: PlanetTraits, hue: number): PlanetSwirl {
  return {
    d: "M 18 52 Q 32 38, 50 46 T 82 50 L 82 58 Q 66 66, 50 56 T 18 62 Z",
    fill: `hsla(${hue}, ${traits.swirl.brightness.toFixed(0)}%, 70%, 0.32)`,
    rotate: traits.swirl.angle,
  };
}

export interface PlanetMoon {
  cx: number;
  cy: number;
  r: number;
  fill: string;
  /** Inset shadow color used to suggest the moon is also lit upper-left. */
  shadowFill: string;
}

export function planetMoonProps(traits: PlanetTraits, hue: number): PlanetMoon {
  const angle = (traits.moonAngleDeg * Math.PI) / 180;
  return {
    cx: 50 + Math.cos(angle) * traits.moonRadius,
    cy: 50 + Math.sin(angle) * traits.moonRadius,
    r: traits.moonR,
    fill: `hsl(${hue}, 35%, 65%)`,
    shadowFill: `hsl(${hue}, 35%, 30%)`,
  };
}

export interface PlanetRing {
  rx: number;
  ry: number;
  /** Tilt around planet center, degrees. */
  angle: number;
  stroke: string;
  strokeWidth: number;
}

export function planetRingProps(traits: PlanetTraits, hue: number): PlanetRing {
  return {
    rx: 48,
    ry: traits.ringRy,
    angle: traits.ringAngleDeg,
    stroke: `hsla(${hue}, 65%, 75%, 0.6)`,
    strokeWidth: 2,
  };
}
