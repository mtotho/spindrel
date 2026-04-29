import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  DndContext,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  MessageCircle,
  Footprints,
  Plus,
  Maximize2,
  Home,
  ZoomIn,
  Link2,
  Settings,
  ExternalLink,
  Trash2,
  Locate,
  Move,
  Radar,
  MoreHorizontal,
  Bot,
  Box,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { useChannels } from "../../api/hooks/useChannels";
import { useDashboards, channelIdFromSlug } from "../../stores/dashboards";
import {
  landmarkPositionFromNodes,
  useSpatialNodes,
  useUpdateSpatialNode,
  useDeleteSpatialNode,
  type SpatialNode,
} from "../../api/hooks/useWorkspaceSpatial";
import { useWorkspaceAttention, useMarkAttentionResponded, isActiveAttentionItem, type WorkspaceAttentionItem } from "../../api/hooks/useWorkspaceAttention";
import { useWorkspaceMissions } from "../../api/hooks/useWorkspaceMissions";
import { useSpatialUpcomingActivity } from "../../api/hooks/useUpcomingActivity";
import { useUsageBreakdown } from "../../api/hooks/useUsage";
import { useBots } from "../../api/hooks/useBots";
import type { Channel } from "../../types/api";
import { ChannelTile } from "./ChannelTile";
import { ChannelClusterMarker } from "./ChannelClusterMarker";
import { WidgetTile } from "./WidgetTile";
import { WidgetClusterMarker } from "./WidgetClusterMarker";
import { NowWell } from "./NowWell";
import { UpcomingTile } from "./UpcomingTile";
import { TaskDefinitionTile } from "./TaskDefinitionTile";
import { definitionOrbit } from "./spatialDefinitionsOrbit";
import type { TasksResponse } from "../shared/TaskConstants";
import { UpcomingFirePulse } from "./UpcomingFirePulse";
import { ConnectionLineLayer } from "./ConnectionLineLayer";
import { MovementHistoryLayer } from "./MovementHistoryLayer";
import { UsageDensityLayer } from "./UsageDensityLayer";
import { UsageDensityChrome, loadStarboardStation, type StarboardObjectAction, type StarboardObjectItem, type StarboardStation } from "./UsageDensityChrome";
import { Minimap } from "./Minimap";
import { SpatialEdgeBeacons } from "./SpatialEdgeBeacons";
import { SpatialAttentionSignal, shouldSurfaceAttentionOnMap } from "./SpatialAttentionLayer";
import { DivePulseOverlay } from "./DivePulseOverlay";
import { SpatialContextMenu, type SpatialContextMenuItem } from "./SpatialContextMenu";
import { SpatialSelectionRail, type SpatialSelectionAction } from "./SpatialSelectionRail";
import { DraggableNode } from "./DraggableNode";
import { ManualBotNode, BotTile } from "./BotNode";
import {
  AddWidgetButton,
  CanvasStarfield,
} from "./SpatialCanvasChrome";
import { MovementTraceLayer } from "./MovementTraceLayer";
import { SpatialMissionLayer } from "./SpatialMissionLayer";
import type { SpatialInteractionMode } from "./spatialInteraction";
import {
  MemoryObservationPanel,
  MemoryObservatory,
  type MemoryObservationSelection,
} from "./MemoryObservatory";
import DailyHealthLandmark from "./DailyHealthLandmark";
import { LandmarkWrapper } from "./LandmarkWrapper";
import { BloatSatellite } from "./BloatSatellite";
import { buildWidgetOverviewClusters } from "./widgetOverviewClusters";
import { ChatSession } from "../chat/ChatSession";
import { SessionPickerOverlay } from "../chat/SessionPickerOverlay";
import {
  buildChannelSessionRoute,
  type ChannelSessionSurface,
} from "../../lib/channelSessionSurfaces";
import { useUIStore } from "../../stores/ui";
import { useDraftsStore } from "../../stores/drafts";
import { usePaletteOverrides } from "../../stores/paletteOverrides";
import { usePaletteActions } from "../../stores/paletteActions";
import {
  LayoutDashboard,
  Map as MapIcon,
  Sparkles,
  Brain,
  Target,
  Users as UsersIcon,
} from "lucide-react";
import {
  buildChannelSurfaceRoute,
  getChannelLastSurface,
} from "../../stores/channelLastSurface";
import { attentionDeckHref, widgetPinHref } from "../../lib/hubRoutes";
import { contextualNavigationState } from "../../lib/contextualNavigation";
import { SPATIAL_HANDOFF_KEY } from "../../lib/spatialHandoff";
import {
  CAMERA_STORAGE_KEY,
  CONNECTIONS_ENABLED_KEY,
  DEFAULT_CAMERA,
  DENSITY_ANIMATE_KEY,
  DENSITY_COMPARE_KEY,
  DENSITY_INTENSITY_KEY,
  DENSITY_WINDOW_KEY,
  BOTS_REDUCED_KEY,
  BOTS_VISIBLE_KEY,
  TRAILS_MODE_KEY,
  MINIMAP_VISIBLE_KEY,
  LANDMARK_BEACONS_VISIBLE_KEY,
  ATTENTION_SIGNALS_VISIBLE_KEY,
  DIVE_SCALE_THRESHOLD,
  DIVE_DWELL_MS,
  DIVE_VIEWPORT_MARGIN,
  LENS_NATIVE_FRACTION,
  LENS_SETTLE_MS,
  MAX_SCALE,
  MIN_SCALE,
  WELL_R_MAX,
  WELL_X,
  WELL_Y,
  WELL_Y_SQUASH,
  MEMORY_OBSERVATORY_X,
  MEMORY_OBSERVATORY_Y,
  ATTENTION_HUB_X,
  ATTENTION_HUB_Y,
  HEALTH_SUMMARY_X,
  HEALTH_SUMMARY_Y,
  type DensityIntensity,
  type DensityWindow,
  type TrailsMode,
  loadConnectionsEnabled,
  loadDensityAnimate,
  loadDensityCompare,
  loadDensityIntensity,
  loadDensityWindow,
  loadBotsReduced,
  loadBotsVisible,
  loadTrailsMode,
  loadMinimapVisible,
  loadLandmarkBeaconsVisible,
  loadAttentionSignalsVisible,
  clampCamera,
  loadStoredCamera,
  projectFisheye,
  getViewportWorldBbox,
  bboxOverlaps,
  type Camera,
  type WorldBbox,
} from "./spatialGeometry";
import { useIsMobile } from "../../hooks/useIsMobile";
import { useReducedMotion } from "../../hooks/useReducedMotion";
import {
  upcomingOrbitBucket,
  upcomingOrbit,
  upcomingIdentityKey,
  upcomingReactKey,
  upcomingTileColor,
} from "./spatialActivity";
import {
  CHANNEL_CLUSTER_ENTER_SCALE,
  CHANNEL_CLUSTER_EXIT_SCALE,
  buildChannelClusters,
  clusterSuppressedChannelIds,
  clusterSuppressedNodeIds,
} from "./spatialClustering";
import { isEmptySpaceClickGesture } from "./spatialCanvasPointer";
import { SpatialCanvasWorld } from "./SpatialCanvasWorld";
import { SpatialCanvasOverlays } from "./SpatialCanvasOverlays";
import { useSpatialSelectionRail } from "./useSpatialSelectionRail";
import { useSpatialContextMenu } from "./useSpatialContextMenu";
import { useSpatialStarboardModels } from "./useSpatialStarboardModels";
import { useSpatialCanvasData } from "./useSpatialCanvasData";
import { cameraTransform, useSpatialCamera } from "./useSpatialCamera";
import { useSpatialNavigation } from "./useSpatialNavigation";
import { useSpatialInteractions } from "./useSpatialInteractions";
import { useSpatialDragViewport } from "./useSpatialDragViewport";

