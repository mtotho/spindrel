export type EdgeBeaconSide = "top" | "right" | "bottom" | "left";

export interface EdgeBeaconPosition {
  x: number;
  y: number;
  angleDeg: number;
  side: EdgeBeaconSide;
  distancePx: number;
  offscreenDistancePx: number;
}

export function computeEdgeBeaconPosition(
  target: { x: number; y: number },
  viewport: { w: number; h: number },
  padding = 42,
  visibleInset = 48,
  maxOffscreenDistance = 280,
): EdgeBeaconPosition | null {
  if (viewport.w <= 0 || viewport.h <= 0) return null;
  if (
    target.x >= -visibleInset &&
    target.x <= viewport.w + visibleInset &&
    target.y >= -visibleInset &&
    target.y <= viewport.h + visibleInset
  ) {
    return null;
  }

  const offscreenDx =
    target.x < 0 ? -target.x : target.x > viewport.w ? target.x - viewport.w : 0;
  const offscreenDy =
    target.y < 0 ? -target.y : target.y > viewport.h ? target.y - viewport.h : 0;
  const offscreenDistance = Math.hypot(offscreenDx, offscreenDy);
  if (offscreenDistance > maxOffscreenDistance) return null;

  const cx = viewport.w / 2;
  const cy = viewport.h / 2;
  const dx = target.x - cx;
  const dy = target.y - cy;
  if (Math.abs(dx) < 1e-6 && Math.abs(dy) < 1e-6) return null;

  const candidates: Array<{ t: number; side: EdgeBeaconSide }> = [];
  if (dx > 0) candidates.push({ t: (viewport.w - padding - cx) / dx, side: "right" });
  if (dx < 0) candidates.push({ t: (padding - cx) / dx, side: "left" });
  if (dy > 0) candidates.push({ t: (viewport.h - padding - cy) / dy, side: "bottom" });
  if (dy < 0) candidates.push({ t: (padding - cy) / dy, side: "top" });

  const hit = candidates
    .filter((c) => Number.isFinite(c.t) && c.t > 0)
    .sort((a, b) => a.t - b.t)[0];
  if (!hit) return null;

  const x = Math.min(viewport.w - padding, Math.max(padding, cx + dx * hit.t));
  const y = Math.min(viewport.h - padding, Math.max(padding, cy + dy * hit.t));
  return {
    x,
    y,
    side: hit.side,
    angleDeg: Math.atan2(dy, dx) * (180 / Math.PI),
    distancePx: Math.hypot(dx, dy),
    offscreenDistancePx: offscreenDistance,
  };
}
