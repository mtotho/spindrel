import { useMemo } from "react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import type { Channel } from "../../types/api";
import {
  SVG_MAX_DIMENSION_PX,
  bboxOverlaps,
  intersectBbox,
  type WorldBbox,
} from "./spatialGeometry";

interface ProjectOrbitLayerProps {
  nodes: SpatialNode[];
  channelsById: Map<string, Channel>;
  zoom?: number;
  viewportBbox?: WorldBbox;
  connectionsEnabled?: boolean;
}

interface OrbitShape {
  id: string;
  projectId: string;
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  outerRx: number;
  outerRy: number;
  hue: number;
  tilt: number;
}

interface Tether {
  id: string;
  projectId: string;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  hue: number;
}

function stableHue(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return h % 360;
}

function lineBbox(line: Tether): WorldBbox {
  const pad = Math.max(80, Math.hypot(line.toX - line.fromX, line.toY - line.fromY) * 0.18);
  return {
    minX: Math.min(line.fromX, line.toX) - pad,
    minY: Math.min(line.fromY, line.toY) - pad,
    maxX: Math.max(line.fromX, line.toX) + pad,
    maxY: Math.max(line.fromY, line.toY) + pad,
  };
}

export function ProjectOrbitLayer({ nodes, channelsById, zoom = 1, viewportBbox, connectionsEnabled = true }: ProjectOrbitLayerProps) {
  const { orbits, tethers } = useMemo(() => {
    const channelNodes = nodes.filter((node) => node.channel_id);
    const shapes: OrbitShape[] = [];
    const lines: Tether[] = [];

    for (const projectNode of nodes) {
      if (!projectNode.project_id) continue;
      const projectId = projectNode.project_id;
      const members = channelNodes.filter((node) => {
        if (!node.channel_id) return false;
        return channelsById.get(node.channel_id)?.project_id === projectId;
      });
      if (!members.length) continue;

      const cx = projectNode.world_x + projectNode.world_w / 2;
      const cy = projectNode.world_y + projectNode.world_h / 2;
      const hue = stableHue(projectId);
      const base = Math.max(projectNode.world_w, projectNode.world_h);
      const rx = Math.max(210, Math.min(320, base * 0.58 + members.length * 14));
      const ry = Math.max(118, Math.min(190, projectNode.world_h * 0.44 + members.length * 9));
      const outerRx = rx + 38;
      const outerRy = ry + 22;
      const tilt = -10 + (hue % 20);
      shapes.push({ id: `project-orbit:${projectId}`, projectId, cx, cy, rx, ry, outerRx, outerRy, hue, tilt });

      if (connectionsEnabled && zoom >= 0.42) {
        for (const member of members) {
          lines.push({
            id: `project-tether:${projectId}:${member.id}`,
            projectId,
            fromX: cx,
            fromY: cy,
            toX: member.world_x + member.world_w / 2,
            toY: member.world_y + member.world_h / 2,
            hue,
          });
        }
      }
    }
    return { orbits: shapes, tethers: lines };
  }, [channelsById, connectionsEnabled, nodes, zoom]);

  const visibleOrbits = orbits.filter((orbit) => {
    if (!viewportBbox) return true;
    return bboxOverlaps(
      { minX: orbit.cx - orbit.rx, minY: orbit.cy - orbit.ry, maxX: orbit.cx + orbit.rx, maxY: orbit.cy + orbit.ry },
      viewportBbox,
    );
  });
  const visibleTethers = tethers.filter((line) => {
    if (!viewportBbox) return true;
    const box = lineBbox(line);
    return bboxOverlaps(box, viewportBbox);
  });
  if (!visibleOrbits.length && !visibleTethers.length) return null;

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const orbit of visibleOrbits) {
    minX = Math.min(minX, orbit.cx - orbit.outerRx);
    minY = Math.min(minY, orbit.cy - orbit.outerRy);
    maxX = Math.max(maxX, orbit.cx + orbit.outerRx);
    maxY = Math.max(maxY, orbit.cy + orbit.outerRy);
  }
  for (const line of visibleTethers) {
    minX = Math.min(minX, line.fromX, line.toX);
    minY = Math.min(minY, line.fromY, line.toY);
    maxX = Math.max(maxX, line.fromX, line.toX);
    maxY = Math.max(maxY, line.fromY, line.toY);
  }
  const content = { minX: minX - 80, minY: minY - 80, maxX: maxX + 80, maxY: maxY + 80 };
  const draw = viewportBbox ? intersectBbox(content, viewportBbox) : content;
  if (!draw) return null;
  const width = Math.min(draw.maxX - draw.minX, SVG_MAX_DIMENSION_PX);
  const height = Math.min(draw.maxY - draw.minY, SVG_MAX_DIMENSION_PX);

  return (
    <div
      className="absolute pointer-events-none z-[2]"
      style={{ left: draw.minX, top: draw.minY, width, height }}
      aria-hidden
    >
      <svg width={width} height={height} viewBox={`${draw.minX} ${draw.minY} ${width} ${height}`} style={{ overflow: "visible" }}>
        {visibleOrbits.map((orbit) => (
          <g key={orbit.id} data-testid="project-orbit">
            <ellipse
              cx={orbit.cx}
              cy={orbit.cy}
              rx={orbit.outerRx}
              ry={orbit.outerRy}
              fill={`hsla(${orbit.hue}, 72%, 66%, 0.025)`}
              stroke={`hsl(${orbit.hue}, 62%, 66%)`}
              strokeOpacity={0.09}
              strokeWidth={1.4}
              strokeDasharray="6 16"
              transform={`rotate(${orbit.tilt.toFixed(1)} ${orbit.cx} ${orbit.cy})`}
            />
            <ellipse
              cx={orbit.cx}
              cy={orbit.cy}
              rx={orbit.rx}
              ry={orbit.ry}
              fill="none"
              stroke={`hsl(${orbit.hue}, 66%, 70%)`}
              strokeOpacity={0.16}
              strokeWidth={1.8}
              strokeDasharray="2 10"
              strokeLinecap="round"
              transform={`rotate(${(orbit.tilt - 7).toFixed(1)} ${orbit.cx} ${orbit.cy})`}
            />
          </g>
        ))}
        {visibleTethers.map((line) => (
          <path
            key={line.id}
            data-testid="project-orbit-tether"
            d={curvedTetherPath(line)}
            stroke={`hsl(${line.hue}, 70%, 70%)`}
            strokeOpacity={0.13}
            strokeWidth={1.25}
            strokeDasharray="3 11"
            strokeLinecap="round"
            fill="none"
          />
        ))}
      </svg>
    </div>
  );
}

function curvedTetherPath(line: Tether): string {
  const dx = line.toX - line.fromX;
  const dy = line.toY - line.fromY;
  const bend = Math.min(130, Math.max(46, Math.hypot(dx, dy) * 0.14));
  const nx = -dy / Math.max(1, Math.hypot(dx, dy));
  const ny = dx / Math.max(1, Math.hypot(dx, dy));
  const c1x = line.fromX + dx * 0.34 + nx * bend;
  const c1y = line.fromY + dy * 0.34 + ny * bend;
  const c2x = line.fromX + dx * 0.72 + nx * bend * 0.56;
  const c2y = line.fromY + dy * 0.72 + ny * bend * 0.56;
  return `M ${line.fromX.toFixed(2)} ${line.fromY.toFixed(2)} C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${line.toX.toFixed(2)} ${line.toY.toFixed(2)}`;
}
