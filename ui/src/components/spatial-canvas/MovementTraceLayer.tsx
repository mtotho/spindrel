import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import {
  intersectBbox,
  SVG_MAX_DIMENSION_PX,
  type WorldBbox,
} from "./spatialGeometry";

export function MovementTraceLayer({ nodes, viewportBbox }: { nodes: SpatialNode[]; viewportBbox?: WorldBbox }) {
  const now = Date.now();
  const traces = nodes
    .map((node) => {
      const movement = node.last_movement;
      if (!movement?.from || !movement?.to || !movement.created_at) return null;
      const created = Date.parse(movement.created_at);
      if (!Number.isFinite(created)) return null;
      const age = now - created;
      const expiresAt = movement.expires_at ? Date.parse(movement.expires_at) : NaN;
      const ttlMs = Number.isFinite(expiresAt)
        ? expiresAt - created
        : Math.max(1, movement.ttl_minutes ?? 30) * 60_000;
      if (ttlMs <= 0 || age < 0 || age > ttlMs) return null;
      const opacity = Math.max(0.18, 1 - age / ttlMs);
      const fromX = movement.from.x + node.world_w / 2;
      const fromY = movement.from.y + node.world_h / 2;
      const toX = movement.to.x + node.world_w / 2;
      const toY = movement.to.y + node.world_h / 2;
      if (viewportBbox) {
        const haloR = Math.max(node.world_w, node.world_h) * 0.7;
        const tb: WorldBbox = {
          minX: Math.min(fromX, toX) - haloR,
          minY: Math.min(fromY, toY) - haloR,
          maxX: Math.max(fromX, toX) + haloR,
          maxY: Math.max(fromY, toY) + haloR,
        };
        if (tb.minX > viewportBbox.maxX || tb.maxX < viewportBbox.minX
            || tb.minY > viewportBbox.maxY || tb.maxY < viewportBbox.minY) {
          return null;
        }
      }
      return { node, fromX, fromY, toX, toY, opacity };
    })
    .filter(Boolean) as Array<{
      node: SpatialNode;
      fromX: number;
      fromY: number;
      toX: number;
      toY: number;
      opacity: number;
    }>;
  if (traces.length === 0) return null;
  const xs = traces.flatMap((t) => [t.fromX, t.toX]);
  const ys = traces.flatMap((t) => [t.fromY, t.toY]);
  const contentBbox: WorldBbox = {
    minX: Math.min(...xs) - 80,
    minY: Math.min(...ys) - 80,
    maxX: Math.max(...xs) + 80,
    maxY: Math.max(...ys) + 80,
  };
  const drawBbox = viewportBbox ? intersectBbox(contentBbox, viewportBbox) : contentBbox;
  if (!drawBbox) return null;
  const minX = drawBbox.minX;
  const minY = drawBbox.minY;
  const width = Math.min(drawBbox.maxX - drawBbox.minX, SVG_MAX_DIMENSION_PX);
  const height = Math.min(drawBbox.maxY - drawBbox.minY, SVG_MAX_DIMENSION_PX);
  return (
    <svg
      className="absolute pointer-events-none overflow-visible"
      style={{ left: minX, top: minY, width, height }}
      aria-hidden
    >
      <defs>
        <marker
          id="spatial-move-arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="rgb(var(--color-accent))" />
        </marker>
      </defs>
      {traces.map((t) => (
        <g key={t.node.id} opacity={t.opacity}>
          <line
            x1={t.fromX - minX}
            y1={t.fromY - minY}
            x2={t.toX - minX}
            y2={t.toY - minY}
            stroke="rgb(var(--color-accent))"
            strokeWidth={2}
            strokeDasharray="6 5"
            markerEnd="url(#spatial-move-arrow)"
          />
          <circle
            cx={t.toX - minX}
            cy={t.toY - minY}
            r={Math.max(t.node.world_w, t.node.world_h) * 0.7}
            fill="none"
            stroke="rgb(var(--color-accent))"
            strokeWidth={2}
            strokeOpacity={0.35}
          />
        </g>
      ))}
    </svg>
  );
}
