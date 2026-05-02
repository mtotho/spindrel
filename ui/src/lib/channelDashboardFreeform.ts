import type { ChatZone, GridLayoutItem } from "@/src/types/api";
import type { GridPreset, GridPresetId } from "@/src/lib/dashboardGrid";

export const FREEFORM_CANVAS_MODE = "freeform_v1";
export const DASHBOARD_CAMERA_MIN_SCALE = 0.08;
export const DASHBOARD_CAMERA_MAX_SCALE = 1;
export const DASHBOARD_CAMERA_EXIT_SCALE = 0.1;
export const DASHBOARD_CANVAS_GAP = 12;

export interface DashboardCamera {
  x: number;
  y: number;
  scale: number;
}

export interface DashboardFreeformConfig {
  canvas_mode?: string;
  canvas_origin_x?: number;
  canvas_origin_y?: number;
  [key: string]: unknown;
}

export interface DashboardLayoutPatch extends GridLayoutItem {
  id: string;
  zone?: ChatZone;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface DashboardFrame {
  origin: { x: number; y: number };
  stepX: number;
  stepY: number;
  colWidth: number;
  centerWidth: number;
  frameX: number;
  frameY: number;
  centerRect: Rect;
}

export interface DashboardNeighborGhost {
  id: string;
  channelId: string;
  x: number;
  y: number;
  opacity: number;
}

export function clampDashboardCamera(camera: DashboardCamera): DashboardCamera {
  return {
    x: Number.isFinite(camera.x) ? camera.x : 0,
    y: Number.isFinite(camera.y) ? camera.y : 0,
    scale: Math.max(
      DASHBOARD_CAMERA_MIN_SCALE,
      Math.min(DASHBOARD_CAMERA_MAX_SCALE, Number.isFinite(camera.scale) ? camera.scale : 1),
    ),
  };
}

export function isFreeformGridConfig(gridConfig: unknown): boolean {
  return !!gridConfig
    && typeof gridConfig === "object"
    && (gridConfig as DashboardFreeformConfig).canvas_mode === FREEFORM_CANVAS_MODE;
}

export function freeformOriginForPreset(preset: Pick<GridPreset, "cols">): { x: number; y: number } {
  return { x: preset.cols.lg * 4, y: 8 };
}

export function originFromGridConfig(
  gridConfig: unknown,
  preset: Pick<GridPreset, "cols">,
): { x: number; y: number } {
  const fallback = freeformOriginForPreset(preset);
  if (!gridConfig || typeof gridConfig !== "object") return fallback;
  const cfg = gridConfig as DashboardFreeformConfig;
  return {
    x: Number.isFinite(cfg.canvas_origin_x) ? Math.max(0, Math.round(cfg.canvas_origin_x as number)) : fallback.x,
    y: Number.isFinite(cfg.canvas_origin_y) ? Math.max(0, Math.round(cfg.canvas_origin_y as number)) : fallback.y,
  };
}

export function buildFreeformGridConfig(
  existing: unknown,
  presetId: GridPresetId,
  origin: { x: number; y: number },
): DashboardFreeformConfig {
  const base = existing && typeof existing === "object"
    ? { ...(existing as Record<string, unknown>) }
    : {};
  return {
    ...base,
    layout_type: "grid",
    preset: presetId,
    canvas_mode: FREEFORM_CANVAS_MODE,
    canvas_origin_x: origin.x,
    canvas_origin_y: origin.y,
  };
}

export function migrateLayoutsToFreeform(
  layouts: Array<{ id: string; zone?: ChatZone; grid_layout?: Partial<GridLayoutItem> | null }>,
  origin: { x: number; y: number },
  fallback: GridLayoutItem,
): DashboardLayoutPatch[] {
  return layouts
    .map((item, index) => {
      const raw = item.grid_layout ?? {};
      const isGrid = (item.zone ?? "grid") === "grid";
      const base = {
        x: isGrid && Number.isFinite(raw.x) ? Math.max(0, Math.round(raw.x as number)) : (index % 2) * fallback.w,
        y: isGrid && Number.isFinite(raw.y) ? Math.max(0, Math.round(raw.y as number)) : Math.floor(index / 2) * fallback.h,
        w: isGrid && Number.isFinite(raw.w) ? Math.max(1, Math.round(raw.w as number)) : fallback.w,
        h: isGrid && Number.isFinite(raw.h) ? Math.max(1, Math.round(raw.h as number)) : fallback.h,
      };
      return {
        id: item.id,
        zone: "grid",
        x: base.x + origin.x,
        y: base.y + origin.y,
        w: base.w,
        h: base.h,
      };
    });
}

export function dashboardFrame(
  preset: GridPreset,
  origin: { x: number; y: number },
  centerWidth: number,
  minHeight: number,
): DashboardFrame {
  const safeCenterWidth = Math.max(320, centerWidth);
  const stepX = (safeCenterWidth + DASHBOARD_CANVAS_GAP) / preset.cols.lg;
  const colWidth = Math.max(8, stepX - DASHBOARD_CANVAS_GAP);
  const stepY = preset.rowHeight + DASHBOARD_CANVAS_GAP;
  const frameX = origin.x * stepX;
  const frameY = origin.y * stepY;
  const bodyH = Math.max(minHeight, preset.defaultTile.h * stepY * 3);
  return {
    origin,
    stepX,
    stepY,
    colWidth,
    centerWidth: safeCenterWidth,
    frameX,
    frameY,
    centerRect: { x: frameX, y: frameY, w: safeCenterWidth, h: bodyH },
  };
}

export function gridLayoutToWorldRect(layout: GridLayoutItem, frame: DashboardFrame): Rect {
  return {
    x: layout.x * frame.stepX,
    y: layout.y * frame.stepY,
    w: Math.max(frame.colWidth, layout.w * frame.stepX - DASHBOARD_CANVAS_GAP),
    h: Math.max(24, layout.h * frame.stepY - DASHBOARD_CANVAS_GAP),
  };
}

export function zonedLayoutToWorldRect(
  zone: ChatZone,
  layout: GridLayoutItem,
  frame: DashboardFrame,
): Rect {
  return gridLayoutToWorldRect(layout, frame);
}

export function classifyDashboardDrop(
  rect: Rect,
  frame: DashboardFrame,
): { zone: ChatZone; x: number; y: number } {
  return {
    zone: "grid",
    x: Math.max(0, Math.round(rect.x / frame.stepX)),
    y: Math.max(0, Math.round(rect.y / frame.stepY)),
  };
}

export function clampDropToZone(
  zone: ChatZone,
  x: number,
  y: number,
  w: number,
  h: number,
  cols: number,
): GridLayoutItem {
  return {
    x: Math.max(0, x),
    y: Math.max(0, y),
    w: Math.max(1, w),
    h: Math.max(1, h),
  };
}

export function rectsOverlap(a: GridLayoutItem, b: GridLayoutItem): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

export function findOpenGridPlacement(
  desired: GridLayoutItem,
  occupied: GridLayoutItem[],
  maxRadius = 18,
): GridLayoutItem {
  const start = { ...desired, x: Math.max(0, desired.x), y: Math.max(0, desired.y) };
  if (!occupied.some((box) => rectsOverlap(start, box))) return start;
  for (let radius = 1; radius <= maxRadius; radius += 1) {
    for (let dy = -radius; dy <= radius; dy += 1) {
      for (let dx = -radius; dx <= radius; dx += 1) {
        if (Math.abs(dx) !== radius && Math.abs(dy) !== radius) continue;
        const candidate = {
          ...start,
          x: Math.max(0, start.x + dx),
          y: Math.max(0, start.y + dy),
        };
        if (!occupied.some((box) => rectsOverlap(candidate, box))) return candidate;
      }
    }
  }
  let y = start.y + 1;
  while (occupied.some((box) => rectsOverlap({ ...start, y }, box))) y += 1;
  return { ...start, y };
}

export function fitFrameCamera(
  frame: Pick<DashboardFrame, "centerRect">,
  viewport: { w: number; h: number },
): DashboardCamera {
  const minX = frame.centerRect.x;
  const minY = frame.centerRect.y;
  const maxX = frame.centerRect.x + frame.centerRect.w;
  const maxY = frame.centerRect.y + frame.centerRect.h;
  const w = Math.max(1, maxX - minX);
  const h = Math.max(1, maxY - minY);
  const scale = Math.max(
    DASHBOARD_CAMERA_MIN_SCALE,
    Math.min(DASHBOARD_CAMERA_MAX_SCALE, Math.min(viewport.w / (w * 1.12), viewport.h / (h * 1.12))),
  );
  return clampDashboardCamera({
    scale,
    x: viewport.w / 2 - (minX + w / 2) * scale,
    y: viewport.h / 2 - (minY + h / 2) * scale,
  });
}

export function homeFrameCamera(
  frame: Pick<DashboardFrame, "centerRect">,
  viewport: { w: number; h: number },
): DashboardCamera {
  const minX = frame.centerRect.x;
  const maxX = frame.centerRect.x + frame.centerRect.w;
  const w = Math.max(1, maxX - minX);
  const x = w <= viewport.w - 48
    ? viewport.w / 2 - (minX + w / 2)
    : 24 - minX;
  return clampDashboardCamera({
    scale: DASHBOARD_CAMERA_MAX_SCALE,
    x,
    y: 24 - frame.centerRect.y,
  });
}

export function placeDashboardNeighborGhosts(
  frame: Pick<DashboardFrame, "centerRect">,
  neighbors: Array<{ id: string; channelId: string; dx: number; dy: number }>,
): DashboardNeighborGhost[] {
  const minX = frame.centerRect.x;
  const minY = frame.centerRect.y;
  const maxX = frame.centerRect.x + frame.centerRect.w;
  const maxY = frame.centerRect.y + frame.centerRect.h;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const halfW = (maxX - minX) / 2;
  const halfH = (maxY - minY) / 2;
  const fallbackStep = (Math.PI * 2) / Math.max(1, neighbors.length);

  return neighbors.map((neighbor, index) => {
    const angle = Number.isFinite(neighbor.dx) && Number.isFinite(neighbor.dy) && Math.hypot(neighbor.dx, neighbor.dy) > 1
      ? Math.atan2(neighbor.dy, neighbor.dx)
      : index * fallbackStep - Math.PI / 2;
    const ux = Math.cos(angle);
    const uy = Math.sin(angle);
    const edgeDistance = Math.min(
      Math.abs(ux) > 0.001 ? halfW / Math.abs(ux) : Number.POSITIVE_INFINITY,
      Math.abs(uy) > 0.001 ? halfH / Math.abs(uy) : Number.POSITIVE_INFINITY,
    );
    const lane = 720 + (index % 4) * 170;
    return {
      id: neighbor.id,
      channelId: neighbor.channelId,
      x: cx + ux * (edgeDistance + lane),
      y: cy + uy * (edgeDistance + lane),
      opacity: Math.max(0.34, 0.78 - index * 0.06),
    };
  });
}
