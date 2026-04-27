/**
 * spatialDefinitionsOrbit — angle math for the outer ring of task
 * definition tiles around the Now Well.
 *
 * Definitions sit at a fixed elliptical radius (DEFINITIONS_R) and don't
 * drift inward. Each definition gets a deterministic angular slot derived
 * from its task id, so the same task lands the same place across reloads
 * and across viewers.
 */
import {
  DEFINITIONS_R,
  WELL_X,
  WELL_Y,
  WELL_Y_SQUASH,
} from "./spatialGeometry";

export interface DefinitionWellCenter {
  x: number;
  y: number;
}
const DEFAULT_WELL: DefinitionWellCenter = { x: WELL_X, y: WELL_Y };

/** Stable hash from a string to a uniform [0, 1) — FNV-1a 32-bit. */
export function angularSlotForId(id: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < id.length; i += 1) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  // 32-bit unsigned → [0, 1)
  return ((h >>> 0) % 1000000) / 1000000;
}

export interface DefinitionOrbitPoint {
  /** World-space x. */
  x: number;
  /** World-space y. */
  y: number;
  /** Radians around the well. */
  theta: number;
}

/**
 * World position of a definition tile on the outer ring.
 *
 * Optional `count` + `index` lets the caller distribute multiple tiles
 * evenly when there are few of them; with a small N this looks much
 * tidier than a hash-only spread (which can clump). When `count` is
 * undefined, falls back to the deterministic-hash slot.
 */
export function definitionOrbit(
  taskId: string,
  count?: number,
  index?: number,
  well: DefinitionWellCenter = DEFAULT_WELL,
): DefinitionOrbitPoint {
  let theta: number;
  if (count && count > 0 && index !== undefined && index >= 0) {
    // Even spacing with a per-id rotation seed so the ring isn't always
    // anchored at 0 radians (avoids identical orientation across workspaces).
    const seed = angularSlotForId(taskId.slice(0, 6) || "spindrel");
    theta = (index / count) * Math.PI * 2 + seed * 0.6;
  } else {
    theta = angularSlotForId(taskId) * Math.PI * 2;
  }
  const r = DEFINITIONS_R;
  const x = well.x + Math.cos(theta) * r;
  const y = well.y + Math.sin(theta) * r * WELL_Y_SQUASH;
  return { x, y, theta };
}
