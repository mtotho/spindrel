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
  Eye,
  Link2,
  Settings,
  ExternalLink,
  Trash2,
  Locate,
  Move,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { useChannels } from "../../api/hooks/useChannels";
import { useDashboards, channelIdFromSlug } from "../../stores/dashboards";
import {
  useSpatialNodes,
  useUpdateSpatialNode,
  useDeleteSpatialNode,
  type SpatialNode,
} from "../../api/hooks/useWorkspaceSpatial";
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
import { UsageDensityChrome } from "./UsageDensityChrome";
import { Minimap } from "./Minimap";
import { SpatialRadialMenu } from "./SpatialRadialMenu";
import { DivePulseOverlay } from "./DivePulseOverlay";
import { CanvasLibrarySheet } from "./CanvasLibrarySheet";
import { SpatialContextMenu, type SpatialContextMenuItem } from "./SpatialContextMenu";
import { DraggableNode } from "./DraggableNode";
import { ManualBotNode, BotTile } from "./BotNode";
import {
  AddWidgetButton,
  CanvasStarfield,
  LensHint,
  ShortcutChip,
} from "./SpatialCanvasChrome";
import { MovementTraceLayer } from "./MovementTraceLayer";
import { buildWidgetOverviewClusters } from "./widgetOverviewClusters";
import { ChatSession } from "../chat/ChatSession";
import { SessionPickerOverlay } from "../chat/SessionPickerOverlay";
import {
  buildChannelSessionRoute,
  type ChannelSessionSurface,
} from "../../lib/channelSessionSurfaces";
import { usePaletteOverrides } from "../../stores/paletteOverrides";
import {
  buildChannelSurfaceRoute,
  getChannelLastSurface,
} from "../../stores/channelLastSurface";
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
  clampCamera,
  loadStoredCamera,
  projectFisheye,
  getViewportWorldBbox,
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
const CAMERA_MOVING_CLASS_MS = 180;

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
}

