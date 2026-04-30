/**
 * Deterministic Project planet geometry.
 *
 * Projects are larger work systems, not just larger channels. The renderer
 * uses this data to draw a lit project core, local orbital rails, member
 * channel moons, and a restrained overflow mark. All output is pure and
 * stable from the project id and attached channel count.
 */

function hashId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 33 + id.charCodeAt(i)) >>> 0;
  return h;
}

function lcgWalker(seed: number, salt: number): () => number {
  let walk = (seed ^ salt) >>> 0;
  return () => {
    walk = ((walk * 1103515245 + 12345) >>> 0) & 0x7fffffff;
    return walk / 0x7fffffff;
  };
}

export interface ProjectBandSeed {
  y: number;
  height: number;
  alpha: number;
}

export interface ProjectCraterSeed {
  x: number;
  y: number;
  r: number;
  alpha: number;
}

export interface ProjectMoonSeed {
  angleDeg: number;
  radius: number;
  size: number;
  hueShift: number;
}

export interface ProjectBodyTraits {
  hue: number;
  accentHue: number;
  shellTiltDeg: number;
  shellRy: number;
  bands: ProjectBandSeed[];
  craters: ProjectCraterSeed[];
  moons: ProjectMoonSeed[];
  overflowCount: number;
}

export function projectHue(id: string): number {
  return hashId(id) % 360;
}

export function projectBodyTraits(id: string, channelCount: number): ProjectBodyTraits {
  const seed = hashId(id);
  const top = lcgWalker(seed, 0x51a7e);
  const surface = lcgWalker(seed, 0x9c3b);
  const hue = projectHue(id);
  const visibleMoonCount = Math.min(Math.max(channelCount, 0), 5);
  const rotation = top() * 360;
  const shellTiltDeg = -18 + top() * 36;
  const shellRy = 18 + top() * 8;

  const bands: ProjectBandSeed[] = [];
  const bandCount = 4 + Math.floor(surface() * 3);
  for (let i = 0; i < bandCount; i++) {
    bands.push({
      y: 45 + i * (42 / Math.max(1, bandCount - 1)) + (surface() - 0.5) * 6,
      height: 4 + surface() * 6,
      alpha: 0.16 + surface() * 0.18,
    });
  }

  const craters: ProjectCraterSeed[] = [];
  const craterCount = 5 + Math.floor(surface() * 4);
  for (let i = 0; i < craterCount; i++) {
    craters.push({
      x: 82 + surface() * 50,
      y: 42 + surface() * 56,
      r: 2.2 + surface() * 4.4,
      alpha: 0.12 + surface() * 0.16,
    });
  }

  const moons: ProjectMoonSeed[] = [];
  for (let i = 0; i < visibleMoonCount; i++) {
    const evenSpread = visibleMoonCount <= 1 ? 0 : (i / visibleMoonCount) * 360;
    moons.push({
      angleDeg: rotation + evenSpread + (top() - 0.5) * 24,
      radius: 74 + (i % 2) * 14 + top() * 8,
      size: 4.4 + top() * 3.8,
      hueShift: 34 + i * 37 + top() * 28,
    });
  }

  return {
    hue,
    accentHue: (hue + 58 + Math.floor(top() * 56)) % 360,
    shellTiltDeg,
    shellRy,
    bands,
    craters,
    moons,
    overflowCount: Math.max(0, channelCount - visibleMoonCount),
  };
}

export interface ProjectMoonRender {
  cx: number;
  cy: number;
  r: number;
  fill: string;
  shadowFill: string;
}

export function projectMoonRenderProps(moon: ProjectMoonSeed, hue: number): ProjectMoonRender {
  const angle = (moon.angleDeg * Math.PI) / 180;
  const moonHue = (hue + moon.hueShift) % 360;
  return {
    cx: 110 + Math.cos(angle) * moon.radius,
    cy: 78 + Math.sin(angle) * moon.radius * 0.62,
    r: moon.size,
    fill: `hsl(${moonHue}, 58%, 66%)`,
    shadowFill: `hsl(${moonHue}, 46%, 28%)`,
  };
}

