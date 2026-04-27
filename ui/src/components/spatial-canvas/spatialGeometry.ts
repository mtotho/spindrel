export interface Camera {
  x: number;
  y: number;
  scale: number;
}

export interface LensTransform {
  dxWorld: number;
  dyWorld: number;
  sizeFactor: number;
}

export const DEFAULT_CAMERA: Camera = { x: 0, y: 0, scale: 1 };
export const MIN_SCALE = 0.03;
export const MAX_SCALE = 8.0;
export const CAMERA_STORAGE_KEY = "spatial.camera";

// Canvas chrome preferences. Persisted across sessions so the user lands
// in the same visual state they last left.
export type DensityIntensity = "off" | "subtle" | "bold";
export type DensityWindow = "24h" | "7d" | "30d";
export const DENSITY_INTENSITY_KEY = "spatial.density.intensity";
export const CONNECTIONS_ENABLED_KEY = "spatial.connections.enabled";
export const DENSITY_WINDOW_KEY = "spatial.density.window";
export const DENSITY_COMPARE_KEY = "spatial.density.compare";
export const DENSITY_ANIMATE_KEY = "spatial.density.animate";
export const BOTS_VISIBLE_KEY = "spatial.bots.visible";
export const BOTS_REDUCED_KEY = "spatial.bots.reduced";
export const TRAILS_MODE_KEY = "spatial.trails.mode";
export const MINIMAP_VISIBLE_KEY = "spatial.minimap.visible";
export const LANDMARK_BEACONS_VISIBLE_KEY = "spatial.landmarkBeacons.visible";
export const ATTENTION_SIGNALS_VISIBLE_KEY = "spatial.attention.signalsVisible";
export const LENS_HINT_SEEN_KEY = "spatial.onboarding.lensHintSeen";

// Push-through dive — tunables for the continuous-zoom-into-channel gesture.
// User keeps zooming in on a channel tile; once `camera.scale` crosses
// `DIVE_SCALE_THRESHOLD` AND the viewport center sits inside the tile's
// padded bbox, a `DIVE_DWELL_MS`-long timer arms the dive. This is
// intentionally decoupled from `MAX_SCALE`: non-channel regions can support
// deeper inspection zooms without making channel push-through harder to
// trigger. Cancel by zooming out, panning the center off the tile, or
// starting a drag.
export const DIVE_SCALE_THRESHOLD = 2.55;
export const DIVE_DWELL_MS = 450;
export const DIVE_VIEWPORT_MARGIN = 0.2;

export type TrailsMode = "off" | "hover" | "all";

export function loadDensityIntensity(storage: Storage = localStorage): DensityIntensity {
  try {
    const v = storage.getItem(DENSITY_INTENSITY_KEY);
    if (v === "off" || v === "subtle" || v === "bold") return v;
  } catch {
    /* storage disabled */
  }
  return "subtle";
}

export function loadDensityWindow(storage: Storage = localStorage): DensityWindow {
  try {
    const v = storage.getItem(DENSITY_WINDOW_KEY);
    if (v === "24h" || v === "7d" || v === "30d") return v;
  } catch {
    /* storage disabled */
  }
  return "24h";
}

