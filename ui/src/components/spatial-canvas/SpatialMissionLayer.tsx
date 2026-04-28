import { Bot, Route } from "lucide-react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import type { WorkspaceMission } from "../../api/hooks/useWorkspaceMissions";
import type { WorldBbox } from "./spatialGeometry";

interface MissionAnchor {
  mission: WorkspaceMission;
  x: number;
  y: number;
  botX?: number;
  botY?: number;
}

function overlaps(x: number, y: number, viewport?: WorldBbox | null): boolean {
  if (!viewport) return true;
  return x >= viewport.minX - 220 && x <= viewport.maxX + 220 && y >= viewport.minY - 220 && y <= viewport.maxY + 220;
}

export function SpatialMissionLayer({
  missions,
  nodes,
  scale,
  viewportBbox,
  onOpenMissionControl,
}: {
  missions: WorkspaceMission[];
  nodes: SpatialNode[];
  scale: number;
  viewportBbox?: WorldBbox | null;
  onOpenMissionControl: () => void;
}) {
  const channelNodes = new Map(nodes.filter((node) => node.channel_id).map((node) => [node.channel_id!, node]));
  const botNodes = new Map(nodes.filter((node) => node.bot_id).map((node) => [node.bot_id!, node]));
  const anchors: MissionAnchor[] = [];
  for (const mission of missions) {
    if (mission.status !== "active" && mission.status !== "paused") continue;
    const channelNode = mission.channel_id ? channelNodes.get(mission.channel_id) : undefined;
    const primaryBot = mission.assignments[0]?.bot_id;
    const botNode = primaryBot ? botNodes.get(primaryBot) : undefined;
    const x = channelNode
      ? channelNode.world_x + channelNode.world_w + 34
      : botNode
        ? botNode.world_x + botNode.world_w + 46
        : 0;
    const y = channelNode
      ? channelNode.world_y + 12 + anchors.length % 3 * 28
      : botNode
        ? botNode.world_y - 18
        : 0;
    if (!channelNode && !botNode) continue;
    if (!overlaps(x, y, viewportBbox)) continue;
    anchors.push({
      mission,
      x,
      y,
      botX: botNode ? botNode.world_x + botNode.world_w / 2 : undefined,
      botY: botNode ? botNode.world_y + botNode.world_h / 2 : undefined,
    });
  }
  const strokeWidth = Math.max(1, 1.2 / Math.max(scale, 0.1));
  return (
    <div className="pointer-events-none absolute left-0 top-0 z-[28]">
      <svg className="absolute left-0 top-0 overflow-visible" width={1} height={1} aria-hidden>
        {anchors.map((anchor) => {
          if (anchor.botX == null || anchor.botY == null) return null;
          return (
            <line
              key={`${anchor.mission.id}-line`}
              x1={anchor.botX}
              y1={anchor.botY}
              x2={anchor.x}
              y2={anchor.y + 14}
              stroke="rgb(var(--color-accent) / 0.42)"
              strokeDasharray={`${6 / Math.max(scale, 0.1)} ${8 / Math.max(scale, 0.1)}`}
              strokeWidth={strokeWidth}
            />
          );
        })}
      </svg>
      {anchors.map((anchor) => (
        <button
          key={anchor.mission.id}
          type="button"
          className="pointer-events-auto absolute flex min-w-[170px] max-w-[230px] items-center gap-2 rounded-md bg-surface-raised/90 px-2.5 py-2 text-left text-xs text-text shadow-none ring-1 ring-surface-border/70 backdrop-blur hover:bg-surface-overlay"
          style={{
            left: anchor.x,
            top: anchor.y,
            transform: `scale(${Math.max(0.78, Math.min(1.05, 1 / Math.max(scale, 0.9)))})`,
            transformOrigin: "left center",
          }}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onOpenMissionControl();
          }}
          title={anchor.mission.directive}
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent/[0.08] text-accent">
            {anchor.mission.scope === "channel" ? <Route size={14} /> : <Bot size={14} />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-semibold">{anchor.mission.title}</span>
            <span className="mt-0.5 block truncate text-[10px] text-text-dim">
              {anchor.mission.assignments[0]?.bot_name ?? "unassigned"} · {anchor.mission.recurrence ?? "manual"}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}
