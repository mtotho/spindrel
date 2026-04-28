import { useMemo } from "react";
import {
  Bot,
  Box,
  Brain,
  ExternalLink,
  Home,
  Locate,
  Maximize2,
  MessageCircle,
  MoreHorizontal,
  Radar,
  Settings,
  Sparkles,
  Target,
  Trash2,
  ZoomIn,
} from "lucide-react";
import { widgetPinHref } from "../../lib/hubRoutes";
import type { SpatialContextMenuItem } from "./SpatialContextMenu";
import type { SpatialSelectionAction } from "./SpatialSelectionRail";
import { mapStateLabel, mapStateMeta } from "./SpatialObjectStatus";

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
    wellPos,
    memoryObsPos,
    activeAttentionCount,
    attentionHubPos,
    dailyHealthPos,
    flyToWell,
    flyToMemoryObservatory,
    openStarboardAttention,
    openStarboardHealth,
    flyToStarboardObject,
    nodes,
    focusNode,
    channelsById,
    setOpenBotChat,
    openStarboardHub,
    navigate,
    canvasBackState,
    deleteNode,
    channelForBot,
    updateNode,
    mapState,
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

    if (selectedSpatialObject.kind === "landmark") {
      const landmark =
        selectedSpatialObject.id === "now_well"
          ? { label: "Now Well", meta: "Landmark", x: wellPos.x, y: wellPos.y, open: flyToWell, icon: Target }
          : selectedSpatialObject.id === "memory_observatory"
          ? { label: "Memory Observatory", meta: "Landmark", x: memoryObsPos.x, y: memoryObsPos.y, open: flyToMemoryObservatory, icon: Brain }
          : selectedSpatialObject.id === "attention_hub"
          ? { label: "Attention Hub", meta: `${activeAttentionCount} active`, x: attentionHubPos.x, y: attentionHubPos.y, open: () => openStarboardAttention(), icon: Radar }
          : { label: "Daily Health", meta: "Landmark", x: dailyHealthPos.x, y: dailyHealthPos.y, open: openStarboardHealth, icon: Sparkles };
      const anchor = toScreen(landmark.x, landmark.y - 90);
      const focus = () => flyToStarboardObject(landmark.x, landmark.y);
      const Icon = landmark.icon;
      return {
        x: anchor.x,
        y: anchor.y,
        label: landmark.label,
        meta: landmark.meta,
        leading: <Icon className="h-4 w-4" />,
        actions: [
          { id: "focus", label: "Focus", icon: Locate, onSelect: (event) => { event.stopPropagation(); focus(); } },
          { id: "open", label: "Open", icon: ExternalLink, onSelect: (event) => { event.stopPropagation(); landmark.open(); } },
          moreAction([
            { label: "Focus", icon: <Locate size={14} />, onClick: focus },
            { label: "Open", icon: <ExternalLink size={14} />, onClick: landmark.open },
          ]),
        ] satisfies SpatialSelectionAction[],
      };
    }

    const node = (nodes ?? []).find((entry: any) => entry.id === selectedSpatialObject.nodeId);
    if (!node) return null;
    const objectState = mapState?.objects_by_node_id?.[node.id] ?? null;
    const stateMeta = mapStateLabel(objectState) || mapStateMeta(objectState);
    const anchor = toScreen(node.world_x + node.world_w / 2, node.world_y - 12);
    const focus = () => focusNode(node);

    if (selectedSpatialObject.kind === "channel" && node.channel_id) {
      const channel = channelsById.get(node.channel_id);
      if (!channel) return null;
      const dive = () =>
        diveToChannel(channel.id, {
          x: node.world_x,
          y: node.world_y,
          w: node.world_w,
          h: node.world_h,
        });
      const openChat = () =>
        setOpenBotChat({
          botId: channel.bot_id,
          botName: channel.bot_id,
          channelId: channel.id,
          channelName: channel.name,
        });
      return {
        x: anchor.x,
        y: anchor.y,
        label: `#${channel.name}`,
        meta: stateMeta || "Channel",
        leading: <MessageCircle className="h-4 w-4" />,
        actions: [
          { id: "focus", label: "Focus", icon: Locate, onSelect: (event) => { event.stopPropagation(); focus(); } },
          { id: "dive", label: "Dive", icon: ZoomIn, onSelect: (event) => { event.stopPropagation(); dive(); } },
          { id: "chat", label: "Open chat", icon: MessageCircle, onSelect: (event) => { event.stopPropagation(); openChat(); } },
          { id: "mission-control", label: "Ask Mission Control", icon: Radar, onSelect: (event) => { event.stopPropagation(); openStarboardHub(); } },
          moreAction([
            { label: "Dive into channel", icon: <ZoomIn size={14} />, onClick: dive },
            { label: "Fly camera here", icon: <Locate size={14} />, onClick: focus },
            { label: "Ask Mission Control about this room", icon: <Radar size={14} />, onClick: openStarboardHub },
            { label: `Open mini chat - #${channel.name}`, icon: <MessageCircle size={14} />, onClick: openChat },
            { label: "Open channel", icon: <ExternalLink size={14} />, onClick: () => navigate(`/channels/${channel.id}`, { state: canvasBackState }) },
            { label: "Unpin from canvas", icon: <Trash2 size={14} />, danger: true, separator: true, onClick: () => deleteNode.mutate(node.id) },
          ]),
        ] satisfies SpatialSelectionAction[],
      };
    }

    if (selectedSpatialObject.kind === "bot" && node.bot_id) {
      const botId = node.bot_id;
      const botName = node.bot?.display_name || node.bot?.name || botId;
      const channel = channelForBot(botId);
      const openChat = () => {
        if (!channel) return;
        setOpenBotChat({ botId, botName, channelId: channel.id, channelName: channel.name });
      };
      const openSettings = () =>
        navigate(`/admin/bots/${botId}`, {
          state: canvasBackState,
        });
      return {
        x: anchor.x,
        y: anchor.y,
        label: botName,
        meta: stateMeta || "Bot",
        leading: <Bot className="h-4 w-4" />,
        actions: [
          { id: "focus", label: "Focus", icon: Locate, onSelect: (event) => { event.stopPropagation(); focus(); } },
          { id: "chat", label: channel ? "Open chat" : "No channel available", icon: MessageCircle, disabled: !channel, onSelect: (event) => { event.stopPropagation(); openChat(); } },
          { id: "settings", label: "Bot settings", icon: Settings, onSelect: (event) => { event.stopPropagation(); openSettings(); } },
          { id: "mission-control", label: "Ask Mission Control", icon: Radar, onSelect: (event) => { event.stopPropagation(); openStarboardHub(); } },
          moreAction([
            { label: "Fly camera here", icon: <Locate size={14} />, onClick: focus },
            { label: "Ask Mission Control about this bot", icon: <Radar size={14} />, onClick: openStarboardHub },
            { label: channel ? `Open mini chat - ${botName}` : "Open mini chat (no channel)", icon: <MessageCircle size={14} />, disabled: !channel, onClick: openChat },
            { label: "Open bot admin", icon: <ExternalLink size={14} />, onClick: openSettings },
            { label: "Reset position", icon: <Home size={14} />, separator: true, onClick: () => deleteNode.mutate(node.id) },
          ]),
        ] satisfies SpatialSelectionAction[],
      };
    }

    if (selectedSpatialObject.kind === "widget" && node.pin) {
      const title = node.pin.panel_title || node.pin.display_label || node.pin.tool_name || "Widget";
      const sourceId = node.pin.source_channel_id;
      const openFull = () => navigate(widgetPinHref(node.pin!.id), { state: canvasBackState });
      const openSource = () => {
        if (sourceId) navigate(`/channels/${sourceId}`, { state: canvasBackState });
      };
      return {
        x: anchor.x,
        y: anchor.y,
        label: title,
        meta: stateMeta || "Widget",
        leading: <Box className="h-4 w-4" />,
        actions: [
          { id: "focus", label: "Focus", icon: Locate, onSelect: (event) => { event.stopPropagation(); focus(); } },
          { id: "open-full", label: "Open full", icon: Maximize2, onSelect: (event) => { event.stopPropagation(); openFull(); } },
          { id: "source", label: sourceId ? "Open source" : "No source channel", icon: ExternalLink, disabled: !sourceId, onSelect: (event) => { event.stopPropagation(); openSource(); } },
          { id: "mission-control", label: "Ask Mission Control", icon: Radar, onSelect: (event) => { event.stopPropagation(); openStarboardHub(); } },
          moreAction([
            { label: "Open full widget", icon: <Maximize2 size={14} />, onClick: openFull },
            { label: "Fly camera here", icon: <Locate size={14} />, onClick: focus },
            { label: "Ask Mission Control about this widget", icon: <Radar size={14} />, onClick: openStarboardHub },
            { label: "Open source channel", icon: <ExternalLink size={14} />, disabled: !sourceId, onClick: openSource },
            { label: "Reset size", icon: <Settings size={14} />, onClick: () => updateNode.mutate({ nodeId: node.id, body: { world_w: 320, world_h: 220 } }) },
            { label: "Unpin from canvas", icon: <Trash2 size={14} />, danger: true, separator: true, onClick: () => deleteNode.mutate(node.id) },
          ]),
        ] satisfies SpatialSelectionAction[],
      };
    }

    return null;
  }, [
    selectedSpatialObject,
    draggingNodeId,
    diving,
    camera.x,
    camera.y,
    camera.scale,
    channelClusters,
    nodes,
    channelsById,
    wellPos.x,
    wellPos.y,
    memoryObsPos.x,
    memoryObsPos.y,
    attentionHubPos.x,
    attentionHubPos.y,
    dailyHealthPos.x,
    dailyHealthPos.y,
    activeAttentionCount,
    flyToWorldBounds,
    diveToChannel,
    flyToWell,
    flyToMemoryObservatory,
    openStarboardAttention,
    openStarboardHub,
    openStarboardHealth,
    flyToStarboardObject,
    focusNode,
    channelForBot,
    navigate,
    canvasBackState,
    deleteNode,
    updateNode,
    mapState,
    setContextMenu,
    setOpenBotChat,
  ]);
}
