import { useMemo, type ReactNode } from "react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import { channelHue } from "./ChannelTile";

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
 * Positions in `position_history` are tile *origins* (top-left); we add
 * `world_w/2`, `world_h/2` per-entry to draw the line through tile centers.
 *
 * Color: stable per-node hue. Channels and bots share `channelHue(id)`
 * (same hashing function — bots get a distinct hue from their bot_id).
 * Widget trails fall back to a token-driven dim color since widgets only
 * move via tug.
 */

type Mode = "hover" | "all";

interface MovementHistoryLayerProps {
  nodes: SpatialNode[];
  mode: Mode;
  hoveredNodeId: string | null;
  /** Camera scale; used to keep stroke widths visually steady at any zoom. */
  scale: number;
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

function colorForNode(node: SpatialNode): string {
  if (node.channel_id) {
    return `hsl(${channelHue(node.channel_id)}, 55%, 58%)`;
  }
  if (node.bot_id) {
    // Reuse the same hash so bot trails have their own stable hue. Distinct
    // from channel hues because bot_ids are textual not UUIDs — different
    // entropy bucket — though collisions are visually fine (just a coincidence
    // of color, no semantic overlap).
    return `hsl(${channelHue(node.bot_id)}, 50%, 62%)`;
  }
  return "rgb(var(--color-text-dim))";
}

export function MovementHistoryLayer({
  nodes,
  mode,
  hoveredNodeId,
  scale,
}: MovementHistoryLayerProps) {
  const trails = useMemo<NodeTrail[]>(() => {
    const out: NodeTrail[] = [];
    for (const node of nodes) {
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
      out.push({
        nodeId: node.id,
        color: colorForNode(node),
        points,
        emphasized: mode === "hover" || isHovered,
      });
    }
    return out;
  }, [nodes, mode, hoveredNodeId]);

  if (trails.length === 0) return null;

  // Bounding rect for the SVG. Margin 80 world px so soft strokes near the
  // edges aren't clipped — same shape as MovementTraceLayer's sizing.
  const xs = trails.flatMap((t) => t.points.map((p) => p.x));
  const ys = trails.flatMap((t) => t.points.map((p) => p.y));
  const minX = Math.min(...xs) - 80;
  const minY = Math.min(...ys) - 80;
  const maxX = Math.max(...xs) + 80;
  const maxY = Math.max(...ys) + 80;

  // Stroke widths are authored in screen pixels so the line stays a steady
  // visual thickness across zooms; divide by `scale` to compensate for the
  // parent world transform.
  const strokeAtNewest = 2.4 / Math.max(scale, 0.001);
  const strokeAtOldest = 0.8 / Math.max(scale, 0.001);

  return (
    <svg
      className="absolute pointer-events-none overflow-visible"
      style={{ left: minX, top: minY, width: maxX - minX, height: maxY - minY }}
      aria-hidden
    >
      {trails.map((trail) => {
        const segments: ReactNode[] = [];
        // n points → n-1 segments. Index 0 connects history[0] → history[1];
        // last segment connects history[last] → current position. Newest
        // segment gets the highest opacity / stroke width.
        const segCount = trail.points.length - 1;
        if (segCount <= 0) return null;
        for (let i = 0; i < segCount; i++) {
          const t = segCount === 1 ? 1 : i / (segCount - 1); // 0 oldest → 1 newest
          const opacityLow = trail.emphasized ? 0.30 : 0.08;
          const opacityHigh = trail.emphasized ? 0.85 : 0.45;
          const opacity = opacityLow + (opacityHigh - opacityLow) * t;
          const stroke = strokeAtOldest + (strokeAtNewest - strokeAtOldest) * t;
          const a = trail.points[i];
          const b = trail.points[i + 1];
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
        return <g key={trail.nodeId}>{segments}</g>;
      })}
    </svg>
  );
}