/**
 * Backend-driven spatial canvas. Renders one tile per `WorkspaceSpatialNode`
 * row at its persisted `world_x` / `world_y` (assigned by the server via
 * golden-angle phyllotaxis on the row's `seed_index`). Pan with background
 * drag, zoom with wheel, drag tiles to reposition (committed via
 * `useUpdateSpatialNode`), double-click a channel tile to dive in.
 *
 * Used by `SpatialCanvasOverlay` (overlay mode, animate-then-close) and by
 * the desktop `/` route (no overlay wrapper). Both share React Query data
 * via the `["workspace-spatial-nodes"]` key.
 */

const DIVE_MS = 300;
const TILE_W = 220;
const TILE_H = 140;
const CAMERA_IDLE_COMMIT_MS = 140;
const CAMERA_MOVING_CLASS_MS = 520;

const DENSITY_WINDOW_HOURS: Record<DensityWindow, number> = {
  "24h": 24,
  "7d": 24 * 7,
  "30d": 24 * 30,
};

function isoHoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

interface SpatialCanvasProps {
  /** Called after the dive animation completes and `router.push` has fired.
   *  Used by the overlay to close itself a tick after the route paints. */
  onAfterDive?: () => void;
  /** Channel id to center the camera on first paint. Used by the overlay
   *  to do contextual-camera-on-open: opening Ctrl+Shift+Space from
   *  `/channels/:id` lands you on that tile rather than the last-saved
   *  camera. One-shot — fires once per mount, then is ignored. */
  initialFlyToChannelId?: string | null;
  /** Spatial node id to center the camera on first paint. Used by durable
   *  Mission Control links that jump to a bot or target tile. */
  initialFlyToNodeId?: string | null;
}

