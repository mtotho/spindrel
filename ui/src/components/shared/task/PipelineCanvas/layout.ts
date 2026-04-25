/**
 * Pipeline Canvas layout helpers.
 *
 * Auto-place algorithm: top-down stack at viewport center for steps that
 * don't have a saved position. The runtime never reads `Task.layout` —
 * positions are pure UI state.
 */
import type { StepDef, TaskLayout } from "@/src/api/hooks/useTasks";

export interface NodePosition {
  x: number;
  y: number;
}

export const NODE_W = 200;
export const NODE_H = 80;
export const VERTICAL_GAP = 60;

const AUTO_PLACE_X = 0;
const AUTO_PLACE_Y_START = 0;

/**
 * Walk steps and return a {nodes} map with every step ID positioned.
 * Steps with a saved position keep it; missing steps get auto-placed in a
 * top-down stack starting at (AUTO_PLACE_X, AUTO_PLACE_Y_START).
 */
export function ensurePositions(steps: StepDef[], layout: TaskLayout): TaskLayout {
  const existing = layout.nodes ?? {};
  const positioned: Record<string, NodePosition> = {};

  // Find the lowest occupied y so auto-placed nodes stack below.
  let nextY = AUTO_PLACE_Y_START;
  for (const id of Object.keys(existing)) {
    const pos = existing[id];
    if (pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)) {
      positioned[id] = { x: pos.x, y: pos.y };
      nextY = Math.max(nextY, pos.y + NODE_H + VERTICAL_GAP);
    }
  }

  // Auto-place missing steps.
  let changed = false;
  for (const step of steps) {
    if (!positioned[step.id]) {
      positioned[step.id] = { x: AUTO_PLACE_X, y: nextY };
      nextY += NODE_H + VERTICAL_GAP;
      changed = true;
    }
  }

  // Drop positions for steps that no longer exist (avoids silent bloat).
  const stepIds = new Set(steps.map((s) => s.id));
  for (const id of Object.keys(existing)) {
    if (!stepIds.has(id)) changed = true;
  }

  if (!changed && Object.keys(existing).length === Object.keys(positioned).length) {
    return layout;
  }

  return {
    ...layout,
    version: layout.version ?? 1,
    nodes: positioned,
  };
}

/**
 * Set a single node's position, returning a new layout object.
 */
export function setNodePosition(
  layout: TaskLayout,
  nodeId: string,
  pos: NodePosition,
): TaskLayout {
  return {
    ...layout,
    version: layout.version ?? 1,
    nodes: { ...(layout.nodes ?? {}), [nodeId]: pos },
  };
}