export function loadDensityCompare(storage: Storage = localStorage): boolean {
  try {
    return storage.getItem(DENSITY_COMPARE_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadDensityAnimate(storage: Storage = localStorage): boolean {
  try {
    if (storage.getItem(DENSITY_ANIMATE_KEY) === "0") return false;
  } catch {
    /* storage disabled */
  }
  return true;
}

export function loadConnectionsEnabled(storage: Storage = localStorage): boolean {
  try {
    const v = storage.getItem(CONNECTIONS_ENABLED_KEY);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch {
    /* storage disabled */
  }
  return true;
}

export function loadBotsVisible(storage: Storage = localStorage): boolean {
  try {
    const v = storage.getItem(BOTS_VISIBLE_KEY);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch {
    /* storage disabled */
  }
  return true;
}

export function loadBotsReduced(storage: Storage = localStorage): boolean {
  try {
    return storage.getItem(BOTS_REDUCED_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadTrailsMode(storage: Storage = localStorage): TrailsMode {
  try {
    const v = storage.getItem(TRAILS_MODE_KEY);
    if (v === "off" || v === "hover" || v === "all") return v;
  } catch {
    /* storage disabled */
  }
  return "hover";
}

export function loadMinimapVisible(storage: Storage = localStorage): boolean {
  try {
    const v = storage.getItem(MINIMAP_VISIBLE_KEY);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch {
    /* storage disabled */
  }
  return true;
}

export function loadLandmarkBeaconsVisible(storage: Storage = localStorage): boolean {
  try {
    const v = storage.getItem(LANDMARK_BEACONS_VISIBLE_KEY);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch {
    /* storage disabled */
  }
  return true;
}

export function loadAttentionSignalsVisible(storage: Storage = localStorage): boolean {
  try {
    const v = storage.getItem(ATTENTION_SIGNALS_VISIBLE_KEY);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch {
    /* storage disabled */
  }
  return true;
}

export const WELL_X = 0;
export const WELL_Y = 2200;
export const WELL_Y_SQUASH = 0.55;
export const MEMORY_OBSERVATORY_X = -2800;
export const MEMORY_OBSERVATORY_Y = 100;
export const ATTENTION_HUB_X = 0;
export const ATTENTION_HUB_Y = -650;
// Daily Health Summary landmark — sibling to the Attention Hub, offset to its
// right so the two read as a paired admin/ops cluster on the canvas.
export const HEALTH_SUMMARY_X = 1100;
export const HEALTH_SUMMARY_Y = -650;
export const WELL_RINGS: { minutes: number; label: string; major?: boolean }[] = [
  { minutes: 15, label: "15m" },
  { minutes: 60, label: "1h", major: true },
  { minutes: 60 * 6, label: "6h", major: true },
  { minutes: 60 * 12, label: "12h", major: true },
  { minutes: 60 * 24, label: "1d", major: true },
  { minutes: 60 * 24 * 2, label: "2d" },
  { minutes: 60 * 24 * 3, label: "3d", major: true },
  { minutes: 60 * 24 * 5, label: "5d" },
  { minutes: 60 * 24 * 7, label: "1w", major: true },
];
export const WELL_R_MIN = 110;
export const WELL_R_MAX = 650;

/**
 * DEFINITIONS_R — radius of the static outer ring where task definitions
 * orbit the Now Well. Sits just past `WELL_R_MAX` so it visually trails
 * the time-band rings without overlapping the 1w marker.
 */
export const DEFINITIONS_R = WELL_R_MAX * 1.42;
export const WELL_MAX_HORIZON_MIN = 60 * 24 * 7;
const WELL_RADIUS_STOPS: { minutes: number; radius: number }[] = [
  { minutes: 0, radius: WELL_R_MIN },
  { minutes: 15, radius: 150 },
  { minutes: 60, radius: 205 },
  { minutes: 60 * 6, radius: 285 },
  { minutes: 60 * 12, radius: 345 },
  { minutes: 60 * 24, radius: 410 },
  { minutes: 60 * 24 * 2, radius: 480 },
  { minutes: 60 * 24 * 3, radius: 540 },
  { minutes: 60 * 24 * 5, radius: 600 },
  { minutes: WELL_MAX_HORIZON_MIN, radius: WELL_R_MAX },
];

export const LENS_NATIVE_FRACTION = 0.22;
export const LENS_R_MAX_MULT = 1.8;
export const LENS_SIZE_EXP = 1.5;
export const LENS_SETTLE_MS = 250;
export const LENS_MIN_SCALE = 0.2;

export interface WorldBbox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * Visible viewport in world coordinates, given the current camera and
 * viewport pixel size. Optional `marginPx` extends the bbox by that many
 * screen pixels of overdraw on every side (converted to world coords).
 *
 * Used by world-layer renderers (MovementHistoryLayer, ConnectionLineLayer,
 * UsageDensityLayer, MovementTraceLayer) to cull off-screen content and
 * clip their backing SVGs to viewport-sized rectangles. iOS Safari WebKit
 * (esp. as a home-screen PWA) refuses to allocate SVG rasterization buffers
 * past ~4096px in either axis; world-bbox-sized SVGs blow that ceiling at
 * deep zoom and white-screen the canvas.
 */
export function getViewportWorldBbox(
  camera: Camera,
  viewport: { w: number; h: number },
  marginPx = 0,
): WorldBbox {
  const m = marginPx / Math.max(camera.scale, 1e-6);
  // `+ 0` normalizes -0 to +0 — bbox math doesn't care about IEEE sign of
  // zero, but downstream `Object.is` / strict-equal callers (esp. in tests)
  // do, so we erase the distinction at the source.
  return {
    minX: -camera.x / camera.scale - m + 0,
    minY: -camera.y / camera.scale - m + 0,
    maxX: (viewport.w - camera.x) / camera.scale + m + 0,
    maxY: (viewport.h - camera.y) / camera.scale + m + 0,
  };
}

/** Axis-aligned intersection. Returns null when the boxes don't overlap. */
export function intersectBbox(a: WorldBbox, b: WorldBbox): WorldBbox | null {
  const minX = Math.max(a.minX, b.minX);
  const minY = Math.max(a.minY, b.minY);
  const maxX = Math.min(a.maxX, b.maxX);
  const maxY = Math.min(a.maxY, b.maxY);
  if (minX >= maxX || minY >= maxY) return null;
  return { minX, minY, maxX, maxY };
}

/** Cheap AABB-vs-AABB hit test. */
export function bboxOverlaps(a: WorldBbox, b: WorldBbox): boolean {
  return a.minX < b.maxX && a.maxX > b.minX && a.minY < b.maxY && a.maxY > b.minY;
}

/**
 * Defensive ceiling on SVG width/height attributes. Picked to stay under the
 * iOS WebKit raster-buffer limit (~4096px in either axis) with margin.
 * Layers that compute their own bbox should clamp the resulting w/h to this.
 */
export const SVG_MAX_DIMENSION_PX = 4096;

export function clampCamera(camera: Camera): Camera {
  return {
    x: camera.x,
    y: camera.y,
    scale: Math.max(MIN_SCALE, Math.min(MAX_SCALE, camera.scale)),
  };
}

export function parseStoredCamera(raw: string | null): Camera {
  if (!raw) return DEFAULT_CAMERA;
  try {
    const parsed = JSON.parse(raw);
    if (
      parsed
      && typeof parsed.x === "number" && Number.isFinite(parsed.x)
      && typeof parsed.y === "number" && Number.isFinite(parsed.y)
      && typeof parsed.scale === "number" && Number.isFinite(parsed.scale)
      && parsed.scale >= MIN_SCALE && parsed.scale <= MAX_SCALE
    ) {
      return { x: parsed.x, y: parsed.y, scale: parsed.scale };
    }
  } catch {
    /* fall through */
  }
  return DEFAULT_CAMERA;
}

export function loadStoredCamera(storage: Storage = localStorage): Camera {
  try {
    return parseStoredCamera(storage.getItem(CAMERA_STORAGE_KEY));
  } catch {
    return DEFAULT_CAMERA;
  }
}

export function radiusForMinutes(minutes: number): number {
  const m = Math.max(0, Math.min(WELL_MAX_HORIZON_MIN, minutes));
  for (let i = 1; i < WELL_RADIUS_STOPS.length; i++) {
    const prev = WELL_RADIUS_STOPS[i - 1];
    const next = WELL_RADIUS_STOPS[i];
    if (m <= next.minutes) {
      const span = next.minutes - prev.minutes;
      const t = span <= 0 ? 0 : (m - prev.minutes) / span;
      return prev.radius + (next.radius - prev.radius) * t;
    }
  }
  return WELL_R_MAX;
}

export function projectFisheye(
  worldCx: number,
  worldCy: number,
  camera: Camera,
  focalScreen: { x: number; y: number },
  lensRadius: number,
): LensTransform {
  if (lensRadius <= 0) return { dxWorld: 0, dyWorld: 0, sizeFactor: 1 };
  const screenCx = camera.x + worldCx * camera.scale;
  const screenCy = camera.y + worldCy * camera.scale;
  const dxs = screenCx - focalScreen.x;
  const dys = screenCy - focalScreen.y;
  const r = Math.hypot(dxs, dys);
  if (r <= lensRadius) return { dxWorld: 0, dyWorld: 0, sizeFactor: 1 };
  const d = r - lensRadius;
  const rMax = lensRadius * LENS_R_MAX_MULT;
  const span = rMax - lensRadius;
  const rPrime = lensRadius + span * (1 - Math.exp(-d / span));
  const ratio = rPrime / r;
  const screenDx = (focalScreen.x - screenCx) * (1 - ratio);
  const screenDy = (focalScreen.y - screenCy) * (1 - ratio);
  const sizeFactor = Math.max(
    LENS_MIN_SCALE,
    Math.min(1, Math.pow(ratio, LENS_SIZE_EXP)),
  );
  return {
    dxWorld: screenDx / camera.scale,
    dyWorld: screenDy / camera.scale,
    sizeFactor,
  };
}
