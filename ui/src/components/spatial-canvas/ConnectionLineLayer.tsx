import { useMemo } from "react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";

/**
 * Toggleable layer that draws faint curved lines from each pinned widget
 * tile to its source channel tile (the channel from which the widget was
 * originally pinned). Helps answer "where did this widget come from"
 * visually without requiring a hover.
 *
 * Rendered inside the canvas's world-transformed div (sibling to tiles), so
 * pan/zoom apply for free. NOT projected through the P16 lens — endpoints
 * would drift from the tiles' rendered positions when the lens is engaged;
 * accepted v1 limitation.
 */

interface ConnectionLineLayerProps {
  nodes: SpatialNode[];
  hoveredNodeId: string | null;
  suppressedChannelIds?: Set<string>;
}

interface LinePair {
  id: string;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  highlighted: boolean;
}

export function ConnectionLineLayer({ nodes, hoveredNodeId, suppressedChannelIds }: ConnectionLineLayerProps) {
  const lines = useMemo<LinePair[]>(() => {
    const channelCenterById = new Map<string, { x: number; y: number }>();
    for (const n of nodes) {
      if (n.channel_id) {
        channelCenterById.set(n.channel_id, {
          x: n.world_x + n.world_w / 2,
          y: n.world_y + n.world_h / 2,
        });
      }
    }
    const out: LinePair[] = [];
    for (const n of nodes) {
      const sourceChannelId = n.pin?.source_channel_id;
      if (!sourceChannelId) continue;
      if (suppressedChannelIds?.has(sourceChannelId)) continue;
      const target = channelCenterById.get(sourceChannelId);
      if (!target) continue; // deleted/missing source channel — skip
      const fromX = n.world_x + n.world_w / 2;
      const fromY = n.world_y + n.world_h / 2;
      out.push({
        id: n.id,
        fromX,
        fromY,
        toX: target.x,
        toY: target.y,
        highlighted: hoveredNodeId === n.id,
      });
    }
    return out;
  }, [nodes, hoveredNodeId, suppressedChannelIds]);

  // Compute viewBox bounds large enough to cover all endpoints + a margin.
  // SVG sized to fit the world-rect of the lines; positioned absolutely at
  // the bounds origin so its internal coords match world coords.
  const bounds = useMemo(() => {
    if (lines.length === 0) return { x: 0, y: 0, w: 0, h: 0 };
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const l of lines) {
      minX = Math.min(minX, l.fromX, l.toX);
      minY = Math.min(minY, l.fromY, l.toY);
      maxX = Math.max(maxX, l.fromX, l.toX);
      maxY = Math.max(maxY, l.fromY, l.toY);
    }
    const margin = 200;
    return {
      x: minX - margin,
      y: minY - margin,
      w: (maxX - minX) + margin * 2,
      h: (maxY - minY) + margin * 2,
    };
  }, [lines]);

  if (lines.length === 0) return null;

  return (
    <div
      className="absolute pointer-events-none"
      style={{ left: bounds.x, top: bounds.y, width: bounds.w, height: bounds.h }}
      aria-hidden
    >
      <svg
        width={bounds.w}
        height={bounds.h}
        viewBox={`${bounds.x} ${bounds.y} ${bounds.w} ${bounds.h}`}
        style={{ overflow: "visible" }}
      >
        {lines.map((l) => {
          // Quadratic bezier with the control point offset perpendicular
          // to the chord — gives the line a gentle arc instead of a stick.
          const mx = (l.fromX + l.toX) / 2;
          const my = (l.fromY + l.toY) / 2;
          const dx = l.toX - l.fromX;
          const dy = l.toY - l.fromY;
          const len = Math.hypot(dx, dy) || 1;
          const offset = Math.min(80, len * 0.18);
          // Perpendicular direction (rotate dx,dy by 90°).
          const px = -dy / len;
          const py = dx / len;
          const cx = mx + px * offset;
          const cy = my + py * offset;
          const opacity = l.highlighted ? 0.55 : 0.15;
          const stroke = l.highlighted
            ? "rgb(var(--color-accent))"
            : "rgb(var(--color-text))";
          return (
            <path
              key={l.id}
              d={`M ${l.fromX} ${l.fromY} Q ${cx} ${cy} ${l.toX} ${l.toY}`}
              fill="none"
              stroke={stroke}
              strokeWidth={1.5}
              strokeOpacity={opacity}
              strokeDasharray="6 8"
              strokeLinecap="round"
            />
          );
        })}
      </svg>
    </div>
  );
}
