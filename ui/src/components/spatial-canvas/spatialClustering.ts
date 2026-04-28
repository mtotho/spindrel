import type { Channel } from "../../types/api";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import type { Camera } from "./spatialGeometry";

export const CHANNEL_CLUSTER_ENTER_SCALE = 0.22;
export const CHANNEL_CLUSTER_EXIT_SCALE = 0.26;
export const CHANNEL_CLUSTER_FOCUS_SCALE = CHANNEL_CLUSTER_EXIT_SCALE + 0.05;
export const CHANNEL_CLUSTER_SCREEN_RADIUS = 92;

export interface ChannelActivityScore {
  tokens: number;
  calls: number;
  recency: number;
}

export interface ChannelClusterMember {
  node: SpatialNode;
  channel: Channel;
  screenX: number;
  screenY: number;
  score: ChannelActivityScore;
}

export interface ChannelCluster {
  id: string;
  winner: ChannelClusterMember;
  members: ChannelClusterMember[];
  hiddenMembers: ChannelClusterMember[];
  worldBounds: { x: number; y: number; w: number; h: number };
  totalTokens: number;
}

function channelRecency(channel: Channel): number {
  const raw = channel.last_message_at ?? channel.updated_at ?? channel.created_at;
  const ts = raw ? new Date(raw).getTime() : 0;
  return Number.isFinite(ts) ? ts : 0;
}

function compareMembers(a: ChannelClusterMember, b: ChannelClusterMember): number {
  const tokenDelta = b.score.tokens - a.score.tokens;
  if (tokenDelta !== 0) return tokenDelta;
  const recencyDelta = b.score.recency - a.score.recency;
  if (recencyDelta !== 0) return recencyDelta;
  return a.channel.id.localeCompare(b.channel.id);
}

function worldBoundsFor(members: ChannelClusterMember[]) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const member of members) {
    const n = member.node;
    minX = Math.min(minX, n.world_x);
    minY = Math.min(minY, n.world_y);
    maxX = Math.max(maxX, n.world_x + n.world_w);
    maxY = Math.max(maxY, n.world_y + n.world_h);
  }
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
}

export function buildChannelClusters({
  nodes,
  channelsById,
  activityByChannelId,
  camera,
  enabled,
  radius = CHANNEL_CLUSTER_SCREEN_RADIUS,
}: {
  nodes: SpatialNode[];
  channelsById: Map<string, Channel>;
  activityByChannelId: Map<string, Pick<ChannelActivityScore, "tokens" | "calls">>;
  camera: Camera;
  enabled: boolean;
  radius?: number;
}): ChannelCluster[] {
  if (!enabled) return [];

  const candidates: ChannelClusterMember[] = [];
  for (const node of nodes) {
    if (!node.channel_id) continue;
    const channel = channelsById.get(node.channel_id);
    if (!channel) continue;
    const cx = node.world_x + node.world_w / 2;
    const cy = node.world_y + node.world_h / 2;
    const activity = activityByChannelId.get(channel.id);
    candidates.push({
      node,
      channel,
      screenX: camera.x + cx * camera.scale,
      screenY: camera.y + cy * camera.scale,
      score: {
        tokens: activity?.tokens ?? 0,
        calls: activity?.calls ?? 0,
        recency: channelRecency(channel),
      },
    });
  }

  const ordered = [...candidates].sort(compareMembers);
  const claimed = new Set<string>();
  const clusters: ChannelCluster[] = [];

  for (const seed of ordered) {
    if (claimed.has(seed.node.id)) continue;
    const members = ordered
      .filter((candidate) => {
        if (claimed.has(candidate.node.id)) return false;
        const dx = candidate.screenX - seed.screenX;
        const dy = candidate.screenY - seed.screenY;
        return Math.hypot(dx, dy) <= radius;
      })
      .sort(compareMembers);

    if (members.length < 2) continue;

    for (const member of members) claimed.add(member.node.id);
    const winner = members[0];
    clusters.push({
      id: `cluster:${members.map((m) => m.channel.id).sort().join(":")}`,
      winner,
      members,
      hiddenMembers: members.slice(1),
      worldBounds: worldBoundsFor(members),
      totalTokens: members.reduce((sum, member) => sum + member.score.tokens, 0),
    });
  }

  return clusters;
}

export function clusterSuppressedNodeIds(clusters: ChannelCluster[]): Set<string> {
  const out = new Set<string>();
  for (const cluster of clusters) {
    for (const member of cluster.members) out.add(member.node.id);
  }
  return out;
}

export function clusterSuppressedChannelIds(clusters: ChannelCluster[]): Set<string> {
  const out = new Set<string>();
  for (const cluster of clusters) {
    for (const member of cluster.members) out.add(member.channel.id);
  }
  return out;
}
