import { useEffect, useMemo, useState } from "react";
import type React from "react";
import { DndContext } from "@dnd-kit/core";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import { widgetPinHref } from "../../lib/hubRoutes";
import { BotTile, ManualBotNode } from "./BotNode";
import { BloatSatellite } from "./BloatSatellite";
import { ChannelClusterMarker } from "./ChannelClusterMarker";
import { ChannelTile } from "./ChannelTile";
import { ConnectionLineLayer } from "./ConnectionLineLayer";
import DailyHealthLandmark from "./DailyHealthLandmark";
import { DraggableNode } from "./DraggableNode";
import { LandmarkWrapper } from "./LandmarkWrapper";
import { MemoryObservatory } from "./MemoryObservatory";
import { MovementHistoryLayer } from "./MovementHistoryLayer";
import { MovementTraceLayer } from "./MovementTraceLayer";
import { NowWell } from "./NowWell";
import { ScheduleSatelliteLayer } from "./ScheduleSatelliteLayer";
import { SpatialAttentionSignal } from "./SpatialAttentionLayer";
import { SpatialMissionLayer } from "./SpatialMissionLayer";
import { buildSpatialObjectBrief } from "./SpatialObjectBrief";
import { ObjectStatusPill, mapCueIntent } from "./SpatialObjectStatus";
import { TaskDefinitionTile } from "./TaskDefinitionTile";
import { UpcomingFirePulse } from "./UpcomingFirePulse";
import { UpcomingTile } from "./UpcomingTile";
import { UsageDensityLayer } from "./UsageDensityLayer";
import { WidgetClusterMarker } from "./WidgetClusterMarker";
import { WidgetTile } from "./WidgetTile";
import { definitionOrbit } from "./spatialDefinitionsOrbit";
import {
  ATTENTION_HUB_X,
  ATTENTION_HUB_Y,
  HEALTH_SUMMARY_X,
  HEALTH_SUMMARY_Y,
  MEMORY_OBSERVATORY_X,
  MEMORY_OBSERVATORY_Y,
  WELL_R_MAX,
  WELL_X,
  WELL_Y,
  WELL_Y_SQUASH,
  projectFisheye,
} from "./spatialGeometry";
import { upcomingOrbit, upcomingReactKey } from "./spatialActivity";
import { AttentionHubLandmark, OriginMarker } from "./SpatialCanvasLandmarks";
import { SpatialActionCueLayer } from "./SpatialActionCues";
import { CHANNEL_CLUSTER_FOCUS_SCALE } from "./spatialClustering";

const DIVE_MS = 300;

type SpatialCanvasWorldProps = Record<string, any> & {
  setHoveredNodeId: React.Dispatch<React.SetStateAction<any>>;
  setSelectedSpatialObject: React.Dispatch<React.SetStateAction<any>>;
  setSelectedAttentionId: React.Dispatch<React.SetStateAction<any>>;
  setDraggingNodeId: React.Dispatch<React.SetStateAction<any>>;
  setActivatedTileId: React.Dispatch<React.SetStateAction<any>>;
  setMemorySelection: React.Dispatch<React.SetStateAction<any>>;
  setContextMenu: React.Dispatch<React.SetStateAction<any>>;
  navigate: (to: string, options?: any) => void;
};

