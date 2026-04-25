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
export const MIN_SCALE = 0.05;
export const MAX_SCALE = 3.0;
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

export const WELL_X = 0;
export const WELL_Y = 2200;
export const WELL_Y_SQUASH = 0.55;
export const WELL_RINGS: { minutes: number; label: string }[] = [
  { minutes: 60, label: "1h" },
  { minutes: 60 * 24, label: "1d" },
  { minutes: 60 * 24 * 7, label: "1w" },
];
export const WELL_R_MIN = 90;
export const WELL_R_MAX = 520;
export const WELL_MAX_HORIZON_MIN = 60 * 24 * 7;

export const LENS_NATIVE_FRACTION = 0.22;
export const LENS_R_MAX_MULT = 1.8;
export const LENS_SIZE_EXP = 1.5;
export const LENS_SETTLE_MS = 250;
export const LENS_MIN_SCALE = 0.2;

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
  const m = Math.max(0, minutes);
  const t = Math.min(1, Math.log(m + 1) / Math.log(WELL_MAX_HORIZON_MIN + 1));
  return WELL_R_MIN + (WELL_R_MAX - WELL_R_MIN) * t;
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
