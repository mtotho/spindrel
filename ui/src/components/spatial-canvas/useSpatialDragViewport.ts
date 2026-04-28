import { useCallback, useMemo, type PointerEvent as ReactPointerEvent } from "react";
import {
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import {
  CHANNEL_CLUSTER_ENTER_SCALE,
  CHANNEL_CLUSTER_EXIT_SCALE,
  buildChannelClusters,
  clusterSuppressedChannelIds,
  clusterSuppressedNodeIds,
} from "./spatialClustering";
import { buildWidgetOverviewClusters } from "./widgetOverviewClusters";
import {
  MIN_SCALE,
  getViewportWorldBbox,
  bboxOverlaps,
  projectFisheye,
  type WorldBbox,
} from "./spatialGeometry";

export function useSpatialDragViewport(args: Record<string, any>) {
  const {
    nodes,
    camera,
    cameraRef,
    updateNode,
    setDraggingNodeId,
    setActivatedTileId,
    pointerToWorld,
    diving,
    dragEnabled,
    manualBotDragRef,
    viewportSize,
    cameraMoving,
    lensEngaged,
    focalScreen,
    lensRadius,
    wellPos,
    channelsById,
    activityByChannelId,
    channelClusterMode,
    widgetSatellitesByClusterId: _unusedWidgetSatellitesByClusterId,
    botsReduced,
  } = args;
  // dnd-kit sensor with a modest activation distance so exploratory clicks
  // and tiny pointer drift pan/select space instead of immediately moving a
  // nearby tile.
  // Split sensors so mouse vs touch can have different activation gates.
  // Mouse: 8px movement = drag (current behavior).
  // Touch: 350ms long-press, max 8px wobble during the press = drag arms.
  // This stops accidental tile drags during a finger-swipe pan on mobile —
  // the user must intentionally hold a tile to start moving it. Keeps the
  // background-long-press radial menu unaffected because that listener is
  // scoped to the viewport background (not delegated through dnd-kit).
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 350, tolerance: 8 } }),
  );

  const handleDragStart = useCallback((e: DragStartEvent) => {
    setDraggingNodeId(String(e.active.id));
    // Reposition cancels iframe activation: dragging is a "manage the tile"
    // gesture, not "interact with its contents."
    setActivatedTileId(null);
  }, []);

  const handleDragEnd = useCallback(
    (e: DragEndEvent) => {
      setDraggingNodeId(null);
      const node = (nodes ?? []).find((n: any) => n.id === e.active.id);
      if (!node) return;
      const scale = cameraRef.current.scale;
      // dnd-kit reports screen-pixel deltas; world delta = screen / scale.
      const dx = e.delta.x / scale;
      const dy = e.delta.y / scale;
      if (dx === 0 && dy === 0) return;
      updateNode.mutate({
        nodeId: node.id,
        body: { world_x: node.world_x + dx, world_y: node.world_y + dy },
      });
    },
    [nodes, updateNode],
  );

  const handleBotPointerDown = useCallback(
    (node: SpatialNode, e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.button !== 0 || diving) return;
      if (!dragEnabled) return;
      const world = pointerToWorld(e.clientX, e.clientY);
      if (!world) return;
      e.preventDefault();
      e.stopPropagation();
      setDraggingNodeId(node.id);
      setActivatedTileId(null);
      manualBotDragRef.current = {
        nodeId: node.id,
        pointerId: e.pointerId,
        grabDx: world.x - node.world_x,
        grabDy: world.y - node.world_y,
        currentX: node.world_x,
        currentY: node.world_y,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [diving, dragEnabled, pointerToWorld],
  );

  const handleBotPointerMove = useCallback(
    (node: SpatialNode, e: ReactPointerEvent<HTMLDivElement>) => {
      const drag = manualBotDragRef.current;
      if (!drag || drag.nodeId !== node.id || drag.pointerId !== e.pointerId) return;
      const world = pointerToWorld(e.clientX, e.clientY);
      if (!world) return;
      e.preventDefault();
      e.stopPropagation();
      drag.currentX = world.x - drag.grabDx;
      drag.currentY = world.y - drag.grabDy;
      e.currentTarget.style.left = `${drag.currentX}px`;
      e.currentTarget.style.top = `${drag.currentY}px`;
    },
    [pointerToWorld],
  );

  const handleBotPointerUp = useCallback(
    (node: SpatialNode, e: ReactPointerEvent<HTMLDivElement>) => {
      const drag = manualBotDragRef.current;
      if (!drag || drag.nodeId !== node.id || drag.pointerId !== e.pointerId) return;
      e.preventDefault();
      e.stopPropagation();
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* already released */
      }
      setDraggingNodeId(null);
      manualBotDragRef.current = null;
      if (drag.currentX !== node.world_x || drag.currentY !== node.world_y) {
        updateNode.mutate({
          nodeId: node.id,
          body: { world_x: drag.currentX, world_y: drag.currentY },
        });
      } else {
        e.currentTarget.style.left = `${node.world_x}px`;
        e.currentTarget.style.top = `${node.world_y}px`;
      }
    },
    [updateNode],
  );

  // Viewport bounds in WORLD coordinates, expanded by a 1-viewport margin on
  // each side. Tiles whose `world_*` rectangle intersects this box are
  // considered "in viewport" and get a live iframe; others render the static
  // body. Margin lets the user pan a viewport away without remounting.
  const viewportWorldBounds = useMemo(() => {
    if (viewportSize.w === 0 || viewportSize.h === 0) return null;
    const visW = viewportSize.w / camera.scale;
    const visH = viewportSize.h / camera.scale;
    const visX = -camera.x / camera.scale;
    const visY = -camera.y / camera.scale;
    return {
      x: visX - visW,
      y: visY - visH,
      w: visW * 3,
      h: visH * 3,
    };
  }, [camera.x, camera.y, camera.scale, viewportSize.w, viewportSize.h]);

  const isInViewport = useCallback(
    (n: SpatialNode) => {
      if (!viewportWorldBounds) return false;
      const v = viewportWorldBounds;
      return (
        n.world_x + n.world_w > v.x &&
        n.world_x < v.x + v.w &&
        n.world_y + n.world_h > v.y &&
        n.world_y < v.y + v.h
      );
    },
    [viewportWorldBounds],
  );

  // Tight viewport bbox in world coords used by SVG-rendering layers
  // (MovementHistory, ConnectionLine, MovementTrace) and the halo culler.
  // 200px screen-pixel overdraw so partial-edge content still renders.
  // Distinct from `viewportWorldBounds` (3x viewport) which gates iframe
  // mounting — that one's generous because remounting iframes is expensive;
  // for SVG clipping we want the tightest bbox that still hides edge clips.
  const viewportBbox = useMemo<WorldBbox | undefined>(() => {
    if (viewportSize.w === 0 || viewportSize.h === 0) return undefined;
    return getViewportWorldBbox(camera, viewportSize, 200);
  }, [camera, viewportSize]);
  const foregroundBbox = useMemo<WorldBbox | undefined>(() => {
    if (viewportSize.w === 0 || viewportSize.h === 0) return undefined;
    return getViewportWorldBbox(camera, viewportSize, 800);
  }, [camera, viewportSize]);
  const nodeInForeground = useCallback(
    (node: SpatialNode) => {
      if (!foregroundBbox) return true;
      return bboxOverlaps(
        {
          minX: node.world_x,
          minY: node.world_y,
          maxX: node.world_x + node.world_w,
          maxY: node.world_y + node.world_h,
        },
        foregroundBbox,
      );
    },
    [foregroundBbox],
  );
  const ambientZoom = camera.scale;
  const interactiveZoom = cameraMoving ? Math.min(camera.scale, 0.99) : camera.scale;

  const nowWellLens =
    lensEngaged && focalScreen
      ? projectFisheye(wellPos.x, wellPos.y, camera, focalScreen, lensRadius)
      : null;

  const channelClusters = useMemo(
    () => buildChannelClusters({
      nodes: nodes ?? [],
      channelsById,
      activityByChannelId,
      camera,
      enabled: channelClusterMode,
    }),
    [nodes, channelsById, activityByChannelId, camera, channelClusterMode],
  );
  const clusteredChannelNodeIds = useMemo(
    () => clusterSuppressedNodeIds(channelClusters),
    [channelClusters],
  );
  const clusteredChannelIds = useMemo(
    () => clusterSuppressedChannelIds(channelClusters),
    [channelClusters],
  );
  const maxClusterTokens = useMemo(
    () => channelClusters.reduce((max, cluster) => Math.max(max, cluster.totalTokens), 0),
    [channelClusters],
  );
  const widgetOverviewOpacity = channelClusterMode
    ? Math.max(0.16, Math.min(0.62, (camera.scale - MIN_SCALE) / (CHANNEL_CLUSTER_EXIT_SCALE - MIN_SCALE) * 0.62))
    : 1;
  const widgetSatellitesByClusterId = useMemo(() => {
    const map = new Map<string, SpatialNode[]>();
    if (!channelClusterMode) return map;
    const clusterByChannelId = new Map<string, string>();
    for (const cluster of channelClusters) {
      for (const member of cluster.members) {
        clusterByChannelId.set(member.channel.id, cluster.id);
      }
    }
    for (const node of nodes ?? []) {
      const sourceChannelId = node.pin?.source_channel_id;
      if (!sourceChannelId) continue;
      const clusterId = clusterByChannelId.get(sourceChannelId);
      if (!clusterId) continue;
      const list = map.get(clusterId) ?? [];
      list.push(node);
      map.set(clusterId, list);
    }
    return map;
  }, [channelClusterMode, channelClusters, nodes]);
  const satellitedWidgetNodeIds = useMemo(() => {
    const out = new Set<string>();
    for (const list of widgetSatellitesByClusterId.values()) {
      for (const node of list) out.add(node.id);
    }
    return out;
  }, [widgetSatellitesByClusterId]);
  const standaloneWidgetClusters = useMemo(
    () => buildWidgetOverviewClusters({
      nodes: nodes ?? [],
      camera,
      excludedNodeIds: satellitedWidgetNodeIds,
      enabled: channelClusterMode,
    }),
    [nodes, camera, satellitedWidgetNodeIds, channelClusterMode],
  );



  return {
    sensors,
    handleDragStart,
    handleDragEnd,
    handleBotPointerDown,
    handleBotPointerMove,
    handleBotPointerUp,
    viewportBbox,
    foregroundBbox,
    nodeInForeground,
    isInViewport,
    ambientZoom,
    interactiveZoom,
    nowWellLens,
    channelClusters,
    clusteredChannelNodeIds,
    clusteredChannelIds,
    maxClusterTokens,
    widgetOverviewOpacity,
    widgetSatellitesByClusterId,
    satellitedWidgetNodeIds,
    standaloneWidgetClusters,
  };
}