export function SpatialCanvasWorld(props: SpatialCanvasWorldProps) {
  const {
    sensors,
    handleDragStart,
    handleDragEnd,
    worldRef,
    worldStyle,
    densityIntensity,
    nodes,
    densityWindow,
    densityCompare,
    densityAnimate,
    animationsEnabled,
    channelActivity,
    baselineChannelActivity,
    clusteredChannelIds,
    viewportBbox,
    connectionsEnabled,
    hoveredNodeId,
    trailsMode,
    interactiveZoom,
    missions,
    mapState,
    starboardObjects,
    selectedStarboardObject,
    highlightedActionCueId,
    camera,
    openStarboardHub,
    ambientZoom,
    interactionMode,
    wellPos,
    selectLandmark,
    flyToWell,
    tickedNow,
    nowWellLens,
    memoryObsPos,
    lensEngaged,
    focalScreen,
    lensRadius,
    setMemorySelection,
    attentionHubPos,
    activeAttentionCount,
    mapAttentionCount,
    attentionSignalsVisible,
    openStarboardAttention,
    openStarboardSmell,
    dailyHealthPos,
    openStarboardHealth,
    channelClusterMode,
    upcomingItems,
    upcomingSpreadByKey,
    taskDefinitions,
    diveToTaskDefinition,
    firePulses,
    dismissPulse,
    channelClusters,
    flyToWorldBounds,
    maxClusterTokens,
    widgetSatellitesByClusterId,
    widgetOverviewOpacity,
    setSelectedSpatialObject,
    setContextMenu,
    selectedSpatialObject,
    starboardOpen,
    diveToChannel,
    attentionByNodeId,
    setSelectedAttentionId,
    standaloneWidgetClusters,
    clusteredChannelNodeIds,
    draggingNodeId,
    nodeInForeground,
    channelsById,
    lensSettling,
    dragEnabled,
    setHoveredNodeId,
    iconByChannelId,
    botAvatarById,
    selectNode,
    botsVisible,
    botsReduced,
    handleBotPointerDown,
    handleBotPointerMove,
    handleBotPointerUp,
    navigate,
    canvasBackState,
    activatedTileId,
    handleActivate,
    isInViewport,
    setDraggingNodeId,
    setActivatedTileId,
    triggerLensSettle,
  } = props;
  const [clusterFocusNodeIds, setClusterFocusNodeIds] = useState<Set<string>>(() => new Set());
  useEffect(() => {
    if (clusterFocusNodeIds.size === 0) return;
    const timeout = window.setTimeout(() => setClusterFocusNodeIds(new Set()), 1600);
    return () => window.clearTimeout(timeout);
  }, [clusterFocusNodeIds]);
  const hoveredNode = hoveredNodeId ? (nodes ?? []).find((node: SpatialNode) => node.id === hoveredNodeId) : null;
  const hoveredState = hoveredNode ? mapState?.objects_by_node_id?.[hoveredNode.id] ?? null : null;
  const hoverCardAllowed = Boolean(
    hoveredNode
      && hoveredState
      && draggingNodeId !== hoveredNode.id
      && !channelClusterMode
      && interactiveZoom >= 0.65
      && (!starboardOpen || !selectedSpatialObject),
  );
  const [hoverCardNodeId, setHoverCardNodeId] = useState<string | null>(null);
  useEffect(() => {
    if (!hoverCardAllowed || !hoveredNode) {
      setHoverCardNodeId(null);
      return;
    }
    const id = window.setTimeout(() => setHoverCardNodeId(hoveredNode.id), 220);
    return () => window.clearTimeout(id);
  }, [hoverCardAllowed, hoveredNode?.id]);
  const hoverCardNode = hoverCardNodeId ? (nodes ?? []).find((node: SpatialNode) => node.id === hoverCardNodeId) : null;
  const hoverCardState = hoverCardNode ? mapState?.objects_by_node_id?.[hoverCardNode.id] ?? null : null;
  const selectedAnchor = buildSelectedAnchor({
    selectedSpatialObject,
    nodes,
    mapState,
    channelsById,
    wellPos,
    memoryObsPos,
    attentionHubPos,
    dailyHealthPos,
  });
  const suppressedCueObjectIds = useMemo(() => {
    if (!clusteredChannelNodeIds?.size) return undefined;
    return new Set(Array.from(clusteredChannelNodeIds, (nodeId) => `node-${nodeId}`));
  }, [clusteredChannelNodeIds]);

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
      <div ref={worldRef} data-testid="spatial-world" className="absolute inset-0" style={worldStyle}>
        <OriginMarker />
        {densityIntensity !== "off" && (
          <UsageDensityLayer
            nodes={nodes ?? []}
            intensity={densityIntensity}
            window={densityWindow}
            compare={densityCompare}
            animate={densityAnimate && animationsEnabled}
            currentGroups={channelActivity.data?.groups ?? []}
            baselineGroups={baselineChannelActivity.data?.groups ?? []}
            suppressedChannelIds={clusteredChannelIds}
            viewportBbox={viewportBbox}
          />
        )}
        {connectionsEnabled && (
          <ConnectionLineLayer
            nodes={nodes ?? []}
            hoveredNodeId={hoveredNodeId}
            suppressedChannelIds={clusteredChannelIds}
            viewportBbox={viewportBbox}
          />
        )}
        {trailsMode !== "off" && (
          <MovementHistoryLayer
            nodes={nodes ?? []}
            mode={trailsMode}
            hoveredNodeId={hoveredNodeId}
            scale={interactiveZoom}
            viewportBbox={viewportBbox}
          />
        )}
        <MovementTraceLayer nodes={nodes ?? []} viewportBbox={viewportBbox} />
        <SpatialMissionLayer
          missions={missions ?? []}
          nodes={nodes ?? []}
          scale={camera.scale}
          viewportBbox={viewportBbox}
          onOpenMissionControl={openStarboardHub}
        />
        {!channelClusterMode && (
          <ScheduleSatelliteLayer
            items={upcomingItems ?? []}
            nodes={nodes ?? []}
            zoom={interactiveZoom}
            tickedNow={tickedNow}
            connectionsEnabled={connectionsEnabled}
            suppressedChannelIds={clusteredChannelIds}
            viewportBbox={viewportBbox}
            navigate={navigate}
            canvasBackState={canvasBackState}
            lensEngaged={lensEngaged}
            focalScreen={focalScreen}
            lensRadius={lensRadius}
            camera={camera}
          />
        )}
        <LandmarkWrapper
          kind="now_well"
          scale={ambientZoom}
          interactionMode={interactionMode}
          fallbackX={WELL_X}
          fallbackY={WELL_Y}
          hitWidth={WELL_R_MAX * 2}
          hitHeight={WELL_R_MAX * WELL_Y_SQUASH * 2}
        >
          <div
            data-tile-kind="landmark"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              selectLandmark("now_well", wellPos.x, wellPos.y);
            }}
            onDoubleClick={(e) => {
              e.stopPropagation();
              flyToWell();
            }}
          >
            <NowWell
              tickedNow={tickedNow}
              zoom={ambientZoom}
              lens={nowWellLens}
            />
          </div>
        </LandmarkWrapper>
        <LandmarkWrapper
          kind="memory_observatory"
          scale={ambientZoom}
          interactionMode={interactionMode}
          fallbackX={MEMORY_OBSERVATORY_X}
          fallbackY={MEMORY_OBSERVATORY_Y}
          hitWidth={1240}
          hitHeight={920}
          style={{ zIndex: 4 }}
        >
          <div
            data-tile-kind="landmark"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              selectLandmark("memory_observatory", memoryObsPos.x, memoryObsPos.y);
            }}
          >
            <MemoryObservatory
              zoom={ambientZoom}
              lens={
                lensEngaged && focalScreen
                  ? projectFisheye(memoryObsPos.x, memoryObsPos.y, camera, focalScreen, lensRadius)
                  : null
              }
              onInspect={setMemorySelection}
            />
          </div>
        </LandmarkWrapper>
        <LandmarkWrapper
          kind="attention_hub"
          scale={ambientZoom}
          interactionMode={interactionMode}
          fallbackX={ATTENTION_HUB_X}
          fallbackY={ATTENTION_HUB_Y}
          hitWidth={220}
          hitHeight={220}
        >
          <div
            data-tile-kind="landmark"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              selectLandmark("attention_hub", attentionHubPos.x, attentionHubPos.y);
            }}
            onDoubleClick={(e) => {
              e.stopPropagation();
              openStarboardAttention();
            }}
          >
            <AttentionHubLandmark
              activeCount={activeAttentionCount}
              mappedCount={mapAttentionCount}
              signalsVisible={attentionSignalsVisible}
              zoom={ambientZoom}
              onOpen={() => openStarboardAttention()}
            />
          </div>
        </LandmarkWrapper>
        <BloatSatellite hubX={attentionHubPos.x} hubY={attentionHubPos.y} onOpen={openStarboardSmell} />
        <LandmarkWrapper
          kind="daily_health"
          scale={ambientZoom}
          interactionMode={interactionMode}
          fallbackX={HEALTH_SUMMARY_X}
          fallbackY={HEALTH_SUMMARY_Y}
          hitWidth={180}
          hitHeight={180}
        >
          <div
            data-tile-kind="landmark"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              selectLandmark("daily_health", dailyHealthPos.x, dailyHealthPos.y);
            }}
            onDoubleClick={(e) => {
              e.stopPropagation();
              openStarboardHealth();
            }}
          >
            <DailyHealthLandmark
              zoom={ambientZoom}
              onOpen={openStarboardHealth}
            />
          </div>
        </LandmarkWrapper>
        {!channelClusterMode && (upcomingItems ?? []).map((item: any) => {
          const itemKey = upcomingReactKey(item);
          const spread = upcomingSpreadByKey.get(itemKey) ?? { index: 0, count: 1 };
          const orbit = upcomingOrbit(item, tickedNow, spread, wellPos);
          const lens =
            lensEngaged && focalScreen
              ? projectFisheye(orbit.x, orbit.y, camera, focalScreen, lensRadius)
              : null;
          return (
            <UpcomingTile
              key={itemKey}
              item={item}
              zoom={interactiveZoom}
              tickedNow={tickedNow}
              spread={spread}
              well={wellPos}
              extraScale={lens?.sizeFactor ?? 1}
              lens={lens}
            />
          );
        })}
        {!channelClusterMode && taskDefinitions.map((task: any, idx: number) => {
          const orbit = definitionOrbit(task.id, taskDefinitions.length, idx, wellPos);
          const lens =
            lensEngaged && focalScreen
              ? projectFisheye(orbit.x, orbit.y, camera, focalScreen, lensRadius)
              : null;
          return (
            <TaskDefinitionTile
              key={task.id}
              task={task}
              zoom={interactiveZoom}
              worldX={orbit.x}
              worldY={orbit.y}
              lens={lens}
              onDive={diveToTaskDefinition}
            />
          );
        })}
        {!channelClusterMode && firePulses.map((pulse: any) => {
          const lens =
            lensEngaged && focalScreen
              ? projectFisheye(pulse.x, pulse.y, camera, focalScreen, lensRadius)
              : null;
          return (
            <UpcomingFirePulse
              key={pulse.id}
              x={pulse.x}
              y={pulse.y}
              color={pulse.color}
              lens={lens}
              onDone={() => dismissPulse(pulse.id)}
            />
          );
        })}
        {channelClusters.map((cluster: any) => {
          const winnerNode = cluster.winner.node;
          return (
            <div
              key={cluster.id}
              className="absolute"
              style={{
                left: winnerNode.world_x,
                top: winnerNode.world_y,
                width: winnerNode.world_w,
                height: winnerNode.world_h,
                zIndex: 30 + winnerNode.z_index,
              }}
            >
              <ChannelClusterMarker
                cluster={cluster}
                zoom={interactiveZoom}
                showActivityGlow={densityIntensity !== "off"}
                maxClusterTokens={maxClusterTokens}
                widgetCount={widgetSatellitesByClusterId.get(cluster.id)?.length ?? 0}
                widgetOpacity={widgetOverviewOpacity}
                cueSummary={clusterCueSummary(cluster, mapState)}
                onFocus={() => {
                  setSelectedSpatialObject(null);
                  setContextMenu(null);
                  setClusterFocusNodeIds(new Set(cluster.members.map((member: any) => member.node.id)));
                  flyToWorldBounds(cluster.worldBounds, CHANNEL_CLUSTER_FOCUS_SCALE, CHANNEL_CLUSTER_FOCUS_SCALE);
                }}
              />
              {attentionSignalsVisible && (
                <SpatialAttentionSignal
                  items={cluster.members.flatMap((member: any) => attentionByNodeId.get(member.node.id) ?? [])}
                  scale={camera.scale}
                  onSelect={openStarboardAttention}
                />
              )}
            </div>
          );
        })}
        {standaloneWidgetClusters.map((cluster: any) => (
          <div
            key={cluster.id}
            className="absolute"
            style={{
              left: cluster.worldX - 43,
              top: cluster.worldY - 43,
              width: 86,
              height: 86,
              zIndex: 1,
            }}
          >
            <WidgetClusterMarker
              count={cluster.nodes.length}
              zoom={interactiveZoom}
              opacity={widgetOverviewOpacity}
            />
            {attentionSignalsVisible && (
              <SpatialAttentionSignal
                items={cluster.nodes.flatMap((node: SpatialNode) => attentionByNodeId.get(node.id) ?? [])}
                scale={camera.scale}
                onSelect={openStarboardAttention}
              />
            )}
          </div>
        ))}
        {(nodes ?? []).map((node: SpatialNode) => {
          if (node.channel_id && clusteredChannelNodeIds.has(node.id)) return null;
          if (channelClusterMode && node.bot_id) return null;
          if (channelClusterMode && node.pin) return null;
          if (draggingNodeId !== node.id && !nodeInForeground(node)) return null;
          const lens =
            lensEngaged && focalScreen
              ? projectFisheye(
                  node.world_x + node.world_w / 2,
                  node.world_y + node.world_h / 2,
                  camera,
                  focalScreen,
                  lensRadius,
                )
              : null;
          if (node.channel_id) {
            const channel = channelsById.get(node.channel_id);
            if (!channel) return null;
            return (
              <DraggableNode
                key={node.id}
                node={node}
                scale={camera.scale}
                isDragging={draggingNodeId === node.id}
                diving={props.diving}
                lens={lens}
                lensSettling={lensSettling}
                dragEnabled={dragEnabled}
                onHoverChange={(hovered) =>
                  setHoveredNodeId((curr: any) => {
                    if (hovered) return node.id;
                    return curr === node.id ? null : curr;
                  })
                }
              >
                <ChannelTile
                  channel={channel}
                  icon={iconByChannelId.get(channel.id) ?? null}
                  zoom={interactiveZoom}
                  extraScale={lens?.sizeFactor ?? 1}
                  botAvatarById={botAvatarById}
                  workState={mapState?.objects_by_node_id?.[node.id] ?? null}
                  onSelect={() => selectNode("channel", node)}
                  onDive={() =>
                    diveToChannel(channel.id, {
                      x: node.world_x,
                      y: node.world_y,
                      w: node.world_w,
                      h: node.world_h,
                    })
                  }
                />
              </DraggableNode>
            );
          }
          if (node.bot_id) {
            if (!botsVisible) return null;
            const botName = node.bot?.display_name || node.bot?.name || node.bot_id;
            return (
              <ManualBotNode
                key={node.id}
                node={node}
                isDragging={draggingNodeId === node.id}
                diving={props.diving}
                dragEnabled={dragEnabled}
                lens={draggingNodeId === node.id ? null : lens}
                lensSettling={lensSettling}
                reduced={botsReduced}
                onPointerDown={(e) => handleBotPointerDown(node, e)}
                onPointerMove={(e) => handleBotPointerMove(node, e)}
                onPointerUp={(e) => handleBotPointerUp(node, e)}
                onHoverChange={(hovered) =>
                  setHoveredNodeId((curr: any) => {
                    if (hovered) return node.id;
                    return curr === node.id ? null : curr;
                  })
                }
                onClick={() => selectNode("bot", node)}
                onDoubleClick={() => {}}
              >
                <BotTile
                  name={botName}
                  botId={node.bot_id}
                  avatarEmoji={node.bot?.avatar_emoji ?? null}
                  zoom={interactiveZoom}
                  reduced={botsReduced}
                  workState={mapState?.objects_by_node_id?.[node.id] ?? null}
                />
              </ManualBotNode>
            );
          }
          if (!node.pin) return null;
          const isFramelessGame =
            node.pin.tool_name?.startsWith("core/game_") ?? false;
          const useScopedGrabber = isFramelessGame && interactiveZoom >= 0.6;
          return (
            <DraggableNode
              key={node.id}
              node={node}
              scale={camera.scale}
              isDragging={draggingNodeId === node.id}
              diving={props.diving}
              lens={lens}
              lensSettling={lensSettling}
              dragEnabled={dragEnabled}
              activatorMode={useScopedGrabber ? "scoped" : "full"}
              onScopedDragStart={() => {
                setDraggingNodeId(node.id);
                setActivatedTileId(null);
                if (lensEngaged) {
                  props.setLensEngaged(false);
                  triggerLensSettle();
                }
              }}
              onScopedDragEnd={() => {
                setDraggingNodeId((curr: any) => (curr === node.id ? null : curr));
              }}
              onHoverChange={(hovered) =>
                setHoveredNodeId((curr: any) => {
                  if (hovered) return node.id;
                  return curr === node.id ? null : curr;
                })
              }
              onDoubleClick={() => navigate(widgetPinHref(node.pin!.id), { state: canvasBackState })}
            >
              <WidgetTile
                pin={node.pin}
                zoom={interactiveZoom}
                extraScale={lens?.sizeFactor ?? 1}
                inViewport={isInViewport(node)}
                activated={activatedTileId === node.id}
                nodeId={node.id}
                workState={mapState?.objects_by_node_id?.[node.id] ?? null}
                onActivate={handleActivate}
                onSelect={() => selectNode("widget", node)}
              />
            </DraggableNode>
          );
        })}
        {hoverCardNode && hoverCardState && (
          <ObjectHoverCard
            node={hoverCardNode}
            state={hoverCardState}
            scale={camera.scale}
          />
        )}
        {(nodes ?? []).map((node: SpatialNode) => {
          const items = attentionByNodeId.get(node.id);
          if (!items?.length) return null;
          if (node.channel_id && clusteredChannelNodeIds.has(node.id)) return null;
          if (channelClusterMode && node.bot_id) return null;
          if (channelClusterMode && node.pin) return null;
          if (draggingNodeId !== node.id && !nodeInForeground(node)) return null;
          const lens =
            lensEngaged && focalScreen
              ? projectFisheye(
                  node.world_x + node.world_w / 2,
                  node.world_y + node.world_h / 2,
                  camera,
                  focalScreen,
                  lensRadius,
                )
              : null;
          const botScale = node.bot_id && botsReduced ? 0.82 : 1;
          const lensTransform = lens
            ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})`
            : "";
          const reduceTransform = botScale !== 1 ? `scale(${botScale})` : "";
          const transformStack = [lensTransform, reduceTransform].filter(Boolean).join(" ");
          return (
            <div
              key={`attention-overlay-${node.id}`}
              className="pointer-events-none absolute"
              style={{
                left: node.world_x,
                top: node.world_y,
                width: node.world_w,
                height: node.world_h,
                zIndex: 5000,
                transform: transformStack || undefined,
                transformOrigin: "center center",
                transition: lensSettling ? `transform ${DIVE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)` : "transform 120ms",
                contain: "layout style",
              }}
            >
              {attentionSignalsVisible && (
                <SpatialAttentionSignal
                  items={items}
                  scale={camera.scale * (lens?.sizeFactor ?? 1) * botScale}
                  onSelect={(item: any) => {
                    if (node.channel_id) selectNode("channel", node);
                    else if (node.bot_id) selectNode("bot", node);
                    else if (node.pin) selectNode("widget", node);
                    else if (node.landmark_kind) selectLandmark(node.landmark_kind, node.world_x + node.world_w / 2, node.world_y + node.world_h / 2);
                    setSelectedAttentionId(item.id);
                  }}
                />
              )}
            </div>
          );
        })}
        <SpatialActionCueLayer
          objects={starboardObjects ?? []}
          selectedObjectId={selectedStarboardObject?.id ?? null}
          highlightedObjectId={highlightedActionCueId ?? null}
          scale={camera.scale}
          suppressedObjectIds={suppressedCueObjectIds}
        />
        {selectedAnchor && (
          <SelectedObjectAnchor
            x={selectedAnchor.x}
            y={selectedAnchor.y}
            worldW={selectedAnchor.worldW}
            worldH={selectedAnchor.worldH}
            label={selectedAnchor.label}
            showLabel={selectedAnchor.showLabel}
            tone={selectedAnchor.tone}
            scale={camera.scale}
          />
        )}
        {clusterFocusNodeIds.size > 0 && (nodes ?? []).map((node: SpatialNode) => (
          clusterFocusNodeIds.has(node.id)
            ? <ClusterFocusCue key={`cluster-focus-${node.id}`} node={node} scale={camera.scale} />
            : null
        ))}
      </div>
    </DndContext>
  );
}

function buildSelectedAnchor({
  selectedSpatialObject,
  nodes,
  mapState,
  channelsById,
  wellPos,
  memoryObsPos,
  attentionHubPos,
  dailyHealthPos,
}: {
  selectedSpatialObject: any;
  nodes: SpatialNode[] | undefined;
  mapState: any;
  channelsById: Map<string, any>;
  wellPos: { x: number; y: number };
  memoryObsPos: { x: number; y: number };
  attentionHubPos: { x: number; y: number };
  dailyHealthPos: { x: number; y: number };
}) {
  if (!selectedSpatialObject) return null;
  if (selectedSpatialObject.kind === "channel" || selectedSpatialObject.kind === "bot" || selectedSpatialObject.kind === "widget") {
    const node = (nodes ?? []).find((item) => item.id === selectedSpatialObject.nodeId);
    if (!node) return null;
    const state = mapState?.objects_by_node_id?.[node.id] ?? null;
    const channel = node.channel_id ? channelsById.get(node.channel_id) : null;
    const label =
      state?.label
      ?? (channel ? `#${channel.name}` : null)
      ?? node.bot?.display_name
      ?? node.bot?.name
      ?? node.bot_id
      ?? node.pin?.panel_title
      ?? node.pin?.display_label
      ?? node.pin?.tool_name
      ?? "Selected";
    return {
      x: node.world_x + node.world_w / 2,
      y: node.world_y + node.world_h / 2,
      worldW: node.world_w,
      worldH: node.world_h,
      label,
      showLabel: false,
      tone: selectedTone(state),
    };
  }
  if (selectedSpatialObject.kind !== "landmark") return null;
  const landmark = selectedSpatialObject.id === "memory_observatory"
    ? { x: memoryObsPos.x, y: memoryObsPos.y, label: "Memory Observatory" }
    : selectedSpatialObject.id === "attention_hub"
      ? { x: attentionHubPos.x, y: attentionHubPos.y, label: "Attention Hub" }
      : selectedSpatialObject.id === "daily_health"
        ? { x: dailyHealthPos.x, y: dailyHealthPos.y, label: "Daily Health" }
        : { x: wellPos.x, y: wellPos.y, label: "Now Well" };
  const state = mapState?.objects?.find((item: any) => item.kind === "landmark" && item.target_id === selectedSpatialObject.id) ?? null;
  return { ...landmark, worldW: 180, worldH: 120, showLabel: true, tone: selectedTone(state) };
}

