export const DASHBOARD_CANVAS_MIN_HEIGHT_FALLBACK = 240;

interface ResolveDashboardCanvasMinHeightArgs {
  viewportHeight: number;
  canvasTop: number | null;
  fallback?: number;
  bottomGap?: number;
}

export function resolveDashboardCanvasMinHeight({
  viewportHeight,
  canvasTop,
  fallback = DASHBOARD_CANVAS_MIN_HEIGHT_FALLBACK,
  bottomGap = 0,
}: ResolveDashboardCanvasMinHeightArgs): number {
  if (!Number.isFinite(viewportHeight) || viewportHeight <= 0) return fallback;
  if (!Number.isFinite(canvasTop ?? NaN)) return fallback;
  const available = Math.ceil(viewportHeight - (canvasTop as number) - bottomGap);
  return Math.max(fallback, available);
}
