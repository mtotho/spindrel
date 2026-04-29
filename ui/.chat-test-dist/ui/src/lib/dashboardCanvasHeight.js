export const DASHBOARD_CANVAS_MIN_HEIGHT_FALLBACK = 240;
export function resolveDashboardCanvasMinHeight({ viewportHeight, canvasTop, fallback = DASHBOARD_CANVAS_MIN_HEIGHT_FALLBACK, bottomGap = 0, }) {
    if (!Number.isFinite(viewportHeight) || viewportHeight <= 0)
        return fallback;
    if (!Number.isFinite(canvasTop ?? NaN))
        return fallback;
    const available = Math.ceil(viewportHeight - canvasTop - bottomGap);
    return Math.max(fallback, available);
}
