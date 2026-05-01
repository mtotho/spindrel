import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { landmarkPositionFromNodes, useSpatialCanvasBootstrap, useSpatialNodes } from "../../api/hooks/useWorkspaceSpatial";
import { useChannels } from "../../api/hooks/useChannels";
import { useBots } from "../../api/hooks/useBots";
import { useDashboards, channelIdFromSlug } from "../../stores/dashboards";
import {
  isActiveAttentionItem,
  useMarkAttentionResponded,
  useWorkspaceAttention,
  type WorkspaceAttentionItem,
} from "../../api/hooks/useWorkspaceAttention";
import { useWorkspaceMissions } from "../../api/hooks/useWorkspaceMissions";
import { useWorkspaceMapState } from "../../api/hooks/useWorkspaceMapState";
import { useSpatialUpcomingActivity } from "../../api/hooks/useUpcomingActivity";
import type { Channel } from "../../types/api";
import type { TasksResponse } from "../shared/TaskConstants";
import {
  ATTENTION_HUB_X,
  ATTENTION_HUB_Y,
  HEALTH_SUMMARY_X,
  HEALTH_SUMMARY_Y,
  MEMORY_OBSERVATORY_X,
  MEMORY_OBSERVATORY_Y,
  WELL_X,
  WELL_Y,
} from "./spatialGeometry";
import { shouldSurfaceAttentionOnMap } from "./SpatialAttentionLayer";

