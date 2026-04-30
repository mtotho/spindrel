import { useCallback, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ExternalLink,
  Footprints,
  Home,
  Link2,
  Locate,
  Maximize2,
  MessageCircle,
  Move,
  Plus,
  Settings,
  Trash2,
  ZoomIn,
} from "lucide-react";
import { widgetPinHref } from "../../lib/hubRoutes";
import { resolveChannelEntryHref } from "../../lib/channelNavigation";
import { useUIStore } from "../../stores/ui";
import type { UnreadStateResponse } from "../../api/hooks/useUnread";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import type { SpatialContextMenuItem } from "./SpatialContextMenu";

type UseSpatialContextMenuArgs = Record<string, any>;

export function useSpatialContextMenu(args: UseSpatialContextMenuArgs) {
  const {
    diving,
    nodes,
    pointerToWorld,
    channelClusters,
    flyToWorldBounds,
    diveToChannel,
    channelsById,
    flyToChannel,
    setOpenBotChat,
    deleteNode,
    navigate,
    canvasBackState,
    updateNode,
    channelForBot,
    setPinPositionOverride,
    openStarboardLaunch,
    scheduleCamera,
    defaultCamera,
    fitAllNodes,
    trailsMode,
    cycleTrailsMode,
    connectionsEnabled,
    setConnectionsEnabled,
    setContextMenu,
  } = args;
  const recentPages = useUIStore((s) => s.recentPages);
  const queryClient = useQueryClient();
  const channelHref = useCallback((channelId: string) => {
    const unreadState = queryClient.getQueryData<UnreadStateResponse>(["unread-state"]);
    return resolveChannelEntryHref({
      channelId,
      recentPages,
      unreadStates: unreadState?.states,
    });
  }, [queryClient, recentPages]);

  return useCallback(
    (e: ReactPointerEvent<HTMLDivElement> | ReactMouseEvent<HTMLDivElement>) => {
      if (diving) return;
      const target = e.target as HTMLElement;
      const tileEl = target.closest("[data-tile-kind]") as HTMLElement | null;
      const tileKind = tileEl?.getAttribute("data-tile-kind");
      const list = nodes ?? [];
      const world = pointerToWorld(e.clientX, e.clientY);
      const hitNode = world
        ? list.find(
            (n: SpatialNode) =>
              world.x >= n.world_x &&
              world.x <= n.world_x + n.world_w &&
              world.y >= n.world_y &&
              world.y <= n.world_y + n.world_h,
          ) ?? null
        : null;
      const hitCluster = tileKind === "channel-cluster" && world
        ? channelClusters.find((cluster: any) => {
            const n = cluster.winner.node;
            return (
              world.x >= n.world_x &&
              world.x <= n.world_x + n.world_w &&
              world.y >= n.world_y &&
              world.y <= n.world_y + n.world_h
            );
          }) ?? null
        : null;
      e.preventDefault();
      const items: SpatialContextMenuItem[] = [];
      if (hitCluster) {
        const winnerNode = hitCluster.winner.node;
        const winnerName = hitCluster.winner.channel.name;
        items.push({
          label: "Fly to cluster members",
          icon: <Locate size={14} />,
          onClick: () => flyToWorldBounds(hitCluster.worldBounds),
        });
        items.push({
          label: `Dive into #${winnerName}`,
          icon: <ZoomIn size={14} />,
          onClick: () =>
            diveToChannel(hitCluster.winner.channel.id, {
              x: winnerNode.world_x,
              y: winnerNode.world_y,
              w: winnerNode.world_w,
              h: winnerNode.world_h,
            }),
        });
      } else if (tileKind === "channel" && hitNode?.channel_id) {
        const channelId = hitNode.channel_id;
        const channel = channelsById.get(channelId) ?? null;
        const channelName = channel?.name ?? "channel";
        items.push({
          label: "Dive into channel",
          icon: <ZoomIn size={14} />,
          onClick: () =>
            diveToChannel(channelId, {
              x: hitNode.world_x,
              y: hitNode.world_y,
              w: hitNode.world_w,
              h: hitNode.world_h,
            }),
        });
        items.push({
          label: "Fly camera here",
          icon: <Locate size={14} />,
          onClick: () => flyToChannel(channelId),
        });
        if (channel) {
          items.push({
            label: `Open mini chat — #${channelName}`,
            icon: <MessageCircle size={14} />,
            onClick: () =>
              setOpenBotChat({
                botId: channel.bot_id,
                botName: channel.bot_id,
                channelId: channel.id,
                channelName: channel.name,
              }),
          });
        }
        items.push({
          label: "Unpin from canvas",
          icon: <Trash2 size={14} />,
          danger: true,
          separator: true,
          onClick: () => deleteNode.mutate(hitNode.id),
        });
      } else if (tileKind === "project" && hitNode?.project_id) {
        const projectId = hitNode.project_id;
        items.push({
          label: "Open project",
          icon: <ExternalLink size={14} />,
          onClick: () => navigate(`/admin/projects/${projectId}`, { state: canvasBackState }),
        });
        items.push({
          label: "Open project runs",
          icon: <Maximize2 size={14} />,
          onClick: () => navigate(`/admin/projects/${projectId}#runs`, { state: canvasBackState }),
        });
        items.push({
          label: "Reset position",
          icon: <Home size={14} />,
          separator: true,
          onClick: () => deleteNode.mutate(hitNode.id),
        });
      } else if (tileKind === "widget" && hitNode?.pin) {
        const pin = hitNode.pin;
        items.push({
          label: "Open full widget",
          icon: <Maximize2 size={14} />,
          onClick: () => navigate(widgetPinHref(pin.id), { state: canvasBackState }),
        });
        if (pin.source_channel_id) {
          const sourceId = pin.source_channel_id;
          items.push({
            label: "Open source channel",
            icon: <ExternalLink size={14} />,
            onClick: () => navigate(channelHref(sourceId), { state: canvasBackState }),
          });
        }
        items.push({
          label: "Reset size",
          icon: <Settings size={14} />,
          onClick: () =>
            updateNode.mutate({
              nodeId: hitNode.id,
              body: { world_w: 320, world_h: 220 },
            }),
        });
        items.push({
          label: "Unpin from canvas",
          icon: <Trash2 size={14} />,
          danger: true,
          separator: true,
          onClick: () => deleteNode.mutate(hitNode.id),
        });
      } else if (tileKind === "bot" && hitNode?.bot_id) {
        const botId = hitNode.bot_id;
        const botName = hitNode.bot?.display_name || hitNode.bot?.name || botId;
        const channel = channelForBot(botId);
        items.push({
          label: channel ? `Open mini chat — ${botName}` : "Open mini chat (no channel)",
          icon: <MessageCircle size={14} />,
          disabled: !channel,
          onClick: () => {
            if (!channel) return;
            setOpenBotChat({
              botId,
              botName,
              channelId: channel.id,
              channelName: channel.name,
            });
          },
        });
        items.push({
          label: "Open bot admin",
          icon: <ExternalLink size={14} />,
          onClick: () =>
            navigate(`/admin/bots/${botId}`, {
              state: canvasBackState,
            }),
        });
        items.push({
          label: "Reset position",
          icon: <Home size={14} />,
          separator: true,
          onClick: () => deleteNode.mutate(hitNode.id),
        });
      } else {
        const worldX = world?.x ?? 0;
        const worldY = world?.y ?? 0;
        const screenX = e.clientX;
        const screenY = e.clientY;
        const openMovePicker = (
          kind: "channel" | "project" | "widget" | "bot",
        ) => {
          const candidates = list.filter((n: SpatialNode) => {
            if (kind === "channel") return Boolean(n.channel_id);
            if (kind === "project") return Boolean(n.project_id);
            if (kind === "widget") return Boolean(n.pin);
            return Boolean(n.bot_id);
          });
          const labelFor = (n: SpatialNode): string => {
            if (n.channel_id) {
              const c = channelsById.get(n.channel_id);
              return c?.name ? `#${c.name}` : "channel";
            }
            if (n.project_id) {
              return n.project?.name || "project";
            }
            if (n.bot_id) {
              return n.bot?.display_name || n.bot?.name || n.bot_id;
            }
            return n.pin?.display_label
              || n.pin?.tool_name
              || "widget";
          };
          const sorted = [...candidates].sort((a, b) =>
            labelFor(a).localeCompare(labelFor(b)),
          );
          const pickerItems: SpatialContextMenuItem[] = sorted.map((n) => ({
            label: labelFor(n),
            icon: <Move size={14} />,
            onClick: () =>
              updateNode.mutate({
                nodeId: n.id,
                body: {
                  world_x: worldX - n.world_w / 2,
                  world_y: worldY - n.world_h / 2,
                },
              }),
          }));
          if (pickerItems.length === 0) {
            pickerItems.push({
              label: `No ${kind}s on the canvas`,
              icon: <Move size={14} />,
              disabled: true,
              onClick: () => {},
            });
          }
          setContextMenu({ screenX, screenY, items: pickerItems });
        };
        items.push({
          label: "Add widget here",
          icon: <Plus size={14} />,
          onClick: () => {
            setPinPositionOverride({ x: worldX - 160, y: worldY - 110 });
            openStarboardLaunch();
          },
        });
        items.push({
          label: "Move channel here…",
          icon: <Move size={14} />,
          onClick: () => openMovePicker("channel"),
          keepOpen: true,
        });
        items.push({
          label: "Move project here…",
          icon: <Move size={14} />,
          onClick: () => openMovePicker("project"),
          keepOpen: true,
        });
        items.push({
          label: "Move widget here…",
          icon: <Move size={14} />,
          onClick: () => openMovePicker("widget"),
          keepOpen: true,
        });
        items.push({
          label: "Move bot here…",
          icon: <Move size={14} />,
          onClick: () => openMovePicker("bot"),
          keepOpen: true,
        });
        items.push({
          label: "Recenter",
          icon: <Home size={14} />,
          onClick: () => scheduleCamera(defaultCamera, "immediate"),
        });
        items.push({
          label: "Fit all (F)",
          icon: <Maximize2 size={14} />,
          onClick: () => fitAllNodes(),
        });
        items.push({
          label: `Trails: ${trailsMode}`,
          icon: <Footprints size={14} />,
          separator: true,
          onClick: () => cycleTrailsMode(),
        });
        items.push({
          label: connectionsEnabled ? "Hide connection lines" : "Show connection lines",
          icon: <Link2 size={14} />,
          onClick: () => setConnectionsEnabled((v: any) => !v),
        });
      }
      setContextMenu({ screenX: e.clientX, screenY: e.clientY, items });
    },
    [
      diving,
      nodes,
      pointerToWorld,
      channelClusters,
      flyToWorldBounds,
      diveToChannel,
      channelsById,
      flyToChannel,
      setOpenBotChat,
      deleteNode,
      navigate,
      canvasBackState,
      updateNode,
      channelForBot,
      setPinPositionOverride,
      openStarboardLaunch,
      scheduleCamera,
      defaultCamera,
      fitAllNodes,
      trailsMode,
      cycleTrailsMode,
      connectionsEnabled,
      setConnectionsEnabled,
      setContextMenu,
      channelHref,
    ],
  );
}
