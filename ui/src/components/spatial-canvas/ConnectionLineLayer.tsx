import { useMemo } from "react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import {
  SVG_MAX_DIMENSION_PX,
  bboxOverlaps,
  intersectBbox,
  type WorldBbox,
} from "./spatialGeometry";

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
 *
 * Viewport clipping: SVG width/height is the intersection of the line
 * content bbox and the visible viewport. Lines whose endpoints AND chord
 * miss the viewport are culled. Without this, deep zoom blew the iOS
 * WebKit raster ceiling.
 */

interface ConnectionLineLayerProps {
  nodes: SpatialNode[];
  hoveredNodeId: string | null;
  suppressedChannelIds?: Set<string>;
  /** Visible world bbox + overdraw. Optional for tests / non-canvas use. */
  viewportBbox?: WorldBbox;
}

interface LinePair {
  id: string;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  highlighted: boolean;
}

function lineBbox(l: LinePair): WorldBbox {
  return {
    minX: Math.min(l.fromX, l.toX),
    minY: Math.min(l.fromY, l.toY),
    maxX: Math.max(l.fromX, l.toX),
    maxY: Math.max(l.fromY, l.toY),
  };
}

export function ConnectionLineLayer({
  nodes,
  hoveredNodeId,
  suppressedChannelIds,
  viewportBbox,
}: ConnectionLineLayerProps) {
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
      const pair: LinePair = {
        id: n.id,
        fromX,
        fromY,
        toX: target.x,
        toY: target.y,
        highlighted: hoveredNodeId === n.id,
      };
      // Cull lines whose chord bbox is entirely off-screen. A bezier with
      // perpendicular control point can bow up to ~80 world-px out of the
      // chord bbox; we expand slightly before testing.
      if (viewportBbox) {
        const lb = lineBbox(pair);
        const padded: WorldBbox = {
          minX: lb.minX - 100,
          minY: lb.minY - 100,
          maxX: lb.maxX + 100,
          maxY: lb.maxY + 100,
        };
        if (!bboxOverlaps(padded, viewportBbox)) continue;
      }
      out.push(pair);
    }
    return out;
  }, [nodes, hoveredNodeId, suppressedChannelIds, viewportBbox]);

  // SVG bbox sized to the kept lines. 200px content margin keeps the bezier
  // arc inside the viewBox; viewport clipping then trims outer edges.
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
    const contentBbox: WorldBbox = {
      minX: minX - margin,
      minY: minY - margin,
      maxX: maxX + margin,
      maxY: maxY + margin,
    };
    const drawBbox = viewportBbox ? intersectBbox(contentBbox, viewportBbox) : contentBbox;
    if (!drawBbox) return { x: 0, y: 0, w: 0, h: 0 };
    return {
      x: drawBbox.minX,
      y: drawBbox.minY,
      w: Math.min(drawBbox.maxX - drawBbox.minX, SVG_MAX_DIMENSION_PX),
      h: Math.min(drawBbox.maxY - drawBbox.minY, SVG_MAX_DIMENSION_PX),
    };
  }, [lines, viewportBbox]);

  if (lines.length === 0 || bounds.w === 0 || bounds.h === 0) return null;

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
