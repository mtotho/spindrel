import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import type { Camera } from "./spatialGeometry";

export interface WidgetOverviewCluster {
  id: string;
  nodes: SpatialNode[];
  worldX: number;
  worldY: number;
}

export function buildWidgetOverviewClusters({
  nodes,
  camera,
  excludedNodeIds,
  enabled,
  radius = 92,
}: {
  nodes: SpatialNode[];
  camera: Camera;
  excludedNodeIds: Set<string>;
  enabled: boolean;
  radius?: number;
}): WidgetOverviewCluster[] {
  if (!enabled) return [];
  const candidates = nodes
    .filter((node) => node.pin && !excludedNodeIds.has(node.id))
    .map((node) => {
      const cx = node.world_x + node.world_w / 2;
      const cy = node.world_y + node.world_h / 2;
      return {
        node,
        worldX: cx,
        worldY: cy,
        screenX: camera.x + cx * camera.scale,
        screenY: camera.y + cy * camera.scale,
      };
    })
    .sort((a, b) => a.node.id.localeCompare(b.node.id));
  const claimed = new Set<string>();
  const clusters: WidgetOverviewCluster[] = [];
  for (const seed of candidates) {
    if (claimed.has(seed.node.id)) continue;
    const members = candidates.filter((candidate) => {
      if (claimed.has(candidate.node.id)) return false;
      const dx = candidate.screenX - seed.screenX;
      const dy = candidate.screenY - seed.screenY;
      return Math.hypot(dx, dy) <= radius;
    });
    for (const member of members) claimed.add(member.node.id);
    const worldX = members.reduce((sum, member) => sum + member.worldX, 0) / members.length;
    const worldY = members.reduce((sum, member) => sum + member.worldY, 0) / members.length;
    clusters.push({
      id: `widget-cluster:${members.map((member) => member.node.id).join(":")}`,
      nodes: members.map((member) => member.node),
      worldX,
      worldY,
    });
  }
  return clusters;
}
