import { useMemo, type ReactNode } from "react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import { channelHue } from "./ChannelTile";
import {
  SVG_MAX_DIMENSION_PX,
  bboxOverlaps,
  intersectBbox,
  type WorldBbox,
} from "./spatialGeometry";

/**
 * Comet-tail trail per node. Reads `position_history` (server-pruned to
 * 72h / 30 entries) and renders a chained set of `<line>` segments from
 * each prior position to the next, with opacity + stroke-width interpolated
 * from oldest (faint, thin) to newest (strong, thick).
 *
 * Modes:
 *   - "off"   → render nothing (handled by SpatialCanvas: layer not mounted)
 *   - "hover" → only render the trail for `hoveredNodeId`; background trails
 *               stay hidden so 15+ tiles don't turn into spaghetti.
 *   - "all"   → render every node's trail at moderate opacity.
 *
 * Bots only. Channels and widgets only ever move because the user dragged
 * them; trails are an *agent autonomy* signal, so we gate on `node.bot_id`.
 *
 * Viewport clipping: the SVG width/height is the intersection of the trail
 * content bbox and the visible viewport (`viewportBbox`). Off-screen trails
 * are culled, and trail segments whose bounding box doesn't intersect the
 * viewport are skipped. Without this, deep zoom blew the iOS WebKit raster
 * buffer ceiling and white-screened the canvas.
 */

type Mode = "hover" | "all";

interface MovementHistoryLayerProps {
  nodes: SpatialNode[];
  mode: Mode;
  hoveredNodeId: string | null;
  /** Camera scale; used to keep stroke widths visually steady at any zoom. */
  scale: number;
  /** Visible world bbox + overdraw. When omitted, no clipping is applied
   *  (kept for tests / non-canvas callers). */
  viewportBbox?: WorldBbox;
}

interface TrailPoint {
  x: number;
  y: number;
}

interface NodeTrail {
  nodeId: string;
  color: string;
  points: TrailPoint[];
  emphasized: boolean;
}

function colorForBot(botId: string): string {
  return `hsl(${channelHue(botId)}, 50%, 62%)`;
}

function trailBbox(points: TrailPoint[]): WorldBbox {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  }
  return { minX, minY, maxX, maxY };
}

export function MovementHistoryLayer({
  nodes,
  mode,
  hoveredNodeId,
  scale,
  viewportBbox,
}: MovementHistoryLayerProps) {
  const trails = useMemo<NodeTrail[]>(() => {
    const out: NodeTrail[] = [];
    for (const node of nodes) {
      // Bots only — see file header.
      if (!node.bot_id) continue;
      const history = node.position_history ?? [];
      if (history.length === 0) continue;
      const isHovered = hoveredNodeId === node.id;
      if (mode === "hover" && !isHovered) continue;
      const cx = node.world_w / 2;
      const cy = node.world_h / 2;
      const points: TrailPoint[] = history.map((entry) => ({
        x: entry.x + cx,
        y: entry.y + cy,
      }));
      // Tip of the comet = current position.
      points.push({ x: node.world_x + cx, y: node.world_y + cy });

      // Cull: skip trails entirely off-screen.
      if (viewportBbox) {
        const tb = trailBbox(points);
        if (!bboxOverlaps(tb, viewportBbox)) continue;
      }

      out.push({
        nodeId: node.id,
        color: colorForBot(node.bot_id),
        points,
        emphasized: mode === "hover" || isHovered,
      });
    }
    return out;
  }, [nodes, mode, hoveredNodeId, viewportBbox]);

  if (trails.length === 0) return null;

  // Content bbox + 80px world margin so soft strokes at the edges don't clip.
  const xs = trails.flatMap((t) => t.points.map((p) => p.x));
  const ys = trails.flatMap((t) => t.points.map((p) => p.y));
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
  // Safety net against unexpectedly large bboxes — iOS WebKit fails roughly
  // ≥ 4096px in either axis. Hitting this clamp will visually clip trails
  // at the edge, which is preferable to a white-screen.
  const width = Math.min(drawBbox.maxX - drawBbox.minX, SVG_MAX_DIMENSION_PX);
  const height = Math.min(drawBbox.maxY - drawBbox.minY, SVG_MAX_DIMENSION_PX);

  // Stroke widths are authored in screen pixels so the line stays a steady
  // visual thickness across zooms; divide by `scale` to compensate for the
  // parent world transform.
  const strokeAtNewest = 2.4 / Math.max(scale, 0.001);
  const strokeAtOldest = 0.8 / Math.max(scale, 0.001);

  return (
    <svg
      className="absolute pointer-events-none overflow-visible"
      style={{ left: minX, top: minY, width, height }}
      aria-hidden
    >
      {trails.map((trail) => {
        const segments: ReactNode[] = [];
        const segCount = trail.points.length - 1;
        if (segCount <= 0) return null;
        for (let i = 0; i < segCount; i++) {
          const a = trail.points[i];
          const b = trail.points[i + 1];
          // Per-segment cull — skip segments that don't cross the viewport.
          if (viewportBbox) {
            const segBbox: WorldBbox = {
              minX: Math.min(a.x, b.x),
              minY: Math.min(a.y, b.y),
              maxX: Math.max(a.x, b.x),
              maxY: Math.max(a.y, b.y),
            };
            if (!bboxOverlaps(segBbox, viewportBbox)) continue;
          }
          const t = segCount === 1 ? 1 : i / (segCount - 1); // 0 oldest → 1 newest
          const opacityLow = trail.emphasized ? 0.30 : 0.08;
          const opacityHigh = trail.emphasized ? 0.85 : 0.45;
          const opacity = opacityLow + (opacityHigh - opacityLow) * t;
          const stroke = strokeAtOldest + (strokeAtNewest - strokeAtOldest) * t;
          segments.push(
            <line
              key={i}
              x1={a.x - minX}
              y1={a.y - minY}
              x2={b.x - minX}
              y2={b.y - minY}
              stroke={trail.color}
              strokeWidth={stroke}
              strokeOpacity={opacity}
              strokeLinecap="round"
            />,
          );
        }
        if (segments.length === 0) return null;
        return <g key={trail.nodeId}>{segments}</g>;
      })}
    </svg>
  );
}
