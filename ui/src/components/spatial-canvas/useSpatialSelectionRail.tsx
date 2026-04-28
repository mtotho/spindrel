import { useMemo } from "react";
import {
  Locate,
  MoreHorizontal,
  Radar,
  ZoomIn,
} from "lucide-react";
import type { SpatialContextMenuItem } from "./SpatialContextMenu";
import type { SpatialSelectionAction } from "./SpatialSelectionRail";

type UseSpatialSelectionRailArgs = Record<string, any>;

export function useSpatialSelectionRail(args: UseSpatialSelectionRailArgs) {
  const {
    selectedSpatialObject,
    draggingNodeId,
    diving,
    camera,
    setContextMenu,
    channelClusters,
    flyToWorldBounds,
    diveToChannel,
  } = args;

  return useMemo(() => {
    if (!selectedSpatialObject || draggingNodeId || diving) return null;

    const toScreen = (worldX: number, worldY: number) => ({
      x: camera.x + worldX * camera.scale,
      y: camera.y + worldY * camera.scale,
    });
    const moreAction = (
      items: SpatialContextMenuItem[],
    ): SpatialSelectionAction => ({
      id: "more",
      label: "More actions",
      icon: MoreHorizontal,
      onSelect: (event) => {
        event.stopPropagation();
        setContextMenu({
          screenX: event.clientX,
          screenY: event.clientY,
          items,
        });
      },
    });

    if (selectedSpatialObject.kind === "channel-cluster") {
      const cluster = channelClusters.find((entry: any) => entry.id === selectedSpatialObject.id);
      if (!cluster) return null;
      const node = cluster.winner.node;
      const channel = cluster.winner.channel;
      const anchor = toScreen(node.world_x + node.world_w / 2, node.world_y - 12);
      const focus = () => flyToWorldBounds(cluster.worldBounds);
      const dive = () =>
        diveToChannel(channel.id, {
          x: node.world_x,
          y: node.world_y,
          w: node.world_w,
          h: node.world_h,
        });
      return {
        x: anchor.x,
        y: anchor.y,
        label: `${channel.display_name || channel.name} cluster`,
        meta: `${cluster.members.length} channels`,
        leading: <Radar className="h-4 w-4" />,
        actions: [
          { id: "focus", label: "Focus cluster", icon: Locate, onSelect: (event) => { event.stopPropagation(); focus(); } },
          { id: "dive", label: "Dive into winner", icon: ZoomIn, onSelect: (event) => { event.stopPropagation(); dive(); } },
          moreAction([
            { label: "Fly to cluster members", icon: <Locate size={14} />, onClick: focus },
            { label: `Dive into #${channel.name}`, icon: <ZoomIn size={14} />, onClick: dive },
          ]),
        ] satisfies SpatialSelectionAction[],
      };
    }

    // Single channels, bots, widgets, and landmarks now use Starboard Map Brief
    // as the one selected-object surface. The floating rail is reserved for
    // aggregate canvas affordances like clusters, where there is no single
    // durable object inspector.
    return null;
  }, [
    selectedSpatialObject,
    draggingNodeId,
    diving,
    camera.x,
    camera.y,
    camera.scale,
    channelClusters,
    flyToWorldBounds,
    diveToChannel,
    setContextMenu,
  ]);
}