type SpatialSelection =
  | { kind: "channel"; nodeId: string }
  | { kind: "bot"; nodeId: string }
  | { kind: "widget"; nodeId: string }
  | { kind: "landmark"; id: "now_well" | "memory_observatory" | "attention_hub" | "daily_health" };

export function SpatialCanvas({ onAfterDive, initialFlyToChannelId, initialFlyToNodeId }: SpatialCanvasProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const canvasBackState = contextualNavigationState(`${location.pathname}${location.search}`, "Canvas");
  const [diving, setDiving] = useState(false);
  const mountedAtRef = useRef<number>(Date.now());
  const {
    nodes,
    nodesRef,
    wellPos,
    memoryObsPos,
    attentionHubPos,
    dailyHealthPos,
    attentionItems,
    missions,
    mapState,
    markAttentionResponded,
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
  } = useSpatialCanvasData();
  const attentionHubOpen = useUIStore((s) => s.attentionHubOpen);
  const closeAttentionHub = useUIStore((s) => s.closeAttentionHub);
  const [interactionMode, setInteractionMode] = useState<SpatialInteractionMode>("browse");
  const [selectedSpatialObject, setSelectedSpatialObject] = useState<SpatialSelection | null>(null);
  const [highlightedActionCueId, setHighlightedActionCueId] = useState<string | null>(null);
  const dragEnabled = interactionMode === "arrange";
  const updateNode = useUpdateSpatialNode();
  const deleteNode = useDeleteSpatialNode();

  useEffect(() => {
    if (!selectedSpatialObject) return;
    if (
      (selectedSpatialObject.kind === "channel" ||
        selectedSpatialObject.kind === "bot" ||
        selectedSpatialObject.kind === "widget") &&
      !(nodes ?? []).some((node) => node.id === selectedSpatialObject.nodeId)
    ) {
      setSelectedSpatialObject(null);
    }
  }, [nodes, selectedSpatialObject]);

  const openStarboard = useCallback(() => {
    setStarboardStation("objects");
    try {
      localStorage.setItem("spatial.starboard.activeTab", "objects");
    } catch {
      /* storage disabled */
    }
    setStarboardOpen(true);
  }, []);

  const openStarboardAttention = useCallback((item?: WorkspaceAttentionItem | null) => {
    if (item) setSelectedAttentionId(item.id);
    navigate(attentionDeckHref({ itemId: item?.id ?? null }), { state: canvasBackState });
    closeAttentionHub();
  }, [canvasBackState, closeAttentionHub, navigate]);
  const openStarboardLaunch = useCallback(() => {
    setCanvasLibraryOpen(true);
  }, []);
  const openStarboardHub = useCallback(() => {
    navigate(attentionDeckHref({ mode: "review" }), { state: canvasBackState });
  }, [canvasBackState, navigate]);
  const openStarboardObjects = useCallback(() => {
    openStarboard();
  }, [openStarboard]);
  const openStarboardHealth = useCallback(() => {
    openStarboard();
  }, [openStarboard]);
  const openStarboardSmell = useCallback(() => {
    openStarboard();
  }, [openStarboard]);

  useEffect(() => {
    if (!attentionHubOpen) return;
    openStarboardAttention();
  }, [attentionHubOpen, openStarboardAttention]);

  const handleAttentionReply = useCallback((item: WorkspaceAttentionItem) => {
    if (!item.channel_id) return;
    const channel = channelsById.get(item.channel_id);
    if (!channel) return;
    const draft = [
      `Re: ${item.title}`,
      "",
      item.message,
      "",
      "My response:",
    ].join("\n");
    useDraftsStore.getState().setDraftText(item.channel_id, draft);
    markAttentionResponded.mutate(item.id);
    setOpenBotChat({
      botId: channel.bot_id,
      botName: "Attention",
      channelId: channel.id,
      channelName: channel.name,
    });
  }, [channelsById, markAttentionResponded]);

  const {
    camera,
    viewportRef,
    worldRef,
    cameraRef,
    viewportRectRef,
    cameraMoving,
    viewportSize,
    scheduleCamera,
    flushCamera,
    pointerToWorld,
    zoomAroundPoint,
    fitAllNodes,
  } = useSpatialCamera({ diving, nodes: nodes ?? undefined });

  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const manualBotDragRef = useRef<{
    nodeId: string;
    pointerId: number;
    grabDx: number;
    grabDy: number;
    currentX: number;
    currentY: number;
  } | null>(null);
  // One activated widget tile at a time. Activation makes a widget tile
  // hand pointer events to its iframe; Esc / click on the canvas background
  // / dragging the tile / activating another tile deactivates.
  const [activatedTileId, setActivatedTileId] = useState<string | null>(null);
  // Hovered tile (for connection-line highlighting). Tracked at the canvas
  // level so layers under the tile map can react.
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [openBotChat, setOpenBotChat] = useState<{
    botId: string;
    botName: string;
    channelId: string;
    channelName: string;
  } | null>(null);
  const [selectedAttentionId, setSelectedAttentionId] = useState<string | null>(null);
  const [starboardOpen, setStarboardOpen] = useState(false);
  const [, setStarboardStation] = useState<StarboardStation>(loadStarboardStation);
  const [canvasLibraryOpen, setCanvasLibraryOpen] = useState(false);
  const [memorySelection, setMemorySelection] = useState<MemoryObservationSelection | null>(null);
  const [sessionPickerOpen, setSessionPickerOpen] = useState(false);

  useEffect(() => {
    if (starboardOpen) return;
    setPinPositionOverride(null);
  }, [starboardOpen]);

  // Mobile + reduced-motion gates. We disable the starfield + halo breathing
  // on mobile (especially iOS PWAs, where every continuous animation is a
  // GPU layer compounding the SVG-raster cost) and under the system
  // `prefers-reduced-motion: reduce` preference. Tile interaction, dive, and
  // trails are NOT animation-gated — those communicate state.
  const isMobile = useIsMobile();
  const reducedMotion = useReducedMotion();
  const animationsEnabled = !isMobile && !reducedMotion;

  // Token-usage density layer state. Defaults: subtle (on), 24h, channel-hued
  // (compare off), breathing on. Persisted to localStorage so the user's
  // preferred visual state survives reloads.
  const [densityIntensity, setDensityIntensity] = useState<DensityIntensity>(loadDensityIntensity);
  const [densityWindow, setDensityWindow] = useState<DensityWindow>(loadDensityWindow);
  const [densityCompare, setDensityCompare] = useState<boolean>(loadDensityCompare);
  const [densityAnimate, setDensityAnimate] = useState<boolean>(loadDensityAnimate);
  const activityAfter = useMemo(
    () => isoHoursAgo(DENSITY_WINDOW_HOURS[densityWindow]),
    [densityWindow],
  );
  const activityBefore = useMemo(() => new Date().toISOString(), [densityWindow]);
  const baselineAfter = useMemo(
    () => isoHoursAgo(DENSITY_WINDOW_HOURS[densityWindow] * 2),
    [densityWindow],
  );
  const baselineBefore = useMemo(
    () => isoHoursAgo(DENSITY_WINDOW_HOURS[densityWindow]),
    [densityWindow],
  );
  const channelActivity = useUsageBreakdown({
    group_by: "channel",
    after: activityAfter,
    before: activityBefore,
  });
  const baselineChannelActivity = useUsageBreakdown({
    group_by: "channel",
    after: baselineAfter,
    before: baselineBefore,
  }, { enabled: densityCompare });
  const activityByChannelId = useMemo(() => {
    const m = new Map<string, { tokens: number; calls: number }>();
    for (const group of channelActivity.data?.groups ?? []) {
      if (group.key) m.set(group.key, { tokens: group.tokens, calls: group.calls });
    }
    return m;
  }, [channelActivity.data]);
  const [channelClusterMode, setChannelClusterMode] = useState(
    () => cameraRef.current.scale < CHANNEL_CLUSTER_ENTER_SCALE,
  );
  useEffect(() => {
    setChannelClusterMode((enabled) => {
      if (enabled) return camera.scale <= CHANNEL_CLUSTER_EXIT_SCALE;
      return camera.scale < CHANNEL_CLUSTER_ENTER_SCALE;
    });
  }, [camera.scale]);
  // Connection-line layer (widget → source channel curves). On by default —
  // the relationship is most of the value of pinning a widget to the canvas.
  const [connectionsEnabled, setConnectionsEnabled] = useState<boolean>(loadConnectionsEnabled);
  const [botsVisible, setBotsVisible] = useState<boolean>(loadBotsVisible);
  const [botsReduced, setBotsReduced] = useState<boolean>(loadBotsReduced);
  const [trailsMode, setTrailsMode] = useState<TrailsMode>(loadTrailsMode);
  const [minimapVisible, setMinimapVisible] = useState<boolean>(loadMinimapVisible);
  const [landmarkBeaconsVisible, setLandmarkBeaconsVisible] = useState<boolean>(loadLandmarkBeaconsVisible);
  const [attentionSignalsVisible, setAttentionSignalsVisible] = useState<boolean>(loadAttentionSignalsVisible);
  // Right-click context menu — single instance at a time. `worldXY` is set
  // when the user right-clicks on the empty background so "Add widget here"
  // can drop the new pin at the click position rather than camera center.
  const [contextMenu, setContextMenu] = useState<{
    screenX: number;
    screenY: number;
    items: SpatialContextMenuItem[];
  } | null>(null);
  const [pinPositionOverride, setPinPositionOverride] = useState<{ x: number; y: number } | null>(null);

  // Persist chrome prefs on change. Single effect with all deps — localStorage
  // writes are sub-ms and these toggles fire at most a few times per session.
  useEffect(() => {
    try {
      localStorage.setItem(DENSITY_INTENSITY_KEY, densityIntensity);
      localStorage.setItem(DENSITY_WINDOW_KEY, densityWindow);
      localStorage.setItem(DENSITY_COMPARE_KEY, densityCompare ? "1" : "0");
      localStorage.setItem(DENSITY_ANIMATE_KEY, densityAnimate ? "1" : "0");
      localStorage.setItem(CONNECTIONS_ENABLED_KEY, connectionsEnabled ? "1" : "0");
      localStorage.setItem(BOTS_VISIBLE_KEY, botsVisible ? "1" : "0");
      localStorage.setItem(BOTS_REDUCED_KEY, botsReduced ? "1" : "0");
      localStorage.setItem(TRAILS_MODE_KEY, trailsMode);
      localStorage.setItem(MINIMAP_VISIBLE_KEY, minimapVisible ? "1" : "0");
      localStorage.setItem(LANDMARK_BEACONS_VISIBLE_KEY, landmarkBeaconsVisible ? "1" : "0");
      localStorage.setItem(ATTENTION_SIGNALS_VISIBLE_KEY, attentionSignalsVisible ? "1" : "0");
    } catch {
      /* storage disabled */
    }
  }, [densityIntensity, densityWindow, densityCompare, densityAnimate, connectionsEnabled, botsVisible, botsReduced, trailsMode, minimapVisible, landmarkBeaconsVisible, attentionSignalsVisible]);

  const cycleTrailsMode = useCallback(() => {
    setTrailsMode((curr) => {
      // off → hover → all → off. Default lives at "hover" so the next
      // click from a fresh load goes to the explicit "all" overview.
      if (curr === "off") return "hover";
      if (curr === "hover") return "all";
      return "off";
    });
  }, []);

  const cycleDensityIntensity = useCallback(() => {
    setDensityIntensity((curr) => {
      // Cycle: subtle → bold → off → subtle. Default state (subtle) is one
      // click away from "off" or "bold" — both extremes reachable quickly.
      if (curr === "subtle") return "bold";
      if (curr === "bold") return "off";
      return "subtle";
    });
  }, []);
  // Esc deactivates the active widget tile.
  useEffect(() => {
    if (!activatedTileId) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setActivatedTileId(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [activatedTileId]);

  const {
    lensEngaged,
    setLensEngaged,
    focalScreen,
    lensSettling,
    lensRadius,
    triggerLensSettle,
    panState,
    onBgPointerDown,
    onBgPointerMove,
    onBgPointerUp,
  } = useSpatialInteractions({
    viewportRef,
    viewportRectRef,
    viewportSize,
    draggingNodeId,
    activatedTileId,
    setActivatedTileId,
    diving,
    scheduleCamera,
    cameraRef,
    flushCamera,
    zoomAroundPoint,
    setSelectedSpatialObject,
    setSelectedAttentionId,
    setStarboardOpen,
    setContextMenu,
    nodes,
    fitAllNodes,
  });

  const {
    diveToChannel,
    diveToTaskDefinition,
    diveCandidate,
    flyToChannel,
    flyToNodeById,
    flyToWorldPoint,
    flyToStarboardObject,
    focusNode,
    selectNode,
    selectLandmark,
    flyToWell,
    flyToMemoryObservatory,
    flyToWorldBounds,
  } = useSpatialNavigation({
    viewportRectRef,
    nodes,
    lensEngaged,
    setLensEngaged,
    triggerLensSettle,
    scheduleCamera,
    navigate,
    onAfterDive,
    taskDefinitions,
    wellPos,
    cameraRef,
    nodesRef,
    initialFlyToChannelId,
    initialFlyToNodeId,
    setSelectedSpatialObject,
    setContextMenu,
    interactionMode,
    setInteractionMode,
    cycleDensityIntensity,
    cycleTrailsMode,
    densityIntensity,
    trailsMode,
    connectionsEnabled,
    setConnectionsEnabled,
    minimapVisible,
    setMinimapVisible,
    landmarkBeaconsVisible,
    setLandmarkBeaconsVisible,
    attentionSignalsVisible,
    setAttentionSignalsVisible,
    botsVisible,
    setBotsVisible,
    camera,
    channelsById,
    diving,
    draggingNodeId,
    mountedAtRef,
    memoryObsPos,
    setDiving,
    fitAllNodes,
    openStarboardAttention,
    setStarboardOpen,
    setStarboardStation,
  });

  const { starboardObjects, edgeBeacons, selectedStarboardObject } = useSpatialStarboardModels({
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
  });

  const {
    sensors,
    handleDragStart,
    handleDragEnd,
    handleBotPointerDown,
    handleBotPointerMove,
    handleBotPointerUp,
    viewportBbox,
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
    standaloneWidgetClusters,
  } = useSpatialDragViewport({
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
    botsReduced,
  });

  const selectionRail = useSpatialSelectionRail({
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
    openStarboardObjects,
    navigate,
    canvasBackState,
    deleteNode,
    channelForBot,
    updateNode,
    mapState,
  });

  // Fire-pulse tracking — when an upcoming item's scheduled_at crosses
  // tickedNow we render a one-shot expanding ring at its last orbit position.
  // The 5s tickedNow cadence means pulses can land up to ~5s late, but a
  // dedicated 700ms fast-tick spins up only while imminent items exist so
  // the visual lands within ~1s of the actual fire.
  const firedKeysRef = useRef<Set<string>>(new Set());
  const [firePulses, setFirePulses] = useState<
    Array<{ id: string; x: number; y: number; color: string }>
  >([]);
  const [pulseTick, setPulseTick] = useState(() => Date.now());
  useEffect(() => {
    const items = upcomingItems ?? [];
    const hasImminent = items.some((it) => {
      const t = Date.parse(it.scheduled_at);
      return !Number.isNaN(t) && t - Date.now() < 30_000;
    });
    if (!hasImminent) return;
    const id = window.setInterval(() => setPulseTick(Date.now()), 700);
    return () => window.clearInterval(id);
  }, [upcomingItems]);
  useEffect(() => {
    const now = pulseTick;
    const items = upcomingItems ?? [];
    const newPulses: Array<{ id: string; x: number; y: number; color: string }> = [];
    for (const item of items) {
      const t = Date.parse(item.scheduled_at);
      if (Number.isNaN(t)) continue;
      if (t > now) continue;
      const key = upcomingIdentityKey(item) + ":" + item.scheduled_at;
      if (firedKeysRef.current.has(key)) continue;
      firedKeysRef.current.add(key);
      const orbit = upcomingOrbit(item, t, undefined, wellPos);
      newPulses.push({
        id: key + ":" + Math.random().toString(36).slice(2, 8),
        x: orbit.x,
        y: orbit.y,
        color: upcomingTileColor(item),
      });
    }
    if (newPulses.length) {
      setFirePulses((prev) => [...prev, ...newPulses]);
    }
  }, [upcomingItems, pulseTick]);
  const dismissPulse = useCallback((id: string) => {
    setFirePulses((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const upcomingSpreadByKey = useMemo(() => {
    const buckets = new Map<string, string[]>();
    for (const item of upcomingItems ?? []) {
      const key = upcomingReactKey(item);
      const bucket = upcomingOrbitBucket(item, tickedNow, wellPos);
      const members = buckets.get(bucket) ?? [];
      members.push(key);
      buckets.set(bucket, members);
    }
    const spread = new Map<string, { index: number; count: number }>();
    for (const members of buckets.values()) {
      members.sort();
      members.forEach((key, index) => {
        spread.set(key, { index, count: members.length });
      });
    }
    return spread;
  }, [upcomingItems, tickedNow]);

  const handleActivate = useCallback((nodeId: string) => {
    setActivatedTileId(nodeId);
  }, []);

  const handleContextMenu = useSpatialContextMenu({
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
    defaultCamera: DEFAULT_CAMERA,
    fitAllNodes,
    trailsMode,
    cycleTrailsMode,
    connectionsEnabled,
    setConnectionsEnabled,
    setContextMenu,
  });

  const worldStyle: CSSProperties = {
    transform: cameraTransform(cameraRef.current),
    transformOrigin: "0 0",
    transition: diving ? `transform ${DIVE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)` : "none",
    willChange: "transform",
  };

  return (
    <div
      ref={viewportRef}
      onPointerDown={onBgPointerDown}
      onPointerMove={onBgPointerMove}
      onPointerUp={onBgPointerUp}
      onPointerCancel={onBgPointerUp}
      onContextMenu={handleContextMenu}
      data-spatial-canvas="true"
      className="absolute inset-0 overflow-hidden select-none bg-surface"
      style={{
        backgroundImage:
          "radial-gradient(rgb(var(--color-text) / 0.05) 1px, transparent 1px)",
        backgroundSize: "32px 32px",
        cursor: panState.current ? "grabbing" : "grab",
        touchAction: "none",
        overscrollBehavior: "none",
      }}
    >
      {animationsEnabled && <CanvasStarfield />}
      <SpatialCanvasWorld
        sensors={sensors}
        handleDragStart={handleDragStart}
        handleDragEnd={handleDragEnd}
        worldRef={worldRef}
        worldStyle={worldStyle}
        densityIntensity={densityIntensity}
        nodes={nodes}
        densityWindow={densityWindow}
        densityCompare={densityCompare}
        densityAnimate={densityAnimate}
        animationsEnabled={animationsEnabled}
        channelActivity={channelActivity}
        baselineChannelActivity={baselineChannelActivity}
        clusteredChannelIds={clusteredChannelIds}
        viewportBbox={viewportBbox}
        connectionsEnabled={connectionsEnabled}
        hoveredNodeId={hoveredNodeId}
        trailsMode={trailsMode}
        interactiveZoom={interactiveZoom}
        missions={missions}
        mapState={mapState}
        starboardObjects={starboardObjects}
        selectedStarboardObject={selectedStarboardObject}
        highlightedActionCueId={highlightedActionCueId}
        camera={camera}
        openStarboardHub={openStarboardHub}
        ambientZoom={ambientZoom}
        interactionMode={interactionMode}
        wellPos={wellPos}
        selectLandmark={selectLandmark}
        flyToWell={flyToWell}
        tickedNow={tickedNow}
        nowWellLens={nowWellLens}
        memoryObsPos={memoryObsPos}
        lensEngaged={lensEngaged}
        setLensEngaged={setLensEngaged}
        focalScreen={focalScreen}
        lensRadius={lensRadius}
        setMemorySelection={setMemorySelection}
        attentionHubPos={attentionHubPos}
        activeAttentionCount={activeAttentionCount}
        mapAttentionCount={mapAttentionCount}
        attentionSignalsVisible={attentionSignalsVisible}
        openStarboardAttention={openStarboardAttention}
        openStarboardSmell={openStarboardSmell}
        dailyHealthPos={dailyHealthPos}
        openStarboardHealth={openStarboardHealth}
        channelClusterMode={channelClusterMode}
        upcomingItems={upcomingItems}
        upcomingSpreadByKey={upcomingSpreadByKey}
        taskDefinitions={taskDefinitions}
        diveToTaskDefinition={diveToTaskDefinition}
        firePulses={firePulses}
        dismissPulse={dismissPulse}
        channelClusters={channelClusters}
        maxClusterTokens={maxClusterTokens}
        widgetSatellitesByClusterId={widgetSatellitesByClusterId}
        widgetOverviewOpacity={widgetOverviewOpacity}
        setSelectedSpatialObject={setSelectedSpatialObject}
        setContextMenu={setContextMenu}
        selectedSpatialObject={selectedSpatialObject}
        starboardOpen={starboardOpen}
        diveToChannel={diveToChannel}
        flyToWorldBounds={flyToWorldBounds}
        attentionByNodeId={attentionByNodeId}
        setSelectedAttentionId={setSelectedAttentionId}
        standaloneWidgetClusters={standaloneWidgetClusters}
        clusteredChannelNodeIds={clusteredChannelNodeIds}
        draggingNodeId={draggingNodeId}
        nodeInForeground={nodeInForeground}
        channelsById={channelsById}
        diving={diving}
        lensSettling={lensSettling}
        dragEnabled={dragEnabled}
        setHoveredNodeId={setHoveredNodeId}
        iconByChannelId={iconByChannelId}
        botAvatarById={botAvatarById}
        selectNode={selectNode}
        botsVisible={botsVisible}
        botsReduced={botsReduced}
        handleBotPointerDown={handleBotPointerDown}
        handleBotPointerMove={handleBotPointerMove}
        handleBotPointerUp={handleBotPointerUp}
        navigate={navigate}
        canvasBackState={canvasBackState}
        activatedTileId={activatedTileId}
        handleActivate={handleActivate}
        isInViewport={isInViewport}
        setDraggingNodeId={setDraggingNodeId}
        setActivatedTileId={setActivatedTileId}
        triggerLensSettle={triggerLensSettle}
      />
      <SpatialCanvasOverlays
        selectionRail={selectionRail}
        diveCandidate={diveCandidate}
        memorySelection={memorySelection}
        setMemorySelection={setMemorySelection}
        landmarkBeaconsVisible={landmarkBeaconsVisible}
        camera={camera}
        viewportSize={viewportSize}
        edgeBeacons={edgeBeacons}
        setPinPositionOverride={setPinPositionOverride}
        canvasLibraryOpen={canvasLibraryOpen}
        setCanvasLibraryOpen={setCanvasLibraryOpen}
        openStarboardLaunch={openStarboardLaunch}
        interactionMode={interactionMode}
        setInteractionMode={setInteractionMode}
        densityIntensity={densityIntensity}
        cycleDensityIntensity={cycleDensityIntensity}
        densityWindow={densityWindow}
        setDensityWindow={setDensityWindow}
        densityCompare={densityCompare}
        setDensityCompare={setDensityCompare}
        densityAnimate={densityAnimate}
        setDensityAnimate={setDensityAnimate}
        connectionsEnabled={connectionsEnabled}
        setConnectionsEnabled={setConnectionsEnabled}
        trailsMode={trailsMode}
        cycleTrailsMode={cycleTrailsMode}
        botsVisible={botsVisible}
        setBotsVisible={setBotsVisible}
        botsReduced={botsReduced}
        setBotsReduced={setBotsReduced}
        setLandmarkBeaconsVisible={setLandmarkBeaconsVisible}
        attentionSignalsVisible={attentionSignalsVisible}
        setAttentionSignalsVisible={setAttentionSignalsVisible}
        starboardObjects={starboardObjects}
        viewportBbox={viewportBbox}
        highlightedActionCueId={highlightedActionCueId}
        setHighlightedActionCueId={setHighlightedActionCueId}
        starboardOpen={starboardOpen}
        setStarboardOpen={setStarboardOpen}
        attentionItems={attentionItems}
        selectedAttentionId={selectedAttentionId}
        setSelectedAttentionId={setSelectedAttentionId}
        handleAttentionReply={handleAttentionReply}
        selectedStarboardObject={selectedStarboardObject}
        pinPositionOverride={pinPositionOverride}
        cameraRef={cameraRef}
        minimapVisible={minimapVisible}
        nodes={nodes}
        flyToWorldPoint={flyToWorldPoint}
        setMinimapVisible={setMinimapVisible}
        contextMenu={contextMenu}
        setContextMenu={setContextMenu}
        openBotChat={openBotChat}
        setOpenBotChat={setOpenBotChat}
        sessionPickerOpen={sessionPickerOpen}
        setSessionPickerOpen={setSessionPickerOpen}
        navigate={navigate}
      />
    </div>
  );
}