export function SpatialCanvas({ onAfterDive, initialFlyToChannelId }: SpatialCanvasProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: nodes } = useSpatialNodes();
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
    if (cameraMovingTimerRef.current !== null) {
      window.clearTimeout(cameraMovingTimerRef.current);
    }
    cameraMovingTimerRef.current = window.setTimeout(() => {
      viewport.classList.remove("spatial-camera-moving");
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
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [openBotChat, setOpenBotChat] = useState<{
    botId: string;
    botName: string;
    channelId: string;
    channelName: string;
  } | null>(null);
  const [sessionPickerOpen, setSessionPickerOpen] = useState(false);

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
  // Radial command menu (Q-key or long-press background). Single anchor in
  // screen-space coords; null when closed. Top-of-document keyboard handler
  // sets it; long-press timer in the touch path also sets it.
  const [radialAnchor, setRadialAnchor] = useState<{ x: number; y: number } | null>(null);
  // Last-known cursor position for the Q keybind — the keybind has no event
  // location (keyboard, not pointer), so we keep a passive ref updated by
  // pointermove on the viewport. Falls back to viewport center.
  const cursorPosRef = useRef<{ x: number; y: number } | null>(null);
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
    } catch {
      /* storage disabled */
    }
  }, [densityIntensity, densityWindow, densityCompare, densityAnimate, connectionsEnabled, botsVisible, botsReduced, trailsMode, minimapVisible]);

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
      // Pan starts on any click that DIDN'T land on a tile. The world div
      // covers the entire viewport (absolute inset-0), so a strict
      // `target === currentTarget` check would only allow pan on the
      // viewport's literal edges — the gap area between tiles wouldn't
      // pan. Tile drag is owned by dnd-kit on the tile's listeners; this
      // handler stays out of its way.
      const target = e.target as HTMLElement;
      if (target.closest("[data-tile-kind]")) return;
      // Background click — release any activated widget tile.
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

  // Beam-me-up handoff. When the user clicks the "Beam to spatial canvas"
  // button on a channel route, ChannelHeader sets a sessionStorage flag with
  // the source channel id + timestamp before navigating home. On the canvas's
  // next mount, we look that flag up, find the matching tile, and recenter
  // the camera on it at a safe overview zoom (well below the push-through
  // dive threshold). Without this, the camera state loaded from localStorage
  // can leave the user already zoomed deep over the source tile, and the
  // dive detector immediately re-fires and sucks them back in.
  const beamConsumedRef = useRef(false);
  useEffect(() => {
    if (beamConsumedRef.current) return;
    if (!nodes || nodes.length === 0) return;
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    let raw: string | null = null;
    try {
      raw = sessionStorage.getItem("spatial.beamFromChannel");
    } catch {
      beamConsumedRef.current = true;
      return;
    }
    if (!raw) {
      beamConsumedRef.current = true;
      return;
    }
    try {
      sessionStorage.removeItem("spatial.beamFromChannel");
    } catch {
      // Ignore — flag will just expire on the timestamp check next time.
    }
    beamConsumedRef.current = true;
    let parsed: { channelId?: string; ts?: number } | null = null;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return;
    }
    if (!parsed?.channelId || typeof parsed.ts !== "number") return;
    if (Date.now() - parsed.ts > 5000) return;
    const tile = nodes.find((n) => n.channel_id === parsed!.channelId);
    if (!tile) return;
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
      if (e.key === "q" || e.key === "Q") {
        if (e.repeat || e.shiftKey) return;
        e.preventDefault();
        const rect = viewportRectRef.current;
        const fallback = {
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
        };
        setRadialAnchor((curr) => (curr ? null : cursorPosRef.current ?? fallback));
        return;
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [diving, draggingNodeId, fitAllNodes, zoomAroundPoint]);

  // Passive cursor tracker for the Q keybind anchor. Lives outside the
  // pointer-handling paths so it never interferes with pan/drag.
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      cursorPosRef.current = { x: e.clientX, y: e.clientY };
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);

  // Touch long-press on canvas background → radial menu. Only fires when
  // the press lands on the viewport background (not on a tile / chrome) and
  // doesn't move > 8px during the 350ms hold. Tile long-press is owned by
  // dnd-kit's TouchSensor — separable because the events fire on different
  // elements.
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
        setRadialAnchor({ x: startX, y: startY });
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
      const orbit = definitionOrbit(taskId, taskDefinitions.length, idx);
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

  // Register the channel-pick override on the palette. While the canvas is
  // mounted, Cmd+K → channel selection flies the camera instead of routing
  // away. Cleared on unmount, so navigating to a channel page restores
  // default route behavior.
  useEffect(() => {
    usePaletteOverrides.getState().setChannelPick(flyToChannel);
    return () => {
      usePaletteOverrides.getState().setChannelPick(null);
    };
  }, [flyToChannel]);

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

  const flyToWell = useCallback(() => {
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    const wellWidth = WELL_R_MAX * 2.4;
    const wellHeight = WELL_R_MAX * WELL_Y_SQUASH * 2.4;
    const targetScale = Math.min(
      rect.width / wellWidth,
      rect.height / wellHeight,
    );
    const targetX = rect.width / 2 - WELL_X * targetScale;
    const targetY = rect.height / 2 - WELL_Y * targetScale;
    scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
  }, [scheduleCamera]);

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
    [diving, pointerToWorld],
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

  const nowWellLens =
    lensEngaged && focalScreen
      ? projectFisheye(WELL_X, WELL_Y, camera, focalScreen, lensRadius)
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
      const orbit = upcomingOrbit(item, t);
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
      const bucket = upcomingOrbitBucket(item, tickedNow);
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
          label: "Activate widget",
          icon: <Eye size={14} />,
          onClick: () => setActivatedTileId(hitNode.id),
        });
        if (pin.source_channel_id) {
          const sourceId = pin.source_channel_id;
          items.push({
            label: "Open source channel",
            icon: <ExternalLink size={14} />,
            onClick: () => navigate(`/channels/${sourceId}`),
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
              state: { backTo: `${location.pathname}${location.search}` },
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
            setLibraryOpen(true);
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
              scale={camera.scale}
              viewportBbox={viewportBbox}
            />
          )}
          <MovementTraceLayer nodes={nodes ?? []} viewportBbox={viewportBbox} />
          <NowWell
            tickedNow={tickedNow}
            zoom={camera.scale}
            lens={nowWellLens}
          />
          {!channelClusterMode && (upcomingItems ?? []).map((item) => {
            const itemKey = upcomingReactKey(item);
            const spread = upcomingSpreadByKey.get(itemKey) ?? { index: 0, count: 1 };
            const orbit = upcomingOrbit(item, tickedNow, spread);
            const lens =
              lensEngaged && focalScreen
                ? projectFisheye(orbit.x, orbit.y, camera, focalScreen, lensRadius)
                : null;
            return (
              <UpcomingTile
                key={itemKey}
                item={item}
                zoom={camera.scale}
                tickedNow={tickedNow}
                spread={spread}
                extraScale={lens?.sizeFactor ?? 1}
                lens={lens}
              />
            );
          })}
          {!channelClusterMode && taskDefinitions.map((task, idx) => {
            const orbit = definitionOrbit(task.id, taskDefinitions.length, idx);
            const lens =
              lensEngaged && focalScreen
                ? projectFisheye(orbit.x, orbit.y, camera, focalScreen, lensRadius)
                : null;
            return (
              <TaskDefinitionTile
                key={task.id}
                task={task}
                zoom={camera.scale}
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
                  zoom={camera.scale}
                  showActivityGlow={densityIntensity !== "off"}
                  maxClusterTokens={maxClusterTokens}
                  widgetCount={widgetSatellitesByClusterId.get(cluster.id)?.length ?? 0}
                  widgetOpacity={widgetOverviewOpacity}
                  onFocus={() => flyToWorldBounds(cluster.worldBounds)}
                  onDiveWinner={() =>
                    diveToChannel(cluster.winner.channel.id, {
                      x: winnerNode.world_x,
                      y: winnerNode.world_y,
                      w: winnerNode.world_w,
                      h: winnerNode.world_h,
                    })
                  }
                />
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
                zoom={camera.scale}
                opacity={widgetOverviewOpacity}
              />
            </div>
          ))}
          {(nodes ?? []).map((node) => {
            if (node.channel_id && clusteredChannelNodeIds.has(node.id)) return null;
            if (channelClusterMode && node.bot_id) return null;
            if (channelClusterMode && node.pin) return null;
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
                    zoom={camera.scale}
                    extraScale={lens?.sizeFactor ?? 1}
                    botAvatarById={botAvatarById}
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
              const channel = channelForBot(node.bot_id);
              return (
                <ManualBotNode
                  key={node.id}
                  node={node}
                  isDragging={draggingNodeId === node.id}
                  diving={diving}
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
                  onClick={() => {
                    if (!channel) return;
                    setOpenBotChat({
                      botId: node.bot_id!,
                      botName,
                      channelId: channel.id,
                      channelName: channel.name,
                    });
                  }}
                  onDoubleClick={() =>
                    navigate(`/admin/bots/${node.bot_id}`, {
                      state: { backTo: `${location.pathname}${location.search}` },
                    })
                  }
                >
                  <BotTile
                    name={botName}
                    botId={node.bot_id}
                    avatarEmoji={node.bot?.avatar_emoji ?? null}
                    zoom={camera.scale}
                    reduced={botsReduced}
                    onOpenChat={() => {
                      if (!channel) return;
                      setOpenBotChat({
                        botId: node.bot_id!,
                        botName,
                        channelId: channel.id,
                        channelName: channel.name,
                      });
                    }}
                    chatDisabled={!channel}
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
            const useScopedGrabber = isFramelessGame && camera.scale >= 0.6;
            return (
              <DraggableNode
                key={node.id}
                node={node}
                scale={camera.scale}
                isDragging={draggingNodeId === node.id}
                diving={diving}
                lens={lens}
                lensSettling={lensSettling}
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
              >
                <WidgetTile
                  pin={node.pin}
                  zoom={camera.scale}
                  extraScale={lens?.sizeFactor ?? 1}
                  inViewport={isInViewport(node)}
                  activated={activatedTileId === node.id}
                  nodeId={node.id}
                  onActivate={handleActivate}
                />
              </DraggableNode>
            );
          })}
        </div>
      </DndContext>
      <LensHint />
      {diveCandidate && (
        <DivePulseOverlay channelLabel={diveCandidate.label} />
      )}
      <div
        className="absolute top-4 right-4 z-[2] flex flex-row items-stretch gap-2"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <AddWidgetButton onClick={() => setLibraryOpen(true)} />
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
        />
        <ShortcutChip />
      </div>
      {radialAnchor && (
        <SpatialRadialMenu
          anchor={radialAnchor}
          state={{
            activity: densityIntensity,
            trails: trailsMode,
            lines: connectionsEnabled,
            map: minimapVisible,
            bots: botsVisible,
          }}
          actions={{
            recenter: () => scheduleCamera(DEFAULT_CAMERA, "immediate"),
            fitAll: () => fitAllNodes(),
            flyToNow: () => flyToWell(),
            cycleActivity: () => cycleDensityIntensity(),
            cycleTrails: () => cycleTrailsMode(),
            toggleLines: () => setConnectionsEnabled((v) => !v),
            toggleMap: () => setMinimapVisible((v) => !v),
            toggleBots: () => setBotsVisible((v) => !v),
          }}
          onClose={() => setRadialAnchor(null)}
        />
      )}
      {minimapVisible && (
        <Minimap
          camera={camera}
          viewport={viewportSize}
          nodes={nodes ?? []}
          onJumpTo={flyToWorldPoint}
          onClose={() => setMinimapVisible(false)}
        />
      )}
      <CanvasLibrarySheet
        open={libraryOpen}
        onClose={() => {
          setLibraryOpen(false);
          setPinPositionOverride(null);
        }}
        worldCenter={
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
