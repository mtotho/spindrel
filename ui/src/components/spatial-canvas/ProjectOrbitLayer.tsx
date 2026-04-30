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
  hue: number;
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
  return {
    minX: Math.min(line.fromX, line.toX),
    minY: Math.min(line.fromY, line.toY),
    maxX: Math.max(line.fromX, line.toX),
    maxY: Math.max(line.fromY, line.toY),
  };
}

export function ProjectOrbitLayer({ nodes, channelsById, viewportBbox, connectionsEnabled = true }: ProjectOrbitLayerProps) {
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
      const far = members.reduce((max, node) => {
        const nx = node.world_x + node.world_w / 2;
        const ny = node.world_y + node.world_h / 2;
        return Math.max(max, Math.hypot(nx - cx, ny - cy));
      }, Math.max(projectNode.world_w, projectNode.world_h) * 0.45);
      const rx = Math.max(projectNode.world_w * 0.78, far + 90);
      const ry = Math.max(projectNode.world_h * 0.72, far * 0.56 + 72);
      shapes.push({ id: `project-orbit:${projectId}`, projectId, cx, cy, rx, ry, hue });

      if (connectionsEnabled) {
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
  }, [channelsById, connectionsEnabled, nodes]);

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
    minX = Math.min(minX, orbit.cx - orbit.rx);
    minY = Math.min(minY, orbit.cy - orbit.ry);
    maxX = Math.max(maxX, orbit.cx + orbit.rx);
    maxY = Math.max(maxY, orbit.cy + orbit.ry);
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
          <ellipse
            key={orbit.id}
            data-testid="project-orbit"
            cx={orbit.cx}
            cy={orbit.cy}
            rx={orbit.rx}
            ry={orbit.ry}
            fill="none"
            stroke={`hsl(${orbit.hue}, 66%, 68%)`}
            strokeOpacity={0.2}
            strokeWidth={2}
            strokeDasharray="10 14"
          />
        ))}
        {visibleTethers.map((line) => (
          <line
            key={line.id}
            data-testid="project-orbit-tether"
            x1={line.fromX}
            y1={line.fromY}
            x2={line.toX}
            y2={line.toY}
            stroke={`hsl(${line.hue}, 70%, 70%)`}
            strokeOpacity={0.18}
            strokeWidth={1.25}
            strokeDasharray="5 10"
            strokeLinecap="round"
          />
        ))}
      </svg>
    </div>
  );
}