function selectedTone(state: any): "danger" | "warning" | "active" | "muted" {
  if (mapCueIntent(state) === "investigate" || state?.status === "error" || state?.severity === "critical" || state?.severity === "error") return "danger";
  if (state?.status === "warning" || state?.severity === "warning") return "warning";
  if (mapCueIntent(state) === "next" || state?.status === "running" || state?.status === "scheduled" || state?.status === "active") return "active";
  return "muted";
}

function clusterCueSummary(cluster: any, mapState: any): string | null {
  const counts = { investigate: 0, next: 0, recent: 0 };
  for (const member of cluster.members ?? []) {
    const state = mapState?.objects_by_node_id?.[member.node.id] ?? null;
    const intent = mapCueIntent(state);
    if (intent === "investigate" || intent === "next" || intent === "recent") counts[intent] += 1;
  }
  if (counts.investigate) return `${counts.investigate} to inspect`;
  if (counts.next) return `${counts.next} next`;
  if (counts.recent) return `${counts.recent} recent`;
  return null;
}

function SelectedObjectAnchor({
  x,
  y,
  worldW,
  worldH,
  label,
  showLabel,
  tone,
  scale,
}: {
  x: number;
  y: number;
  worldW: number;
  worldH: number;
  label: string;
  showLabel: boolean;
  tone: "danger" | "warning" | "active" | "muted";
  scale: number;
}) {
  const inverseScale = 1 / Math.max(scale, 0.2);
  const width = Math.max(74, Math.min(220, worldW * scale + 24));
  const height = Math.max(54, Math.min(160, worldH * scale + 24));
  const toneClass =
    tone === "danger"
      ? "ring-danger/45 bg-danger/[0.045] text-danger"
      : tone === "warning"
        ? "ring-warning/40 bg-warning/[0.045] text-warning"
        : tone === "active"
          ? "ring-accent/45 bg-accent/[0.055] text-accent"
          : "ring-accent/35 bg-accent/[0.04] text-accent";
  return (
    <div
      data-spatial-selected-anchor="true"
      className="pointer-events-none absolute z-[4998]"
      style={{
        left: x,
        top: y,
        transform: `translate(-50%, -50%) scale(${inverseScale})`,
        transformOrigin: "center center",
      }}
    >
      <div
        className={`rounded-md ring-1 ring-offset-2 ring-offset-surface ${toneClass}`}
        style={{ width, height }}
      />
      {showLabel && (
        <div data-spatial-selected-anchor-label="true" className="absolute left-1/2 top-full mt-1 max-w-[220px] -translate-x-1/2 truncate rounded-md bg-surface-raised/90 px-2 py-1 text-xs font-medium text-text ring-1 ring-surface-border backdrop-blur">
          {label}
        </div>
      )}
    </div>
  );
}

