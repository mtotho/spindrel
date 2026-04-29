import { useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Brain, LayoutDashboard, MessageCircle, Radar, Target, Users as UsersIcon } from "lucide-react";
import { widgetPinHref } from "../../lib/hubRoutes";
import { resolveChannelEntryHref } from "../../lib/channelNavigation";
import { useUIStore } from "../../stores/ui";
import type { UnreadStateResponse } from "../../api/hooks/useUnread";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import type { Camera } from "./spatialGeometry";
import type { StarboardObjectAction, StarboardObjectItem } from "./UsageDensityChrome";
import { mapCueRank, mapStateMeta } from "./SpatialObjectStatus";

type UseSpatialStarboardModelsArgs = Record<string, any> & {
  camera: Camera;
};

export function useSpatialStarboardModels(args: UseSpatialStarboardModelsArgs) {
  const {
    viewportRectRef,
    camera,
    flyToStarboardObject,
    memoryObsPos,
    selectLandmark,
    flyToMemoryObservatory,
    wellPos,
    flyToWell,
    activeAttentionCount,
    attentionHubPos,
    openStarboardAttention,
    dailyHealthPos,
    openStarboardHealth,
    nodes,
    channelsById,
    selectNode,
    diveToChannel,
    navigate,
    canvasBackState,
    setOpenBotChat,
    channelForBot,
    attentionSignalsVisible,
    mapAttentionCount,
    flyToChannel,
    flyToNodeById,
    botsVisible,
    selectedSpatialObject,
    mapState,
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

  const scheduleActionForSignal = useCallback((signal: any): StarboardObjectAction | null => {
    if (!signal) return null;
    if (signal.kind === "heartbeat" && signal.channel_id) {
      return {
        label: "Open heartbeat settings",
        icon: "settings",
        onSelect: () =>
          navigate(`/channels/${signal.channel_id}/settings#automation`, {
            state: canvasBackState,
          }),
      };
    }
    const taskId = signal.kind === "task" ? signal.task_id || signal.id : null;
    if (taskId) {
      return {
        label: "Open automation",
        icon: "open",
        onSelect: () =>
          navigate(`/admin/automations/${taskId}`, {
            state: canvasBackState,
          }),
      };
    }
    return null;
  }, [canvasBackState, navigate]);

  const starboardObjects = useMemo<StarboardObjectItem[]>(() => {
    const landmarkSize = { worldW: 180, worldH: 120 };
    const rect = viewportRectRef.current;
    const scale = Math.max(camera.scale, 0.05);
    const focusX = rect.width ? (rect.width / 2 - camera.x) / scale : 0;
    const focusY = rect.height ? (rect.height / 2 - camera.y) / scale : 0;
    const distanceFromFocus = (worldX: number, worldY: number) => Math.hypot(worldX - focusX, worldY - focusY);
    const jumpAction = (worldX: number, worldY: number): StarboardObjectAction => ({
      label: "Jump here",
      icon: "jump",
      onSelect: () => flyToStarboardObject(worldX, worldY),
    });
    const landmarkState = (kind: string) =>
      mapState?.objects?.find((item: any) => item.kind === "landmark" && item.target_id === kind) ?? null;
    const items: StarboardObjectItem[] = [
      {
        id: "landmark-memory-observatory",
        label: "Memory Observatory",
        kind: "landmark",
        subtitle: "Landmark",
        workState: landmarkState("memory_observatory"),
        worldX: memoryObsPos.x,
        worldY: memoryObsPos.y,
        ...landmarkSize,
        distance: distanceFromFocus(memoryObsPos.x, memoryObsPos.y),
        onSelect: () => selectLandmark("memory_observatory", memoryObsPos.x, memoryObsPos.y, true),
        actions: [
          jumpAction(memoryObsPos.x, memoryObsPos.y),
          { label: "Open Memory Observatory", icon: "open", onSelect: flyToMemoryObservatory },
        ],
      },
      {
        id: "landmark-now-well",
        label: "Now Well",
        kind: "landmark",
        subtitle: "Landmark",
        workState: landmarkState("now_well"),
        worldX: wellPos.x,
        worldY: wellPos.y,
        ...landmarkSize,
        distance: distanceFromFocus(wellPos.x, wellPos.y),
        onSelect: () => selectLandmark("now_well", wellPos.x, wellPos.y, true),
        actions: [
          jumpAction(wellPos.x, wellPos.y),
          { label: "Open Now Well", icon: "open", onSelect: flyToWell },
        ],
      },
      {
        id: "landmark-attention-hub",
        label: "Attention Hub",
        kind: "landmark",
        subtitle: activeAttentionCount > 0 ? `${activeAttentionCount} active` : "Landmark",
        workState: landmarkState("attention_hub"),
        worldX: attentionHubPos.x,
        worldY: attentionHubPos.y,
        ...landmarkSize,
        distance: distanceFromFocus(attentionHubPos.x, attentionHubPos.y),
        onSelect: () => {
          selectLandmark("attention_hub", attentionHubPos.x, attentionHubPos.y, true);
        },
        actions: [
          jumpAction(attentionHubPos.x, attentionHubPos.y),
          { label: "Open Attention", icon: "open", onSelect: () => openStarboardAttention() },
        ],
      },
      {
        id: "landmark-daily-health",
        label: "Daily Health",
        kind: "landmark",
        subtitle: "Landmark",
        workState: landmarkState("daily_health"),
        worldX: dailyHealthPos.x,
        worldY: dailyHealthPos.y,
        ...landmarkSize,
        distance: distanceFromFocus(dailyHealthPos.x, dailyHealthPos.y),
        onSelect: () => selectLandmark("daily_health", dailyHealthPos.x, dailyHealthPos.y, true),
        actions: [
          jumpAction(dailyHealthPos.x, dailyHealthPos.y),
          { label: "Open Daily Health", icon: "open", onSelect: openStarboardHealth },
        ],
      },
    ];
    for (const node of nodes ?? []) {
      const worldX = node.world_x + node.world_w / 2;
      const worldY = node.world_y + node.world_h / 2;
      if (node.channel_id) {
        const channel = channelsById.get(node.channel_id);
        const workState = mapState?.objects_by_node_id?.[node.id] ?? null;
        const scheduleAction = scheduleActionForSignal(workState?.next);
        items.push({
          id: `node-${node.id}`,
          label: channel ? `#${channel.name}` : "Channel",
          kind: "channel",
          subtitle: mapStateMeta(workState) ?? "Channel",
          workState,
          worldX,
          worldY,
          worldW: node.world_w,
          worldH: node.world_h,
          distance: distanceFromFocus(worldX, worldY),
          onSelect: () => selectNode("channel", node, true),
          onDoubleClick: () =>
            diveToChannel(node.channel_id!, {
              x: node.world_x,
              y: node.world_y,
              w: node.world_w,
              h: node.world_h,
            }),
          actions: [
            jumpAction(worldX, worldY),
            { label: "Open channel", icon: "open", onSelect: () => navigate(channelHref(node.channel_id!), { state: canvasBackState }) },
            ...(scheduleAction ? [scheduleAction] : []),
            {
              label: channel ? `Open mini chat - #${channel.name}` : "Open mini chat",
              icon: "chat",
              disabled: !channel,
              onSelect: () => {
                if (!channel) return;
                setOpenBotChat({
                  botId: channel.bot_id,
                  botName: channel.bot_id,
                  channelId: channel.id,
                  channelName: channel.name,
                });
              },
            },
          ],
        });
      } else if (node.pin) {
        const workState = mapState?.objects_by_node_id?.[node.id] ?? null;
        items.push({
          id: `node-${node.id}`,
          label: node.pin.panel_title || node.pin.display_label || node.pin.tool_name || "Widget",
          kind: "widget",
          subtitle: mapStateMeta(workState) ?? node.pin.tool_name ?? "Widget",
          workState,
          worldX,
          worldY,
          worldW: node.world_w,
          worldH: node.world_h,
          distance: distanceFromFocus(worldX, worldY),
          onSelect: () => selectNode("widget", node, true),
          onDoubleClick: () => navigate(widgetPinHref(node.pin!.id), { state: canvasBackState }),
          actions: [
            jumpAction(worldX, worldY),
            { label: "Open full widget", icon: "open", onSelect: () => navigate(widgetPinHref(node.pin!.id), { state: canvasBackState }) },
            {
              label: "Open source channel",
              icon: "open",
              disabled: !node.pin.source_channel_id,
              onSelect: () => {
                if (node.pin?.source_channel_id) navigate(`/channels/${node.pin.source_channel_id}`, { state: canvasBackState });
              },
            },
          ],
        });
      } else if (node.bot_id) {
        const botId = node.bot_id;
        const botName = node.bot?.display_name || node.bot?.name || botId;
        const channel = channelForBot(botId);
        const workState = mapState?.objects_by_node_id?.[node.id] ?? null;
        items.push({
          id: `node-${node.id}`,
          label: botName,
          kind: "bot",
          subtitle: mapStateMeta(workState) ?? "Bot",
          workState,
          worldX,
          worldY,
          worldW: node.world_w,
          worldH: node.world_h,
          distance: distanceFromFocus(worldX, worldY),
          onSelect: () => selectNode("bot", node, true),
          actions: [
            jumpAction(worldX, worldY),
            {
              label: channel ? `Open bot chat - ${botName}` : "Open bot chat",
              icon: "chat",
              disabled: !channel,
              onSelect: () => {
                if (!channel) return;
                setOpenBotChat({ botId, botName, channelId: channel.id, channelName: channel.name });
              },
            },
            {
              label: "Open bot settings",
              icon: "settings",
              onSelect: () =>
                navigate(`/admin/bots/${botId}`, {
                  state: canvasBackState,
                }),
            },
          ],
        });
      }
    }
    const rank = (item: StarboardObjectItem) => {
      const cue = mapCueRank(item.workState);
      if (cue > 0) return cue + 10;
      const status = item.workState?.status;
      if (status === "error") return 6;
      if (status === "warning") return 5;
      if (status === "running") return 4;
      if (status === "scheduled") return 3;
      if (status === "active") return 2;
      if (status === "recent") return 1;
      return 0;
    };
    return items.sort((a, b) => rank(b) - rank(a) || a.distance - b.distance || a.label.localeCompare(b.label));
  }, [
    nodes,
    channelsById,
    camera,
    activeAttentionCount,
    dailyHealthPos.x,
    dailyHealthPos.y,
    flyToStarboardObject,
    selectNode,
    selectLandmark,
    flyToMemoryObservatory,
    flyToWell,
    openStarboardHealth,
    openStarboardAttention,
    channelForBot,
    diveToChannel,
    navigate,
    canvasBackState,
    setOpenBotChat,
    viewportRectRef,
    memoryObsPos.x,
    memoryObsPos.y,
    wellPos.x,
    wellPos.y,
    attentionHubPos.x,
    attentionHubPos.y,
    mapState,
    channelHref,
    scheduleActionForSignal,
  ]);

  const edgeBeacons = useMemo(() => {
    const beacons = [
      {
        id: "memory-observatory",
        label: "Memory Observatory",
        shortLabel: "Memory",
        worldX: memoryObsPos.x,
        worldY: memoryObsPos.y,
        colorClass: "border-violet-300/40 text-violet-200 hover:border-violet-200/70",
        icon: Brain,
        onClick: flyToMemoryObservatory,
      },
      {
        id: "now-well",
        label: "Now Well",
        shortLabel: "Now",
        worldX: wellPos.x,
        worldY: wellPos.y,
        colorClass: "border-sky-300/35 text-sky-100 hover:border-sky-200/65",
        icon: Target,
        onClick: flyToWell,
      },
      {
        id: "attention-hub",
        label: attentionSignalsVisible && mapAttentionCount > 0 ? `Attention Hub (${mapAttentionCount} mapped)` : "Attention Hub",
        shortLabel: "Attention",
        worldX: attentionHubPos.x,
        worldY: attentionHubPos.y,
        colorClass: "border-warning/55 text-warning hover:border-warning/85",
        icon: Radar,
        onClick: () => openStarboardAttention(),
        persistent: attentionSignalsVisible && mapAttentionCount > 0,
      },
    ];

    for (const node of nodes ?? []) {
      const worldX = node.world_x + node.world_w / 2;
      const worldY = node.world_y + node.world_h / 2;
      if (node.channel_id) {
        const channel = channelsById.get(node.channel_id);
        beacons.push({
          id: `channel-${node.id}`,
          label: channel ? `#${channel.name}` : "Channel",
          shortLabel: "Channel",
          worldX,
          worldY,
          colorClass: "border-cyan-300/35 text-cyan-100 hover:border-cyan-200/65",
          icon: MessageCircle,
          onClick: () => flyToChannel(node.channel_id!),
        });
      } else if (node.pin) {
        beacons.push({
          id: `widget-${node.id}`,
          label: node.pin.panel_title || node.pin.display_label || node.pin.tool_name || "Widget",
          shortLabel: "Widget",
          worldX,
          worldY,
          colorClass: "border-amber-300/35 text-amber-100 hover:border-amber-200/65",
          icon: LayoutDashboard,
          onClick: () => flyToNodeById(node.id),
        });
      } else if (node.bot_id && botsVisible) {
        const botName = node.bot?.display_name || node.bot?.name || node.bot_id;
        beacons.push({
          id: `bot-${node.id}`,
          label: botName,
          shortLabel: "Bot",
          worldX,
          worldY,
          colorClass: "border-emerald-300/35 text-emerald-100 hover:border-emerald-200/65",
          icon: UsersIcon,
          onClick: () => flyToNodeById(node.id),
        });
      }
    }
    return beacons;
  }, [
    nodes,
    channelsById,
    botsVisible,
    attentionSignalsVisible,
    mapAttentionCount,
    flyToMemoryObservatory,
    flyToWell,
    openStarboardAttention,
    flyToChannel,
    flyToNodeById,
    memoryObsPos.x,
    memoryObsPos.y,
    wellPos.x,
    wellPos.y,
    attentionHubPos.x,
    attentionHubPos.y,
  ]);

  const selectedStarboardObject = useMemo(() => {
    if (!selectedSpatialObject) return null;
    if (selectedSpatialObject.kind === "channel" || selectedSpatialObject.kind === "bot" || selectedSpatialObject.kind === "widget") {
      return starboardObjects.find((item) => item.id === `node-${selectedSpatialObject.nodeId}`) ?? null;
    }
    if (selectedSpatialObject.kind === "landmark") {
      const id = selectedSpatialObject.id === "memory_observatory"
        ? "landmark-memory-observatory"
        : selectedSpatialObject.id === "now_well"
          ? "landmark-now-well"
          : selectedSpatialObject.id === "attention_hub"
            ? "landmark-attention-hub"
            : "landmark-daily-health";
      return starboardObjects.find((item) => item.id === id) ?? null;
    }
    return null;
  }, [selectedSpatialObject, starboardObjects]);

  return { starboardObjects, edgeBeacons, selectedStarboardObject };
}