export function useSpatialCanvasData() {
  const { data: bootstrap } = useSpatialCanvasBootstrap();
  const [enrichmentEnabled, setEnrichmentEnabled] = useState(false);
  useEffect(() => {
    if (!bootstrap || enrichmentEnabled) return;
    const start = () => setEnrichmentEnabled(true);
    const requestIdle = window.requestIdleCallback;
    if (requestIdle) {
      const id = requestIdle(start, { timeout: 750 });
      return () => window.cancelIdleCallback?.(id);
    }
    const id = window.setTimeout(start, 150);
    return () => window.clearTimeout(id);
  }, [bootstrap, enrichmentEnabled]);

  const { data: hydratedNodes } = useSpatialNodes({ enabled: enrichmentEnabled });
  const nodes = hydratedNodes ?? bootstrap?.nodes;
  const nodesRef = useRef<typeof nodes>(nodes);
  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  const wellPos = landmarkPositionFromNodes(nodes, "now_well", WELL_X, WELL_Y);
  const memoryObsPos = landmarkPositionFromNodes(nodes, "memory_observatory", MEMORY_OBSERVATORY_X, MEMORY_OBSERVATORY_Y);
  const attentionHubPos = landmarkPositionFromNodes(nodes, "attention_hub", ATTENTION_HUB_X, ATTENTION_HUB_Y);
  const dailyHealthPos = landmarkPositionFromNodes(nodes, "daily_health", HEALTH_SUMMARY_X, HEALTH_SUMMARY_Y);
  const { data: attentionItems } = useWorkspaceAttention(null, { includeResolved: true, enabled: enrichmentEnabled });
  const { data: missions } = useWorkspaceMissions(false, { enabled: enrichmentEnabled });
  const { data: mapState } = useWorkspaceMapState({ enabled: enrichmentEnabled });
  const markAttentionResponded = useMarkAttentionResponded();
  const { data: hydratedChannels } = useChannels({ enabled: enrichmentEnabled });
  const channels = hydratedChannels ?? bootstrap?.channels;
  const { data: hydratedBots } = useBots({ enabled: enrichmentEnabled });
  const bots = hydratedBots ?? bootstrap?.bots;
  const { data: upcomingItems } = useSpatialUpcomingActivity(50, undefined, { enabled: enrichmentEnabled });
  const { data: definitionsData } = useQuery({
    queryKey: ["spatial-task-definitions"],
    queryFn: () => apiFetch<TasksResponse>("/api/v1/admin/tasks?limit=200&definitions_only=true"),
    staleTime: 30_000,
    enabled: enrichmentEnabled,
  });
  const taskDefinitions = useMemo(
    () => (definitionsData?.tasks ?? []).filter((t) => t.source !== "system"),
    [definitionsData],
  );

  const [tickedNow, setTickedNow] = useState(() => Date.now());
  const hasImminentRef = useRef(false);
  useEffect(() => {
    hasImminentRef.current = (upcomingItems ?? []).some((it) => {
      const t = Date.parse(it.scheduled_at);
      return !Number.isNaN(t) && t - Date.now() < 60_000;
    });
  }, [upcomingItems]);
  useEffect(() => {
    let intervalMs = hasImminentRef.current ? 1_000 : 5_000;
    let id = window.setInterval(tick, intervalMs);
    function tick() {
      const now = Date.now();
      setTickedNow(now);
      const wantFast = (upcomingItems ?? []).some((it) => {
        const t = Date.parse(it.scheduled_at);
        return !Number.isNaN(t) && t - now < 60_000;
      });
      const target = wantFast ? 1_000 : 5_000;
      if (target !== intervalMs) {
        window.clearInterval(id);
        intervalMs = target;
        id = window.setInterval(tick, intervalMs);
      }
    }
    return () => window.clearInterval(id);
  }, [upcomingItems]);

  const channelsById = useMemo(() => {
    const m = new Map<string, Channel>();
    for (const c of channels ?? []) m.set(c.id, c);
    return m;
  }, [channels]);

  const attentionByNodeId = useMemo(() => {
    const byNode = new Map<string, WorkspaceAttentionItem[]>();
    const list = attentionItems ?? [];
    const byTargetNode = new Map<string, string>();
    const byChannel = new Map<string, string>();
    const byBot = new Map<string, string>();
    const byWidget = new Map<string, string>();
    for (const candidate of nodes ?? []) {
      byTargetNode.set(candidate.id, candidate.id);
      if (candidate.channel_id) byChannel.set(candidate.channel_id, candidate.id);
      if (candidate.bot_id) byBot.set(candidate.bot_id, candidate.id);
      if (candidate.widget_pin_id) byWidget.set(candidate.widget_pin_id, candidate.id);
    }
    for (const item of list) {
      if (!isActiveAttentionItem(item)) continue;
      const nodeId =
        (item.target_node_id ? byTargetNode.get(item.target_node_id) : undefined)
        ?? (item.target_kind === "channel" ? byChannel.get(item.target_id) : undefined)
        ?? (item.target_kind === "bot" ? byBot.get(item.target_id) : undefined)
        ?? (item.target_kind === "widget" ? byWidget.get(item.target_id) : undefined);
      if (!nodeId) continue;
      const bucket = byNode.get(nodeId) ?? [];
      bucket.push(item);
      byNode.set(nodeId, bucket);
    }
    return byNode;
  }, [attentionItems, nodes]);
  const activeAttentionCount = useMemo(
    () => (attentionItems ?? []).filter(isActiveAttentionItem).length,
    [attentionItems],
  );
  const mapAttentionCount = useMemo(
    () => (attentionItems ?? []).filter(shouldSurfaceAttentionOnMap).length,
    [attentionItems],
  );

  const channelByBotId = useMemo(() => {
    const m = new Map<string, Channel>();
    const ts = (c: Channel): number => {
      const raw = c.last_message_at ?? c.updated_at ?? c.created_at;
      return raw ? new Date(raw).getTime() : 0;
    };
    const offer = (botId: string | null | undefined, channel: Channel) => {
      if (!botId) return;
      const existing = m.get(botId);
      if (!existing || ts(channel) > ts(existing)) m.set(botId, channel);
    };
    for (const channel of channels ?? []) {
      offer(channel.bot_id, channel);
      for (const member of channel.member_bots ?? []) {
        offer(member.bot_id, channel);
      }
    }
    return m;
  }, [channels]);

  const channelForBot = useCallback(
    (botId: string): Channel | null => channelByBotId.get(botId) ?? null,
    [channelByBotId],
  );

  const botAvatarById = useMemo(() => {
    const m = new Map<string, string>();
    for (const bot of bots ?? []) {
      if (bot.avatar_emoji) m.set(bot.id, bot.avatar_emoji);
    }
    return m;
  }, [bots]);

  const { channelDashboards } = useDashboards();
  const iconByChannelId = useMemo(() => {
    const m = new Map<string, string | null>();
    for (const d of channelDashboards) {
      const cid = channelIdFromSlug(d.slug);
      if (cid) m.set(cid, d.icon);
    }
    return m;
  }, [channelDashboards]);

  return {
    nodes,
    enrichmentEnabled,
    nodesRef,
    wellPos,
    memoryObsPos,
    attentionHubPos,
    dailyHealthPos,
    attentionItems,
    missions,
    mapState,
    markAttentionResponded,
    channels,
    bots,
    upcomingItems,
    taskDefinitions,
    tickedNow,
    channelsById,
    attentionByNodeId,
    activeAttentionCount,
    mapAttentionCount,
    channelForBot,
    botAvatarById,
    iconByChannelId,
  };
}