function ClusterFocusCue({ node, scale }: { node: SpatialNode; scale: number }) {
  const inverseScale = 1 / Math.max(scale, 0.2);
  const width = Math.max(54, Math.min(180, node.world_w * scale + 18));
  const height = Math.max(44, Math.min(128, node.world_h * scale + 18));
  return (
    <div
      data-spatial-cluster-focus-cue="true"
      className="pointer-events-none absolute z-[4997]"
      style={{
        left: node.world_x + node.world_w / 2,
        top: node.world_y + node.world_h / 2,
        transform: `translate(-50%, -50%) scale(${inverseScale})`,
        transformOrigin: "center center",
      }}
    >
      <div
        className="rounded-md bg-accent/[0.035] ring-1 ring-accent/45 ring-offset-2 ring-offset-surface"
        style={{ width, height }}
      />
    </div>
  );
}

function ObjectHoverCard({ node, state, scale }: { node: SpatialNode; state: any; scale: number }) {
  const brief = buildSpatialObjectBrief(state);
  return (
    <div
      data-testid="spatial-object-hover-card"
      className="pointer-events-none absolute z-[70] w-[260px] rounded-md border border-surface-border bg-surface-raised/95 px-3 py-2 text-xs text-text shadow-[0_16px_40px_rgb(0_0_0/0.22)] backdrop-blur"
      style={{
        left: node.world_x + node.world_w / 2,
        top: node.world_y - 10,
        transform: `translate(-50%, -100%) scale(${1 / Math.max(scale, 0.2)})`,
        transformOrigin: "bottom center",
      }}
    >
      <div className="mb-1 flex min-w-0 items-center gap-2">
        <span className="truncate font-semibold">{state.label}</span>
        <ObjectStatusPill state={state} compact />
      </div>
      <div className="line-clamp-2 text-text-muted">{brief?.summary ?? brief?.headline ?? "No live map state attached."}</div>
    </div>
  );
}
