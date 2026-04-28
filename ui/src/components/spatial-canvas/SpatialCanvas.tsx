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
  LensHint,
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
import { widgetPinHref } from "../../lib/hubRoutes";
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

function cameraTransform(camera: Camera): string {
  return `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`;
}

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
  | { kind: "landmark"; id: "now_well" | "memory_observatory" | "attention_hub" | "daily_health" }
  | { kind: "channel-cluster"; id: string };

export function SpatialCanvas({ onAfterDive, initialFlyToChannelId, initialFlyToNodeId }: SpatialCanvasProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const canvasBackState = contextualNavigationState(`${location.pathname}${location.search}`, "Canvas");
  const { data: nodes } = useSpatialNodes();
  // Live landmark positions derived from `nodes`. Falls back to the
  // hardcoded seed defaults until the canvas list query resolves; once
  // the row exists it's the source of truth, so user drags propagate to
  // every consumer (orbit math, edge beacons, fly-to camera, lens projection).
  const wellPos = landmarkPositionFromNodes(nodes, "now_well", WELL_X, WELL_Y);
  const memoryObsPos = landmarkPositionFromNodes(nodes, "memory_observatory", MEMORY_OBSERVATORY_X, MEMORY_OBSERVATORY_Y);
  const attentionHubPos = landmarkPositionFromNodes(nodes, "attention_hub", ATTENTION_HUB_X, ATTENTION_HUB_Y);
  const dailyHealthPos = landmarkPositionFromNodes(nodes, "daily_health", HEALTH_SUMMARY_X, HEALTH_SUMMARY_Y);
  const { data: attentionItems } = useWorkspaceAttention();
  const { data: missions } = useWorkspaceMissions();
  const markAttentionResponded = useMarkAttentionResponded();
  const attentionHubOpen = useUIStore((s) => s.attentionHubOpen);
  const closeAttentionHub = useUIStore((s) => s.closeAttentionHub);
  const [interactionMode, setInteractionMode] = useState<SpatialInteractionMode>("browse");
  const [selectedSpatialObject, setSelectedSpatialObject] = useState<SpatialSelection | null>(null);
  const dragEnabled = interactionMode === "arrange";
  const { data: channels } = useChannels();
  const { data: bots } = useBots();
  const { data: upcomingItems } = useSpatialUpcomingActivity(50);
  const { data: definitionsData } = useQuery({
    queryKey: ["spatial-task-definitions"],
    queryFn: () => apiFetch<TasksResponse>("/api/v1/admin/tasks?limit=200&definitions_only=true"),
    staleTime: 30_000,
  });
  const taskDefinitions = useMemo(
    () => (definitionsData?.tasks ?? []).filter((t) => t.source !== "system"),
    [definitionsData],
  );
  const updateNode = useUpdateSpatialNode();
  const deleteNode = useDeleteSpatialNode();

  // Snapshot of the live node list — read by the window-exposed recording
  // hook without forcing a re-run when nodes refetch.
  const nodesRef = useRef<typeof nodes>(nodes);
  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

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

  // Live tick for the Now Well + orbital tile positions. Server data is
  // 60s-fresh (`useSpatialUpcomingActivity` refetchInterval), but tile radii
  // decay continuously toward the well between fetches. Cadence:
  //   • 5s default — quiet canvas, no imminent fires.
  //   • 1s when an item is < 60s out — fast enough to show the diamond's
  //     final approach inward and align with the fire-pulse detector below.
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
    for (const item of list) {
      if (!isActiveAttentionItem(item)) continue;
      const node = (nodes ?? []).find((candidate) => {
        if (item.target_node_id) return candidate.id === item.target_node_id;
        if (item.target_kind === "channel") return candidate.channel_id === item.target_id;
        if (item.target_kind === "bot") return candidate.bot_id === item.target_id;
        if (item.target_kind === "widget") return candidate.widget_pin_id === item.target_id;
        return false;
      });
      if (!node) continue;
      const bucket = byNode.get(node.id) ?? [];
      bucket.push(item);
      byNode.set(node.id, bucket);
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

  const openStarboard = useCallback((station: StarboardStation) => {
    setStarboardStation(station);
    try {
      localStorage.setItem("spatial.starboard.activeTab", station);
    } catch {
      /* storage disabled */
    }
    setStarboardOpen(true);
  }, []);

  const openStarboardAttention = useCallback((item?: WorkspaceAttentionItem | null) => {
    if (item) setSelectedAttentionId(item.id);
    openStarboard("attention");
    closeAttentionHub();
  }, [closeAttentionHub, openStarboard]);
  const openStarboardLaunch = useCallback(() => {
    openStarboard("launch");
  }, [openStarboard]);
  const openStarboardHub = useCallback(() => {
    openStarboard("hub");
  }, [openStarboard]);
  const openStarboardHealth = useCallback(() => {
    openStarboard("health");
  }, [openStarboard]);
  const openStarboardSmell = useCallback(() => {
    openStarboard("smell");
  }, [openStarboard]);

  useEffect(() => {
    if (!attentionHubOpen) return;
    openStarboardAttention();
  }, [attentionHubOpen, openStarboardAttention]);

  const botAvatarById = useMemo(() => {
    const m = new Map<string, string>();
    for (const bot of bots ?? []) {
      if (bot.avatar_emoji) m.set(bot.id, bot.avatar_emoji);
    }
    return m;
  }, [bots]);

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

  // Channel dashboards carry an `icon` field already used by the sidebar
  // rail; lift it onto the canvas tile too. Map `channelId → icon name`
  // (or null if the user hasn't picked one yet — tile falls back to Hash).
  const { channelDashboards } = useDashboards();
  const iconByChannelId = useMemo(() => {
    const m = new Map<string, string | null>();
    for (const d of channelDashboards) {
      const cid = channelIdFromSlug(d.slug);
      if (cid) m.set(cid, d.icon);
    }
    return m;
  }, [channelDashboards]);

  const [camera, setCamera] = useState<Camera>(() => loadStoredCamera());
  const viewportRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const cameraRef = useRef(camera);
  const viewportRectRef = useRef({ left: 0, top: 0, width: 0, height: 0 });
  const pendingCameraRef = useRef<Camera | null>(null);
  const cameraRafRef = useRef<number | null>(null);
  const cameraCommitTimerRef = useRef<number | null>(null);
  const cameraMovingTimerRef = useRef<number | null>(null);
  const [cameraMoving, setCameraMoving] = useState(false);
  const [diving, setDiving] = useState(false);
  // Mount timestamp — gates push-through dive detection for the first 1.5s
  // after the canvas remounts. Belt-and-suspenders against any flow that
  // lands the user at high zoom over a tile (route change, hot reload,
  // future "open canvas centered on X" entry points), not just the
  // beam-me-up case the sessionStorage handoff covers.
  const mountedAtRef = useRef<number>(Date.now());
  // Persist camera on every change EXCEPT during the dive transition. Dive
  // tweens the camera to a tile-fill target right before navigating away;
  // we want to remember the user's *pre-dive* exploration camera, not the
  // fully-zoomed-in dive target. Skipping the write while `diving` is true
  // freezes localStorage at the last pan/zoom the user authored, which is
  // what they expect when they return to the canvas.
  useEffect(() => {
    if (diving) return;
    const id = window.setTimeout(() => {
      try {
        localStorage.setItem(CAMERA_STORAGE_KEY, JSON.stringify(camera));
      } catch {
        /* quota / disabled storage — silently skip */
      }
    }, 180);
    return () => window.clearTimeout(id);
  }, [camera, diving]);

  const applyCameraTransform = useCallback((next: Camera) => {
    const world = worldRef.current;
    if (world) world.style.transform = cameraTransform(next);
  }, []);

  const markCameraMoving = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.classList.add("spatial-camera-moving");
    setCameraMoving(true);
    if (cameraMovingTimerRef.current !== null) {
      window.clearTimeout(cameraMovingTimerRef.current);
    }
    cameraMovingTimerRef.current = window.setTimeout(() => {
      viewport.classList.remove("spatial-camera-moving");
      setCameraMoving(false);
      cameraMovingTimerRef.current = null;
    }, CAMERA_MOVING_CLASS_MS);
  }, []);

  const commitCameraState = useCallback((next: Camera) => {
    const clamped = clampCamera(next);
    cameraRef.current = clamped;
    pendingCameraRef.current = null;
    applyCameraTransform(clamped);
    setCamera((curr) =>
      curr.x === clamped.x && curr.y === clamped.y && curr.scale === clamped.scale
        ? curr
        : clamped,
    );
  }, [applyCameraTransform]);

  const scheduleCamera = useCallback((next: Camera, commit: "idle" | "immediate" = "idle") => {
    const clamped = clampCamera(next);
    cameraRef.current = clamped;
    pendingCameraRef.current = clamped;

    if (cameraRafRef.current === null) {
      cameraRafRef.current = window.requestAnimationFrame(() => {
        cameraRafRef.current = null;
        const pending = pendingCameraRef.current;
        if (pending) applyCameraTransform(pending);
      });
    }

    if (commit === "immediate") {
      if (cameraCommitTimerRef.current !== null) {
        window.clearTimeout(cameraCommitTimerRef.current);
        cameraCommitTimerRef.current = null;
      }
      commitCameraState(clamped);
      return;
    }

    markCameraMoving();
    if (cameraCommitTimerRef.current !== null) {
      window.clearTimeout(cameraCommitTimerRef.current);
    }
    cameraCommitTimerRef.current = window.setTimeout(() => {
      cameraCommitTimerRef.current = null;
      commitCameraState(cameraRef.current);
    }, CAMERA_IDLE_COMMIT_MS);
  }, [applyCameraTransform, commitCameraState, markCameraMoving]);

  const flushCamera = useCallback(() => {
    if (cameraCommitTimerRef.current !== null) {
      window.clearTimeout(cameraCommitTimerRef.current);
      cameraCommitTimerRef.current = null;
    }
    commitCameraState(cameraRef.current);
  }, [commitCameraState]);

  useEffect(() => {
    cameraRef.current = camera;
    applyCameraTransform(camera);
  }, [camera, applyCameraTransform]);

  useEffect(() => {
    return () => {
      if (cameraRafRef.current !== null) window.cancelAnimationFrame(cameraRafRef.current);
      if (cameraCommitTimerRef.current !== null) window.clearTimeout(cameraCommitTimerRef.current);
      if (cameraMovingTimerRef.current !== null) window.clearTimeout(cameraMovingTimerRef.current);
    };
  }, []);

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
  const [starboardStation, setStarboardStation] = useState<StarboardStation>(loadStarboardStation);
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
  // Viewport size in screen pixels — used together with `camera` to compute
  // each tile's `inViewport` flag for iframe culling. ResizeObserver keeps it
  // current across overlay open/close, sidebar toggles, and window resizes.
  const [viewportSize, setViewportSize] = useState<{ w: number; h: number }>({
    w: 0,
    h: 0,
  });

  const updateViewportMetrics = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    viewportRectRef.current = {
      left: r.left,
      top: r.top,
      width: r.width,
      height: r.height,
    };
    setViewportSize((curr) =>
      curr.w === r.width && curr.h === r.height ? curr : { w: r.width, h: r.height },
    );
  }, []);

  const pointerToWorld = useCallback((clientX: number, clientY: number) => {
    const rect = viewportRectRef.current;
    const c = cameraRef.current;
    if (!rect.width || !rect.height) return null;
    return {
      x: (clientX - rect.left - c.x) / c.scale,
      y: (clientY - rect.top - c.y) / c.scale,
    };
  }, []);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    updateViewportMetrics();
    const ro = new ResizeObserver(updateViewportMetrics);
    ro.observe(el);
    return () => ro.disconnect();
  }, [updateViewportMetrics]);

  // Esc deactivates the active widget tile.
  useEffect(() => {
    if (!activatedTileId) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setActivatedTileId(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [activatedTileId]);

  // Fisheye lens state (P16). `lensEngaged` is the held-Space flag;
  // `focalScreen` is the cursor position relative to the viewport rect at
  // engage time and updated live while engaged. `lensSettling` is true for
  // ~LENS_SETTLE_MS after engage/disengage so tiles get a CSS transition for
  // the pop-in / pop-out; while engaged + cursor-tracking it's false so tile
  // transforms follow the cursor without lag.
  const [lensEngaged, setLensEngaged] = useState(false);
  const [focalScreen, setFocalScreen] = useState<{ x: number; y: number } | null>(null);
  const [lensSettling, setLensSettling] = useState(false);
  const lastCursorRef = useRef<{ x: number; y: number } | null>(null);
  const pendingFocalRef = useRef<{ x: number; y: number } | null>(null);
  const focalRafRef = useRef<number | null>(null);
  const lensSettleTimerRef = useRef<number | null>(null);

  const lensRadius = useMemo(() => {
    if (!viewportSize.w || !viewportSize.h) return 0;
    return LENS_NATIVE_FRACTION * Math.min(viewportSize.w, viewportSize.h);
  }, [viewportSize.w, viewportSize.h]);

  const triggerLensSettle = useCallback(() => {
    setLensSettling(true);
    if (lensSettleTimerRef.current) {
      window.clearTimeout(lensSettleTimerRef.current);
    }
    lensSettleTimerRef.current = window.setTimeout(() => {
      setLensSettling(false);
      lensSettleTimerRef.current = null;
    }, LENS_SETTLE_MS + 10);
  }, []);

  // Cursor tracking (always-on; cheap). Used for both engage-time focal seed
  // and live focal updates while engaged.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const handler = (e: PointerEvent) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const p = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      lastCursorRef.current = p;
      if (!lensEngaged) return;
      pendingFocalRef.current = p;
      if (focalRafRef.current === null) {
        focalRafRef.current = window.requestAnimationFrame(() => {
          focalRafRef.current = null;
          setFocalScreen(pendingFocalRef.current);
        });
      }
    };
    el.addEventListener("pointermove", handler);
    return () => el.removeEventListener("pointermove", handler);
  }, [lensEngaged]);

  useEffect(() => {
    return () => {
      if (focalRafRef.current !== null) window.cancelAnimationFrame(focalRafRef.current);
    };
  }, []);

  // Space hold-to-engage. Guards: input focus, modifiers, repeat, in-flight
  // pan, in-flight tile drag.
  useEffect(() => {
    const isInputFocused = () => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      if (e.repeat) return;
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
      if (isInputFocused()) return;
      if (panState.current) return;
      if (draggingNodeId) return;
      if (lensEngaged) return;
      e.preventDefault();
      setFocalScreen(lastCursorRef.current);
      setLensEngaged(true);
      triggerLensSettle();
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      if (!lensEngaged) return;
      setLensEngaged(false);
      triggerLensSettle();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [lensEngaged, draggingNodeId, triggerLensSettle]);

  // If a drag starts while the lens is held, drop the lens (drag math at the
  // lens edge would be non-linear — release first, drag second).
  useEffect(() => {
    if (draggingNodeId && lensEngaged) {
      setLensEngaged(false);
      triggerLensSettle();
    }
  }, [draggingNodeId, lensEngaged, triggerLensSettle]);
  const panState = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    cameraX: number;
    cameraY: number;
  } | null>(null);

  const onBgPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.button !== 0 || diving) return;
      // Pan starts on background space only. Tiles and landmarks own their
      // own click/selection semantics; Arrange mode is the only movement mode.
      // The world layer covers the entire viewport (absolute inset-0), so a strict
      // `target === currentTarget` check would only allow pan on the
      // viewport's literal edges — the gap area between tiles wouldn't
      // pan.
      const target = e.target as HTMLElement;
      if (target.closest("button,a,input,textarea,select")) return;
      if (target.closest("[data-tile-kind]")) return;
      if (activatedTileId) setActivatedTileId(null);
      // Pan supersedes lens — drop the lens if it's engaged.
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      panState.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        cameraX: cameraRef.current.x,
        cameraY: cameraRef.current.y,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [diving, activatedTileId, lensEngaged, triggerLensSettle],
  );

  const onBgPointerMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const p = panState.current;
    if (!p || p.pointerId !== e.pointerId) return;
    scheduleCamera({
      ...cameraRef.current,
      x: p.cameraX + (e.clientX - p.startX),
      y: p.cameraY + (e.clientY - p.startY),
    });
  }, [scheduleCamera]);

  const onBgPointerUp = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const p = panState.current;
    if (!p || p.pointerId !== e.pointerId) return;
    panState.current = null;
    flushCamera();
    if (
      isEmptySpaceClickGesture({
        startX: p.startX,
        startY: p.startY,
        endX: e.clientX,
        endY: e.clientY,
      })
    ) {
      setSelectedSpatialObject(null);
      setSelectedAttentionId(null);
      setStarboardOpen(false);
      setContextMenu(null);
    }
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
  }, [flushCamera]);

  // Anchor-zoom helper used by the wheel handler, the keyboard `+` / `-`
  // shortcuts, and any other code path that wants to scale the camera while
  // pinning a screen point. The point `(cx, cy)` is in viewport-local pixels.
  const zoomAroundPoint = useCallback(
    (factor: number, cx: number, cy: number) => {
      const c = cameraRef.current;
      const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, c.scale * factor));
      const k = newScale / c.scale;
      scheduleCamera({
        scale: newScale,
        x: cx - (cx - c.x) * k,
        y: cy - (cy - c.y) * k,
      });
    },
    [scheduleCamera],
  );

  // Frame all spatial nodes inside the viewport with an 8% margin. Falls
  // back to `DEFAULT_CAMERA` when there's nothing to fit.
  const fitAllNodes = useCallback(() => {
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    const list = nodes ?? [];
    if (list.length === 0) {
      scheduleCamera(DEFAULT_CAMERA, "immediate");
      return;
    }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of list) {
      if (n.world_x < minX) minX = n.world_x;
      if (n.world_y < minY) minY = n.world_y;
      if (n.world_x + n.world_w > maxX) maxX = n.world_x + n.world_w;
      if (n.world_y + n.world_h > maxY) maxY = n.world_y + n.world_h;
    }
    const bboxW = Math.max(1, maxX - minX);
    const bboxH = Math.max(1, maxY - minY);
    const margin = 0.08;
    const targetScale = Math.max(
      MIN_SCALE,
      Math.min(
        MAX_SCALE,
        Math.min(
          rect.width / (bboxW * (1 + margin * 2)),
          rect.height / (bboxH * (1 + margin * 2)),
        ),
      ),
    );
    const cx = minX + bboxW / 2;
    const cy = minY + bboxH / 2;
    scheduleCamera({
      scale: targetScale,
      x: rect.width / 2 - cx * targetScale,
      y: rect.height / 2 - cy * targetScale,
    }, "immediate");
  }, [nodes, scheduleCamera]);

  // Beam-me-up handoff. Channel and widget detail routes set a sessionStorage
  // flag before navigating here; on mount we select the target node and land
  // at a safe overview zoom below the push-through dive threshold.
  const beamConsumedRef = useRef(false);
  useEffect(() => {
    if (beamConsumedRef.current) return;
    if (!nodes || nodes.length === 0) return;
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    let raw: string | null = null;
    try {
      raw = sessionStorage.getItem(SPATIAL_HANDOFF_KEY);
    } catch {
      beamConsumedRef.current = true;
      return;
    }
    if (!raw) {
      beamConsumedRef.current = true;
      return;
    }
    try {
      sessionStorage.removeItem(SPATIAL_HANDOFF_KEY);
    } catch {
      // Ignore — flag will just expire on the timestamp check next time.
    }
    beamConsumedRef.current = true;
    let parsed: { kind?: string; channelId?: string; pinId?: string; ts?: number } | null = null;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return;
    }
    if (!parsed || typeof parsed.ts !== "number") return;
    if (Date.now() - parsed.ts > 5000) return;
    const tile = parsed.kind === "widgetPin" && parsed.pinId
      ? nodes.find((n) => {
          if (n.widget_pin_id === parsed!.pinId) return true;
          const origin = n.pin?.widget_origin;
          return !!origin
            && typeof origin === "object"
            && (origin as { source_dashboard_pin_id?: unknown }).source_dashboard_pin_id === parsed!.pinId;
        })
      : parsed.channelId
        ? nodes.find((n) => n.channel_id === parsed!.channelId)
        : null;
    if (!tile) return;
    if (tile.widget_pin_id) {
      setSelectedSpatialObject({ kind: "widget", nodeId: tile.id });
    } else if (tile.channel_id) {
      setSelectedSpatialObject({ kind: "channel", nodeId: tile.id });
    }
    const targetScale = DIVE_SCALE_THRESHOLD * 0.7;
    const tileCx = tile.world_x + tile.world_w / 2;
    const tileCy = tile.world_y + tile.world_h / 2;
    scheduleCamera(
      {
        scale: targetScale,
        x: rect.width / 2 - tileCx * targetScale,
        y: rect.height / 2 - tileCy * targetScale,
      },
      "immediate",
    );
  }, [nodes, viewportSize.w, viewportSize.h, scheduleCamera]);

  // Manual wheel listener with { passive: false } — React's synthetic onWheel
  // is passive by default, so preventDefault() would be silently ignored and
  // the page would scroll underneath.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    function handler(e: WheelEvent) {
      if (diving) return;
      if (e.target instanceof Element && e.target.closest("[data-starboard-panel='true']")) return;
      e.preventDefault();
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      zoomAroundPoint(
        Math.exp(-e.deltaY * 0.001),
        e.clientX - rect.left,
        e.clientY - rect.top,
      );
    }
    viewport.addEventListener("wheel", handler, { passive: false });
    return () => viewport.removeEventListener("wheel", handler);
  }, [diving, zoomAroundPoint]);

  // Keyboard shortcuts for the canvas chrome: `F` fits all nodes, `+` / `-`
  // zoom around the viewport center. Same input-focus / dive / drag guards
  // the lens-engage hook uses; modifier keys (Ctrl/Cmd/Alt) bail so OS
  // shortcuts like Cmd+= / Cmd+- (browser zoom) keep their native behavior.
  useEffect(() => {
    const isInputFocused = () => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
    };
    function handler(e: KeyboardEvent) {
      if (diving || draggingNodeId) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isInputFocused()) return;
      if (e.key === "f" || e.key === "F") {
        if (e.repeat || e.shiftKey) return;
        e.preventDefault();
        fitAllNodes();
        return;
      }
      if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        const rect = viewportRectRef.current;
        if (!rect.width || !rect.height) return;
        zoomAroundPoint(1.2, rect.width / 2, rect.height / 2);
        return;
      }
      if (e.key === "-" || e.key === "_") {
        e.preventDefault();
        const rect = viewportRectRef.current;
        if (!rect.width || !rect.height) return;
        zoomAroundPoint(0.83, rect.width / 2, rect.height / 2);
        return;
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [diving, draggingNodeId, fitAllNodes, zoomAroundPoint]);

  // Touch long-press on canvas background previously opened a radial menu.
  // It now opens the global ⌘K palette instead — same canvas-aware menu the
  // keyboard shortcut shows. Only fires on the viewport background (not on
  // a tile / chrome) and only when the press doesn't drift > 8px during the
  // 350ms hold. Tile long-press is owned by dnd-kit's TouchSensor.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    let timer: number | null = null;
    let startX = 0;
    let startY = 0;
    const cancel = () => {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    };
    const onDown = (e: PointerEvent) => {
      if (e.pointerType !== "touch") return;
      const target = e.target as HTMLElement | null;
      if (target && target.closest("[data-tile-kind]")) return;
      startX = e.clientX;
      startY = e.clientY;
      cancel();
      timer = window.setTimeout(() => {
        useUIStore.getState().openPalette();
        timer = null;
      }, 350);
    };
    const onMove = (e: PointerEvent) => {
      if (timer === null) return;
      if (Math.hypot(e.clientX - startX, e.clientY - startY) > 8) cancel();
    };
    viewport.addEventListener("pointerdown", onDown);
    viewport.addEventListener("pointermove", onMove);
    viewport.addEventListener("pointerup", cancel);
    viewport.addEventListener("pointercancel", cancel);
    return () => {
      cancel();
      viewport.removeEventListener("pointerdown", onDown);
      viewport.removeEventListener("pointermove", onMove);
      viewport.removeEventListener("pointerup", cancel);
      viewport.removeEventListener("pointercancel", cancel);
    };
  }, []);

  // Two-finger pinch zoom (mobile / trackpad). Captures all touch pointers on
  // the viewport regardless of whether they land on tiles or background, so a
  // second finger always escalates to pinch even mid tile-drag. While pinching
  // we suppress the single-finger pan and the dnd-kit tile drag (the latter
  // by sending preventDefault on the move). Anchor logic mirrors the wheel
  // handler: zoom around the initial midpoint, plus midpoint translation for
  // two-finger pan.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const pointers = new Map<number, { x: number; y: number }>();
    let pinch:
      | { distance: number; midpoint: { x: number; y: number }; camera: Camera }
      | null = null;

    function midpointAndDistance() {
      const pts = Array.from(pointers.values()).slice(0, 2);
      const [p1, p2] = pts;
      return {
        distance: Math.hypot(p1.x - p2.x, p1.y - p2.y),
        midpointClient: { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 },
      };
    }

    function onDown(e: PointerEvent) {
      if (e.pointerType !== "touch") return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size >= 2 && !pinch) {
        const rect = viewportRectRef.current;
        if (!rect.width || !rect.height) return;
        const { distance, midpointClient } = midpointAndDistance();
        pinch = {
          distance,
          midpoint: {
            x: midpointClient.x - rect.left,
            y: midpointClient.y - rect.top,
          },
          camera: cameraRef.current,
        };
        // Pinch overrides pan AND any in-flight tile drag.
        panState.current = null;
        if (lensEngaged) {
          setLensEngaged(false);
          triggerLensSettle();
        }
      }
    }

    function onMove(e: PointerEvent) {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (!pinch || pointers.size < 2) return;
      e.preventDefault();
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const { distance, midpointClient } = midpointAndDistance();
      const newMid = {
        x: midpointClient.x - rect.left,
        y: midpointClient.y - rect.top,
      };
      const factor = distance / pinch.distance;
      const c = pinch.camera;
      const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, c.scale * factor));
      const k = newScale / c.scale;
      const mx = pinch.midpoint.x;
      const my = pinch.midpoint.y;
      const dx = newMid.x - mx;
      const dy = newMid.y - my;
      scheduleCamera({
        scale: newScale,
        x: mx - (mx - c.x) * k + dx,
        y: my - (my - c.y) * k + dy,
      });
    }

    function onUp(e: PointerEvent) {
      if (!pointers.has(e.pointerId)) return;
      pointers.delete(e.pointerId);
      if (pointers.size < 2) {
        pinch = null;
        flushCamera();
      }
    }

    viewport.addEventListener("pointerdown", onDown, { capture: true });
    viewport.addEventListener("pointermove", onMove, { capture: true, passive: false });
    viewport.addEventListener("pointerup", onUp, { capture: true });
    viewport.addEventListener("pointercancel", onUp, { capture: true });
    return () => {
      viewport.removeEventListener("pointerdown", onDown, { capture: true });
      viewport.removeEventListener("pointermove", onMove, { capture: true });
      viewport.removeEventListener("pointerup", onUp, { capture: true });
      viewport.removeEventListener("pointercancel", onUp, { capture: true });
    };
  }, [lensEngaged, triggerLensSettle, scheduleCamera, flushCamera]);

  const diveToChannel = useCallback(
    (channelId: string, world: { x: number; y: number; w: number; h: number }) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const targetScale = Math.max(rect.width / world.w, rect.height / world.h);
      const targetX = rect.width / 2 - (world.x + world.w / 2) * targetScale;
      const targetY = rect.height / 2 - (world.y + world.h / 2) * targetScale;
      // Drop the lens before diving so the per-tile fisheye transform doesn't
      // fight the dive animation on the target tile.
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      setDiving(true);
      requestAnimationFrame(() => {
        scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
      });
      // Animate-THEN-navigate: route change happens after the transition
      // completes. onAfterDive (overlay close) runs a tick later so the new
      // route paints before the overlay disappears.
      // Surface routing: dive to whichever surface the user last opened for
      // this channel (chat OR `/widgets/channel/:id` dashboard). First-ever
      // dive falls back to chat. The tracker in AppShell records the
      // surface on every channel-route visit.
      const surface = getChannelLastSurface(channelId) ?? "chat";
      const target = buildChannelSurfaceRoute(channelId, surface);
      window.setTimeout(() => {
        navigate(target);
        if (onAfterDive) window.setTimeout(onAfterDive, 16);
      }, DIVE_MS);
    },
    [navigate, onAfterDive, lensEngaged, triggerLensSettle, scheduleCamera],
  );

  /**
   * diveToTaskDefinition — mirrors `diveToChannel` for an outer-ring
   * task definition tile. Camera flies toward the orbit point; route
   * swaps to the canvas editor for that task with a sidebar-collapsed
   * layout.
   */
  const diveToTaskDefinition = useCallback(
    (taskId: string) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const def = taskDefinitions.find((t) => t.id === taskId);
      if (!def) return;
      const idx = taskDefinitions.findIndex((t) => t.id === taskId);
      const orbit = definitionOrbit(taskId, taskDefinitions.length, idx, wellPos);
      // Aim the camera so the orbit point sits in the viewport center
      // at near-max zoom; the editor pop-in covers the rest visually.
      const targetScale = MAX_SCALE * 0.95;
      const targetX = rect.width / 2 - orbit.x * targetScale;
      const targetY = rect.height / 2 - orbit.y * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      setDiving(true);
      requestAnimationFrame(() => {
        scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
      });
      window.setTimeout(() => {
        navigate(`/admin/automations?canvas=1&edit=${encodeURIComponent(taskId)}`);
        if (onAfterDive) window.setTimeout(onAfterDive, 16);
      }, DIVE_MS);
    },
    [taskDefinitions, navigate, onAfterDive, lensEngaged, triggerLensSettle, scheduleCamera],
  );

  // Push-through dive — sustained zoom into a channel tile triggers the same
  // dive flow as double-click. Trigger condition (re-evaluated on every
  // camera commit): scale >= DIVE_SCALE_THRESHOLD AND viewport center in
  // the bounding box of exactly one channel tile (with margin). Dwell timer
  // gives the user 450ms to back off — vignette + crosshair tighten as the
  // timer progresses.
  const [diveCandidate, setDiveCandidate] = useState<{
    nodeId: string;
    channelId: string;
    label: string;
    world: { x: number; y: number; w: number; h: number };
  } | null>(null);

  useEffect(() => {
    // Mount-time cooldown — defends against any flow that lands the canvas
    // at high zoom over a tile right after mount (most often: beam-me-up
    // back from a channel route, where the camera state loaded from
    // localStorage might re-trigger a dive into the channel we just left).
    if (Date.now() - mountedAtRef.current < 1500) {
      setDiveCandidate(null);
      return;
    }
    if (diving || draggingNodeId) {
      setDiveCandidate(null);
      return;
    }
    if (camera.scale < DIVE_SCALE_THRESHOLD) {
      setDiveCandidate(null);
      return;
    }
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    // Viewport center → world coords.
    const cx = (rect.width / 2 - camera.x) / camera.scale;
    const cy = (rect.height / 2 - camera.y) / camera.scale;
    let found: typeof diveCandidate = null;
    for (const n of nodes ?? []) {
      if (!n.channel_id) continue;
      const padX = n.world_w * DIVE_VIEWPORT_MARGIN;
      const padY = n.world_h * DIVE_VIEWPORT_MARGIN;
      if (
        cx >= n.world_x - padX
        && cx <= n.world_x + n.world_w + padX
        && cy >= n.world_y - padY
        && cy <= n.world_y + n.world_h + padY
      ) {
        const channel = channelsById.get(n.channel_id);
        const label = channel ? channel.display_name || channel.name : "channel";
        found = {
          nodeId: n.id,
          channelId: n.channel_id,
          label,
          world: { x: n.world_x, y: n.world_y, w: n.world_w, h: n.world_h },
        };
        break;
      }
    }
    setDiveCandidate((curr) => {
      if (!found) return null;
      if (curr && curr.nodeId === found.nodeId) return curr;
      return found;
    });
  }, [camera, nodes, channelsById, diving, draggingNodeId]);

  // Dwell timer + smooth progress tween. Restarts whenever the candidate
  // changes (or first appears). Cancels cleanly on candidate clear.
  useEffect(() => {
    if (!diveCandidate) return;
    const id = window.setTimeout(() => {
      diveToChannel(diveCandidate.channelId, diveCandidate.world);
    }, DIVE_DWELL_MS);
    return () => window.clearTimeout(id);
  }, [diveCandidate, diveToChannel]);

  // Pan + scale the camera to a single channel tile (Cmd+K override target).
  // Same scale-derivation pattern as `diveToChannel` but capped at scale 1.0
  // so the user lands at the channel's "preview" zoom — readable but not
  // fully zoomed-in (which would overshoot into a single-tile-fills-screen
  // state that's hard to navigate away from).
  const flyToChannel = useCallback(
    (channelId: string): boolean => {
      const node = (nodes ?? []).find((n) => n.channel_id === channelId);
      const rect = viewportRectRef.current;
      if (!node || !rect.width || !rect.height) return false;
      const targetScale = Math.min(
        1.0,
        Math.max(rect.width / (node.world_w * 4), rect.height / (node.world_h * 4)),
      );
      const cx = node.world_x + node.world_w / 2;
      const cy = node.world_y + node.world_h / 2;
      const targetX = rect.width / 2 - cx * targetScale;
      const targetY = rect.height / 2 - cy * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
      return true;
    },
    [nodes, lensEngaged, triggerLensSettle, scheduleCamera],
  );

  // Pan + scale the camera to a spatial node by id. Used for the widget-pick
  // palette override and the contributed widget items.
  const flyToNodeById = useCallback(
    (nodeId: string): boolean => {
      const node = (nodes ?? []).find((n) => n.id === nodeId);
      const rect = viewportRectRef.current;
      if (!node || !rect.width || !rect.height) return false;
      const targetScale = Math.min(
        1.0,
        Math.max(rect.width / (node.world_w * 4), rect.height / (node.world_h * 4)),
      );
      const cx = node.world_x + node.world_w / 2;
      const cy = node.world_y + node.world_h / 2;
      const targetX = rect.width / 2 - cx * targetScale;
      const targetY = rect.height / 2 - cy * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
      return true;
    },
    [nodes, lensEngaged, triggerLensSettle, scheduleCamera],
  );

  // Register the channel-pick + widget-pick overrides + the active surface
  // on the palette. While the canvas is mounted, ⌘K renders in canvas mode
  // (Canvas + On the map groups at top); Enter opens routes while the
  // secondary action can fly the camera to mapped channels/widgets.
  useEffect(() => {
    const o = usePaletteOverrides.getState();
    o.setChannelPick(flyToChannel);
    o.setWidgetPick(flyToNodeById);
    o.setSurface("canvas");
    return () => {
      const c = usePaletteOverrides.getState();
      c.setChannelPick(null);
      c.setWidgetPick(null);
      c.setSurface(null);
    };
  }, [flyToChannel, flyToNodeById]);

  // Publish channel ids that have a spatial node so the palette can re-badge
  // them into the "On the map" group when the canvas is the active surface.
  // Membership changes infrequently, so we cheap-derive via .map + Set on
  // every nodes update.
  useEffect(() => {
    const ids = new Set<string>();
    for (const n of nodes ?? []) {
      if (n.channel_id) ids.add(n.channel_id);
    }
    usePaletteOverrides.getState().setOnMapChannelIds(ids);
    return () => {
      usePaletteOverrides.getState().setOnMapChannelIds(new Set());
    };
  }, [nodes]);

  // Contribute one palette item per pinned widget node so widgets are
  // searchable in ⌘K. Selecting a widget flies the camera to its tile
  // (handled by the widgetPick override). Items have no `href`, so the
  // secondary "Open page" affordance is naturally hidden — widgets have no
  // standalone route.
  useEffect(() => {
    const items = (nodes ?? [])
      .filter((n) => n.widget_pin_id && n.pin)
      .map((n) => ({
        id: `widget-${n.id}`,
        label: `Widget: ${n.pin?.panel_title || n.pin?.display_label || n.pin?.tool_name || "Untitled"}`,
        category: "On the map",
        icon: LayoutDashboard,
        routeKind: "spatial-widget",
        hint: n.pin?.tool_name || undefined,
      }));
    usePaletteOverrides.getState().setExtraItems(items);
    return () => {
      usePaletteOverrides.getState().setExtraItems([]);
    };
  }, [nodes]);

  // Contextual-camera-on-open. When the overlay mounts the canvas with a
  // target channel id (because the user opened it from /channels/:id), fly
  // there as soon as the node list arrives instead of restoring the
  // last-saved camera. One-shot per mount — toggling the overlay closed
  // and back open re-mounts the canvas, which re-runs this effect against
  // the new route.
  const firedInitialFlyRef = useRef(false);
  useEffect(() => {
    if (!initialFlyToChannelId) return;
    if (firedInitialFlyRef.current) return;
    if (!nodes || nodes.length === 0) return;
    const found = nodes.find((n) => n.channel_id === initialFlyToChannelId);
    if (!found) return;
    if (flyToChannel(initialFlyToChannelId)) {
      firedInitialFlyRef.current = true;
    }
  }, [initialFlyToChannelId, nodes, flyToChannel]);

  const firedInitialNodeFlyRef = useRef(false);
  useEffect(() => {
    if (!initialFlyToNodeId) return;
    if (firedInitialNodeFlyRef.current) return;
    if (!nodes || nodes.length === 0) return;
    const found = nodes.find((n) => n.id === initialFlyToNodeId);
    if (!found) return;
    if (flyToNodeById(initialFlyToNodeId)) {
      firedInitialNodeFlyRef.current = true;
      if (found.bot_id) {
        setSelectedSpatialObject({ kind: "bot", nodeId: found.id });
      } else if (found.channel_id) {
        setSelectedSpatialObject({ kind: "channel", nodeId: found.id });
      } else if (found.widget_pin_id) {
        setSelectedSpatialObject({ kind: "widget", nodeId: found.id });
      }
    }
  }, [initialFlyToNodeId, nodes, flyToNodeById]);

  // Pan + scale the camera so the Now Well fills the viewport with a small
  // padding margin. Uses the same scale-derivation trick as `diveToChannel`
  // but without the route change at the end.
  // Center the camera on an arbitrary world point. Used by the minimap
  // click-to-fly handler. Caps scale at 1.0 so a click on a distant region
  // doesn't slam the user into max-zoom over empty space; preserves any
  // scale below 1.0 the user has set so they don't lose context.
  const flyToWorldPoint = useCallback(
    (wx: number, wy: number) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const targetScale = Math.min(1.0, cameraRef.current.scale);
      const targetX = rect.width / 2 - wx * targetScale;
      const targetY = rect.height / 2 - wy * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
    },
    [lensEngaged, triggerLensSettle, scheduleCamera],
  );

  const flyToStarboardObject = useCallback(
    (wx: number, wy: number) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const currentScale = cameraRef.current.scale;
      const targetScale = Math.min(MAX_SCALE, Math.max(currentScale, 0.42));
      const targetX = rect.width / 2 - wx * targetScale;
      const targetY = rect.height / 2 - wy * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
    },
    [lensEngaged, triggerLensSettle, scheduleCamera],
  );

  const focusNode = useCallback(
    (node: SpatialNode) => {
      flyToStarboardObject(node.world_x + node.world_w / 2, node.world_y + node.world_h / 2);
    },
    [flyToStarboardObject],
  );

  const selectNode = useCallback(
    (kind: "channel" | "bot" | "widget", node: SpatialNode, focus = false) => {
      setSelectedSpatialObject({ kind, nodeId: node.id });
      setContextMenu(null);
      if (focus) focusNode(node);
    },
    [focusNode],
  );

  const selectLandmark = useCallback(
    (id: "now_well" | "memory_observatory" | "attention_hub" | "daily_health", x: number, y: number, focus = false) => {
      setSelectedSpatialObject({ kind: "landmark", id });
      setContextMenu(null);
      if (focus) flyToStarboardObject(x, y);
    },
    [flyToStarboardObject],
  );

  const flyToWell = useCallback(() => {
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    const wellWidth = WELL_R_MAX * 2.4;
    const wellHeight = WELL_R_MAX * WELL_Y_SQUASH * 2.4;
    const targetScale = Math.min(
      rect.width / wellWidth,
      rect.height / wellHeight,
    );
    const targetX = rect.width / 2 - wellPos.x * targetScale;
    const targetY = rect.height / 2 - wellPos.y * targetScale;
    scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
  }, [scheduleCamera, wellPos.x, wellPos.y]);

  const flyToMemoryObservatory = useCallback(() => {
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    const targetScale = Math.min(0.9, Math.max(0.55, cameraRef.current.scale));
    scheduleCamera({
      x: rect.width / 2 - memoryObsPos.x * targetScale,
      y: rect.height / 2 - memoryObsPos.y * targetScale,
      scale: targetScale,
    }, "immediate");
  }, [scheduleCamera, memoryObsPos.x, memoryObsPos.y]);

  const starboardObjects = useMemo<StarboardObjectItem[]>(() => {
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
    const items: StarboardObjectItem[] = [
      {
        id: "landmark-memory-observatory",
        label: "Memory Observatory",
        kind: "landmark",
        subtitle: "Landmark",
        worldX: memoryObsPos.x,
        worldY: memoryObsPos.y,
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
        worldX: wellPos.x,
        worldY: wellPos.y,
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
        worldX: attentionHubPos.x,
        worldY: attentionHubPos.y,
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
        worldX: dailyHealthPos.x,
        worldY: dailyHealthPos.y,
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
        items.push({
          id: `node-${node.id}`,
          label: channel ? `#${channel.name}` : "Channel",
          kind: "channel",
          subtitle: "Channel",
          worldX,
          worldY,
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
            { label: "Open channel", icon: "open", onSelect: () => navigate(`/channels/${node.channel_id}`, { state: canvasBackState }) },
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
        items.push({
          id: `node-${node.id}`,
          label: node.pin.panel_title || node.pin.display_label || node.pin.tool_name || "Widget",
          kind: "widget",
          subtitle: node.pin.tool_name || "Widget",
          worldX,
          worldY,
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
        items.push({
          id: `node-${node.id}`,
          label: botName,
          kind: "bot",
          subtitle: "Bot",
          worldX,
          worldY,
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
    return items.sort((a, b) => a.distance - b.distance || a.label.localeCompare(b.label));
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
    location.pathname,
    location.search,
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
  ]);


  // Register canvas commands as palette items. They appear under the
  // "Canvas" group at the top of ⌘K while the canvas is mounted, replacing
  // the previous SVG radial wheel. Handler bindings mirror the radial action
  // bundle the deleted menu used. Lives below `flyToWell` so the action
  // closure can reference it.
  useEffect(() => {
    return usePaletteActions.getState().register("spatial-canvas", [
      {
        id: "canvas-recenter",
        label: "Canvas: Recenter",
        category: "Canvas",
        icon: Home,
        onSelect: () => scheduleCamera(DEFAULT_CAMERA, "immediate"),
      },
      {
        id: "canvas-fit-all",
        label: "Canvas: Fit all",
        category: "Canvas",
        icon: Maximize2,
        onSelect: () => fitAllNodes(),
      },
      {
        id: "canvas-fly-to-now",
        label: "Canvas: Fly to Now",
        category: "Canvas",
        icon: Target,
        onSelect: () => flyToWell(),
      },
      {
        id: "canvas-fly-to-memory",
        label: "Canvas: Fly to Memory Observatory",
        category: "Canvas",
        icon: Brain,
        onSelect: () => flyToMemoryObservatory(),
      },
      {
        id: "canvas-open-attention-hub",
        label: "Canvas: Open Attention Hub",
        category: "Canvas",
        icon: Radar,
        onSelect: () => openStarboardAttention(),
      },
      {
        id: "canvas-toggle-arrange",
        label: interactionMode === "arrange" ? "Canvas: Browse mode" : "Canvas: Arrange mode",
        hint: interactionMode,
        category: "Canvas",
        icon: Move,
        onSelect: () => setInteractionMode((mode) => (mode === "arrange" ? "browse" : "arrange")),
      },
      {
        id: "canvas-cycle-activity",
        label: "Canvas: Cycle activity",
        hint: densityIntensity === "off" ? "off" : densityIntensity,
        category: "Canvas",
        icon: Sparkles,
        onSelect: () => cycleDensityIntensity(),
      },
      {
        id: "canvas-cycle-trails",
        label: "Canvas: Cycle trails",
        hint: trailsMode,
        category: "Canvas",
        icon: Footprints,
        onSelect: () => cycleTrailsMode(),
      },
      {
        id: "canvas-toggle-lines",
        label: connectionsEnabled ? "Canvas: Hide connection lines" : "Canvas: Show connection lines",
        category: "Canvas",
        icon: Link2,
        onSelect: () => setConnectionsEnabled((v) => !v),
      },
      {
        id: "canvas-toggle-map",
        label: minimapVisible ? "Canvas: Hide minimap" : "Canvas: Show minimap",
        category: "Canvas",
        icon: MapIcon,
        onSelect: () => setMinimapVisible((v) => !v),
      },
      {
        id: "canvas-toggle-landmark-beacons",
        label: landmarkBeaconsVisible ? "Canvas: Hide edge beacons" : "Canvas: Show edge beacons",
        category: "Canvas",
        icon: Locate,
        onSelect: () => setLandmarkBeaconsVisible((v) => !v),
      },
      {
        id: "canvas-toggle-attention-signals",
        label: attentionSignalsVisible ? "Canvas: Hide attention signals" : "Canvas: Show attention signals",
        category: "Canvas",
        icon: Radar,
        onSelect: () => setAttentionSignalsVisible((v) => !v),
      },
      {
        id: "canvas-toggle-bots",
        label: botsVisible ? "Canvas: Hide bots" : "Canvas: Show bots",
        category: "Canvas",
        icon: UsersIcon,
        onSelect: () => setBotsVisible((v) => !v),
      },
    ]);
  }, [
    scheduleCamera,
    fitAllNodes,
    flyToWell,
    flyToMemoryObservatory,
    openStarboardAttention,
    interactionMode,
    cycleDensityIntensity,
    cycleTrailsMode,
    densityIntensity,
    trailsMode,
    connectionsEnabled,
    minimapVisible,
    landmarkBeaconsVisible,
    attentionSignalsVisible,
    botsVisible,
  ]);

  // Expose canvas actions on window for screenshot/video recording. The
  // radial menu is the in-product surface; recordings need a stable hook
  // that doesn't depend on portal-mount timing or keyboard focus state.
  // `panTo` interpolates with requestAnimationFrame so video pans look
  // cinematic instead of jumpy — the inline-style world transform has no
  // CSS transition, so the tween has to live here.
  useEffect(() => {
    if (typeof window === "undefined") return;
    let panRaf = 0;
    const cancelPan = () => {
      if (panRaf) {
        window.cancelAnimationFrame(panRaf);
        panRaf = 0;
      }
    };
    const easeInOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
    const panTo = (target: { x: number; y: number; scale: number }, durationMs = 1200) => {
      cancelPan();
      const start = { ...cameraRef.current };
      const t0 = performance.now();
      const tick = (now: number) => {
        const t = Math.min(1, (now - t0) / Math.max(16, durationMs));
        const k = easeInOut(t);
        const next = {
          x: start.x + (target.x - start.x) * k,
          y: start.y + (target.y - start.y) * k,
          scale: start.scale + (target.scale - start.scale) * k,
        };
        scheduleCamera(next, t === 1 ? "immediate" : "idle");
        if (t < 1) panRaf = window.requestAnimationFrame(tick);
        else panRaf = 0;
      };
      panRaf = window.requestAnimationFrame(tick);
    };
    const flyToWorldPanned = (wx: number, wy: number, scale?: number, durationMs = 1200) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const targetScale = typeof scale === "number" ? scale : cameraRef.current.scale;
      panTo({ x: rect.width / 2 - wx * targetScale, y: rect.height / 2 - wy * targetScale, scale: targetScale }, durationMs);
    };
    (window as unknown as { __spindrelSpatial?: object }).__spindrelSpatial = {
      recenter: () => scheduleCamera(DEFAULT_CAMERA, "immediate"),
      flyToNow: () => flyToWell(),
      flyToMemory: () => flyToMemoryObservatory(),
      fitAll: () => fitAllNodes(),
      flyToChannel: (channelId: string) => flyToChannel(channelId),
      setCamera: (next: { x: number; y: number; scale: number }) => scheduleCamera(next, "immediate"),
      panTo,
      flyToPoint: flyToWorldPanned,
      cancelPan,
      getCamera: () => ({ ...cameraRef.current }),
      getNodes: () =>
        (nodesRef.current ?? []).map((n) => ({
          id: n.id,
          channel_id: n.channel_id,
          bot_id: n.bot_id,
          widget_pin_id: n.widget_pin_id,
          world_x: n.world_x,
          world_y: n.world_y,
          world_w: n.world_w,
          world_h: n.world_h,
        })),
    };
    return cancelPan;
  }, [scheduleCamera, flyToWell, flyToMemoryObservatory, fitAllNodes, flyToChannel]);

  const flyToWorldBounds = useCallback(
    (bounds: { x: number; y: number; w: number; h: number }, minScale = CHANNEL_CLUSTER_EXIT_SCALE + 0.06) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const margin = 0.18;
      const targetScale = Math.max(
        minScale,
        Math.min(
          0.62,
          Math.min(
            rect.width / Math.max(1, bounds.w * (1 + margin * 2)),
            rect.height / Math.max(1, bounds.h * (1 + margin * 2)),
          ),
        ),
      );
      const cx = bounds.x + bounds.w / 2;
      const cy = bounds.y + bounds.h / 2;
      scheduleCamera({
        scale: targetScale,
        x: rect.width / 2 - cx * targetScale,
        y: rect.height / 2 - cy * targetScale,
      }, "immediate");
    },
    [scheduleCamera],
  );

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
      const node = (nodes ?? []).find((n) => n.id === e.active.id);
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

  const selectionRail = useMemo(() => {
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
      const cluster = channelClusters.find((entry) => entry.id === selectedSpatialObject.id);
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

    const node = (nodes ?? []).find((entry) => entry.id === selectedSpatialObject.nodeId);
    if (!node) return null;
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
        meta: "Channel",
        leading: <MessageCircle className="h-4 w-4" />,
        actions: [
          { id: "focus", label: "Focus", icon: Locate, onSelect: (event) => { event.stopPropagation(); focus(); } },
          { id: "dive", label: "Dive", icon: ZoomIn, onSelect: (event) => { event.stopPropagation(); dive(); } },
          { id: "chat", label: "Open chat", icon: MessageCircle, onSelect: (event) => { event.stopPropagation(); openChat(); } },
          moreAction([
            { label: "Dive into channel", icon: <ZoomIn size={14} />, onClick: dive },
            { label: "Fly camera here", icon: <Locate size={14} />, onClick: focus },
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
        meta: "Bot",
        leading: <Bot className="h-4 w-4" />,
        actions: [
          { id: "focus", label: "Focus", icon: Locate, onSelect: (event) => { event.stopPropagation(); focus(); } },
          { id: "chat", label: channel ? "Open chat" : "No channel available", icon: MessageCircle, disabled: !channel, onSelect: (event) => { event.stopPropagation(); openChat(); } },
          { id: "settings", label: "Bot settings", icon: Settings, onSelect: (event) => { event.stopPropagation(); openSettings(); } },
          moreAction([
            { label: "Fly camera here", icon: <Locate size={14} />, onClick: focus },
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
        meta: "Widget",
        leading: <Box className="h-4 w-4" />,
        actions: [
          { id: "focus", label: "Focus", icon: Locate, onSelect: (event) => { event.stopPropagation(); focus(); } },
          { id: "open-full", label: "Open full", icon: Maximize2, onSelect: (event) => { event.stopPropagation(); openFull(); } },
          { id: "source", label: sourceId ? "Open source" : "No source channel", icon: ExternalLink, disabled: !sourceId, onSelect: (event) => { event.stopPropagation(); openSource(); } },
          moreAction([
            { label: "Open full widget", icon: <Maximize2 size={14} />, onClick: openFull },
            { label: "Fly camera here", icon: <Locate size={14} />, onClick: focus },
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
    openStarboardHealth,
    flyToStarboardObject,
    focusNode,
    channelForBot,
    navigate,
    location.pathname,
    location.search,
    deleteNode,
    updateNode,
  ]);

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

  const handleContextMenu = useCallback(
    (e: ReactPointerEvent<HTMLDivElement> | React.MouseEvent<HTMLDivElement>) => {
      if (diving) return;
      const target = e.target as HTMLElement;
      const tileEl = target.closest("[data-tile-kind]") as HTMLElement | null;
      const tileKind = tileEl?.getAttribute("data-tile-kind");
      const list = nodes ?? [];
      // Resolve the node by walking up to the tile element and matching its
      // bounding-rect-equivalent — but our tiles don't carry a stable id
      // attribute today. Easier: derive node from screen → world → hit-test.
      const world = pointerToWorld(e.clientX, e.clientY);
      const hitNode = world
        ? list.find(
            (n) =>
              world.x >= n.world_x &&
              world.x <= n.world_x + n.world_w &&
              world.y >= n.world_y &&
              world.y <= n.world_y + n.world_h,
          ) ?? null
        : null;
      const hitCluster = tileKind === "channel-cluster" && world
        ? channelClusters.find((cluster) => {
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
            onClick: () => navigate(`/channels/${sourceId}`, { state: canvasBackState }),
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
        // Background — no tile under the cursor.
        const worldX = world?.x ?? 0;
        const worldY = world?.y ?? 0;
        const screenX = e.clientX;
        const screenY = e.clientY;
        // "Move <kind> here" picker. Builds a second-level menu of every
        // existing node of the chosen kind; clicking moves it so its CENTER
        // lands at the right-click point. Doubles as an escape hatch when a
        // tile glitches off-screen — pick it from the list and reseat it.
        const openMovePicker = (
          kind: "channel" | "widget" | "bot",
        ) => {
          const candidates = list.filter((n) => {
            if (kind === "channel") return Boolean(n.channel_id);
            if (kind === "widget") return Boolean(n.pin);
            return Boolean(n.bot_id);
          });
          const labelFor = (n: SpatialNode): string => {
            if (n.channel_id) {
              const c = channelsById.get(n.channel_id);
              return c?.name ? `#${c.name}` : "channel";
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
          // The menu re-opens with the picker; suppress the default
          // post-click close.
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
          onClick: () => scheduleCamera(DEFAULT_CAMERA, "immediate"),
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
          onClick: () => setConnectionsEnabled((v) => !v),
        });
      }
      setContextMenu({ screenX: e.clientX, screenY: e.clientY, items });
    },
    [
      diving,
      nodes,
      pointerToWorld,
      channelsById,
      diveToChannel,
      flyToChannel,
      deleteNode,
      navigate,
      updateNode,
      location.pathname,
      location.search,
      channelForBot,
      fitAllNodes,
      trailsMode,
      cycleTrailsMode,
      connectionsEnabled,
      scheduleCamera,
      channelClusters,
      flyToWorldBounds,
    ],
  );

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
      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div ref={worldRef} className="absolute inset-0" style={worldStyle}>
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
          {!channelClusterMode && (upcomingItems ?? []).map((item) => {
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
          {!channelClusterMode && taskDefinitions.map((task, idx) => {
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
          {!channelClusterMode && firePulses.map((pulse) => {
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
          {channelClusters.map((cluster) => {
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
                  onFocus={() => {
                    setSelectedSpatialObject({ kind: "channel-cluster", id: cluster.id });
                    setContextMenu(null);
                  }}
                  onDiveWinner={() =>
                    diveToChannel(cluster.winner.channel.id, {
                      x: winnerNode.world_x,
                      y: winnerNode.world_y,
                      w: winnerNode.world_w,
                      h: winnerNode.world_h,
                    })
                  }
                />
                {attentionSignalsVisible && (
                  <SpatialAttentionSignal
                    items={cluster.members.flatMap((member) => attentionByNodeId.get(member.node.id) ?? [])}
                    scale={camera.scale}
                    onSelect={(item) => setSelectedAttentionId(item.id)}
                  />
                )}
              </div>
            );
          })}
          {standaloneWidgetClusters.map((cluster) => (
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
                  items={cluster.nodes.flatMap((node) => attentionByNodeId.get(node.id) ?? [])}
                  scale={camera.scale}
                  onSelect={(item) => setSelectedAttentionId(item.id)}
                />
              )}
            </div>
          ))}
          {(nodes ?? []).map((node) => {
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
                  diving={diving}
                  lens={lens}
                  lensSettling={lensSettling}
                  dragEnabled={dragEnabled}
                  onHoverChange={(hovered) =>
                    setHoveredNodeId((curr) => {
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
                  diving={diving}
                  dragEnabled={dragEnabled}
                  lens={draggingNodeId === node.id ? null : lens}
                  lensSettling={lensSettling}
                  reduced={botsReduced}
                  onPointerDown={(e) => handleBotPointerDown(node, e)}
                  onPointerMove={(e) => handleBotPointerMove(node, e)}
                  onPointerUp={(e) => handleBotPointerUp(node, e)}
                  onHoverChange={(hovered) =>
                    setHoveredNodeId((curr) => {
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
                  />
                </ManualBotNode>
              );
            }
            // Widget node — render via embedded pin payload. Card zoom hosts
            // live iframe/native/component bodies when the tile is in the
            // viewport; far tiers stay lightweight. If `pin` is missing the
            // node points at a vanished pin row — render nothing rather than
            // a broken placeholder; the next list refresh should clean it up.
            if (!node.pin) return null;
            // Frameless game widgets get a scoped drag activator so empty
            // areas around the floating asteroid stay canvas-pannable. At
            // chip/title zoom levels there is no visible grabber, so the
            // glyph itself must stay draggable through the normal activator.
            const isFramelessGame =
              node.pin.tool_name?.startsWith("core/game_") ?? false;
            const useScopedGrabber = isFramelessGame && interactiveZoom >= 0.6;
            return (
              <DraggableNode
                key={node.id}
                node={node}
                scale={camera.scale}
                isDragging={draggingNodeId === node.id}
                diving={diving}
                lens={lens}
                lensSettling={lensSettling}
                dragEnabled={dragEnabled}
                activatorMode={useScopedGrabber ? "scoped" : "full"}
                onScopedDragStart={() => {
                  setDraggingNodeId(node.id);
                  setActivatedTileId(null);
                  if (lensEngaged) {
                    setLensEngaged(false);
                    triggerLensSettle();
                  }
                }}
                onScopedDragEnd={() => {
                  setDraggingNodeId((curr) => (curr === node.id ? null : curr));
                }}
                onHoverChange={(hovered) =>
                  setHoveredNodeId((curr) => {
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
                  onActivate={handleActivate}
                  onSelect={() => selectNode("widget", node)}
                />
              </DraggableNode>
            );
          })}
          {(nodes ?? []).map((node) => {
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
                    onSelect={openStarboardAttention}
                  />
                )}
              </div>
            );
          })}
        </div>
      </DndContext>
      <LensHint />
      {selectionRail && (
        <SpatialSelectionRail
          x={selectionRail.x}
          y={selectionRail.y}
          label={selectionRail.label}
          meta={selectionRail.meta}
          leading={selectionRail.leading}
          actions={selectionRail.actions}
        />
      )}
      {diveCandidate && (
        <DivePulseOverlay channelLabel={diveCandidate.label} />
      )}
      <MemoryObservationPanel
        selection={memorySelection}
        onClose={() => setMemorySelection(null)}
      />
      {landmarkBeaconsVisible && (
        <SpatialEdgeBeacons
          camera={camera}
          viewport={viewportSize}
          beacons={edgeBeacons}
          maxVisible={9}
        />
      )}
      <div
        className="absolute top-4 right-4 z-[2] flex flex-row items-stretch gap-2"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <AddWidgetButton
          onClick={() => {
            setPinPositionOverride(null);
            openStarboardLaunch();
          }}
        />
        <button
          type="button"
          title={interactionMode === "arrange" ? "Arrange mode on. Click to return to Browse." : "Arrange items"}
          aria-pressed={interactionMode === "arrange"}
          onClick={() => setInteractionMode((mode) => (mode === "arrange" ? "browse" : "arrange"))}
          className={`inline-flex h-10 items-center gap-1.5 rounded-md border px-3 text-sm font-medium shadow-sm transition-colors ${
            interactionMode === "arrange"
              ? "border-accent/50 bg-accent/10 text-accent"
              : "border-surface-border/70 bg-surface-raised/80 text-text-muted hover:bg-surface-overlay hover:text-text"
          }`}
        >
          <Move size={16} />
          {interactionMode === "arrange" && <span className="hidden sm:inline">Arrange</span>}
        </button>
        <UsageDensityChrome
          intensity={densityIntensity}
          onCycleIntensity={cycleDensityIntensity}
          window={densityWindow}
          onWindowChange={setDensityWindow}
          compare={densityCompare}
          onCompareChange={setDensityCompare}
          animate={densityAnimate}
          onAnimateChange={setDensityAnimate}
          connectionsEnabled={connectionsEnabled}
          onConnectionsToggle={() => setConnectionsEnabled((v) => !v)}
          botsVisible={botsVisible}
          onBotsVisibleChange={setBotsVisible}
          botsReduced={botsReduced}
          onBotsReducedChange={setBotsReduced}
          landmarkBeaconsVisible={landmarkBeaconsVisible}
          onLandmarkBeaconsVisibleChange={setLandmarkBeaconsVisible}
          attentionSignalsVisible={attentionSignalsVisible}
          onAttentionSignalsVisibleChange={setAttentionSignalsVisible}
          onOpenPalette={() => useUIStore.getState().openPalette()}
          objects={starboardObjects}
          open={starboardOpen}
          station={starboardStation}
          onOpenChange={setStarboardOpen}
          onStationChange={setStarboardStation}
          attentionItems={attentionItems ?? []}
          selectedAttentionId={selectedAttentionId}
          onSelectAttention={(item) => setSelectedAttentionId(item?.id ?? null)}
          onReplyAttention={handleAttentionReply}
          launchWorldCenter={
            pinPositionOverride
              ? { x: pinPositionOverride.x + 160, y: pinPositionOverride.y + 110 }
              : viewportSize.w && viewportSize.h
                ? {
                    x: (viewportSize.w / 2 - cameraRef.current.x) / cameraRef.current.scale,
                    y: (viewportSize.h / 2 - cameraRef.current.y) / cameraRef.current.scale,
                  }
                : null
          }
        />
      </div>
      {/* Canvas commands now live in ⌘K via `usePaletteActions` registration
          below. The previous `<SpatialRadialMenu>` was removed in favor of the
          unified palette so canvas chrome matches the rest of the app. */}
      {minimapVisible && (
        <Minimap
          camera={camera}
          viewport={viewportSize}
          nodes={nodes ?? []}
          onJumpTo={flyToWorldPoint}
          onClose={() => setMinimapVisible(false)}
        />
      )}
      {contextMenu && (
        <SpatialContextMenu
          screenX={contextMenu.screenX}
          screenY={contextMenu.screenY}
          items={contextMenu.items}
          onClose={() => setContextMenu(null)}
        />
      )}
      {openBotChat && (
        <ChatSession
          source={{ kind: "channel", channelId: openBotChat.channelId }}
          shape="dock"
          open={true}
          onClose={() => {
            setOpenBotChat(null);
            setSessionPickerOpen(false);
          }}
          title={`${openBotChat.botName} in #${openBotChat.channelName}`}
          initiallyExpanded
          dockCollapsedTitle={openBotChat.botName}
          dockCollapsedSubtitle={`#${openBotChat.channelName}`}
          dismissMode="close"
          onOpenSessions={() => setSessionPickerOpen(true)}
        />
      )}
      {openBotChat && (
        <SessionPickerOverlay
          open={sessionPickerOpen}
          onClose={() => setSessionPickerOpen(false)}
          channelId={openBotChat.channelId}
          botId={openBotChat.botId}
          channelLabel={openBotChat.channelName}
          onActivateSurface={(surface: ChannelSessionSurface) => {
            setSessionPickerOpen(false);
            setOpenBotChat(null);
            navigate(buildChannelSessionRoute(openBotChat.channelId, surface));
          }}
        />
      )}
    </div>
  );
}

/**
 * Passive landmark at world (0,0). Two faint dashed rings + a center dot —
 * enough to reorient when the user has panned far away or zoomed all the
 * way out, subtle enough to stay out of the way at close zoom. Inset-0
 * tile bounds at index 0 will partially overlap the inner ring; the visible
 * arc still reads as "you're near the origin."
 */
function OriginMarker() {
  return (
    <div
      className="absolute pointer-events-none"
      style={{ left: 0, top: 0 }}
      aria-hidden
    >
      <div
        className="absolute rounded-full border border-dashed border-text-dim/25"
        style={{ width: 800, height: 800, left: -400, top: -400 }}
      />
      <div
        className="absolute rounded-full border border-dashed border-text-dim/35"
        style={{ width: 280, height: 280, left: -140, top: -140 }}
      />
      <div
        className="absolute rounded-full bg-text-dim/40"
        style={{ width: 8, height: 8, left: -4, top: -4 }}
      />
    </div>
  );
}

function AttentionHubLandmark({
  activeCount,
  mappedCount,
  signalsVisible,
  zoom,
  onOpen,
}: {
  activeCount: number;
  mappedCount: number;
  signalsVisible: boolean;
  zoom: number;
  onOpen: () => void;
}) {
  const compact = zoom < 0.45;
  const size = compact ? 178 : 220;
  const visibleCount = signalsVisible ? mappedCount : 0;
  return (
    <button
      type="button"
      className="absolute flex flex-col items-center justify-center rounded-full border border-warning/45 bg-surface-raised/85 text-text backdrop-blur transition-transform hover:scale-105 hover:border-warning/80"
      style={{
        left: -size / 2,
        top: -size / 2,
        width: size,
        height: size,
        zIndex: 4,
      }}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onOpen();
      }}
      title="Open Attention Hub"
    >
      <span className="absolute inset-4 rounded-full border border-warning/20" aria-hidden="true" />
      <span className="absolute inset-10 rounded-full border border-warning/25" aria-hidden="true" />
      <span className="absolute bottom-10 h-14 w-px bg-warning/45" aria-hidden="true" />
      <Radar className="mb-2 text-warning" size={compact ? 46 : 58} />
      {!compact && <span className="text-sm font-semibold">Attention Hub</span>}
      {signalsVisible && visibleCount > 0 ? (
        <span className="mt-1 rounded-full bg-warning/10 px-2.5 py-0.5 text-[11px] font-semibold text-warning">{visibleCount} mapped</span>
      ) : (
        <span className="mt-1 text-[11px] text-text-dim">{activeCount} active</span>
      )}
    </button>
  );
}
