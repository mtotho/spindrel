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
  useDraggable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  LayoutGrid,
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
import type { Channel } from "../../types/api";
import { ChannelTile } from "./ChannelTile";
import { ChannelClusterMarker } from "./ChannelClusterMarker";
import { WidgetTile } from "./WidgetTile";
import { WidgetClusterMarker } from "./WidgetClusterMarker";
import { NowWell } from "./NowWell";
import { UpcomingTile } from "./UpcomingTile";
import { ConnectionLineLayer } from "./ConnectionLineLayer";
import { MovementHistoryLayer } from "./MovementHistoryLayer";
import { UsageDensityLayer } from "./UsageDensityLayer";
import { UsageDensityChrome } from "./UsageDensityChrome";
import { Minimap } from "./Minimap";
import { SpatialRadialMenu } from "./SpatialRadialMenu";
import { DivePulseOverlay } from "./DivePulseOverlay";
import { CanvasLibrarySheet } from "./CanvasLibrarySheet";
import { SpatialContextMenu, type SpatialContextMenuItem } from "./SpatialContextMenu";
import { DragActivatorContext, type DragActivatorBundle } from "./dragActivatorContext";
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
  LENS_HINT_SEEN_KEY,
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
  intersectBbox,
  SVG_MAX_DIMENSION_PX,
  type Camera,
  type LensTransform,
  type WorldBbox,
} from "./spatialGeometry";
import { useIsMobile } from "../../hooks/useIsMobile";
import { useReducedMotion } from "../../hooks/useReducedMotion";
import {
  upcomingOrbitBucket,
  upcomingOrbit,
  upcomingReactKey,
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
  const { data: upcomingItems } = useSpatialUpcomingActivity(50);
  const updateNode = useUpdateSpatialNode();
  const deleteNode = useDeleteSpatialNode();

  // Live tick for the Now Well + orbital tile positions. Server data is
  // 60s-fresh (`useSpatialUpcomingActivity` refetchInterval), but tile radii decay
  // continuously toward the well between fetches — a 5s client tick keeps
  // motion smooth without spamming the network.
  const [tickedNow, setTickedNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setTickedNow(Date.now()), 5_000);
    return () => window.clearInterval(id);
  }, []);

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
  const [manualBotDrag, setManualBotDrag] = useState<{
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
  const channelActivity = useUsageBreakdown({
    group_by: "channel",
    after: activityAfter,
    before: activityBefore,
  });
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
  const [divePulseProgress, setDivePulseProgress] = useState(0);

  useEffect(() => {
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
    if (!diveCandidate) {
      setDivePulseProgress(0);
      return;
    }
    let raf: number | null = null;
    const start = performance.now();
    const tick = (t: number) => {
      const elapsed = t - start;
      const progress = Math.min(1, elapsed / DIVE_DWELL_MS);
      setDivePulseProgress(progress);
      if (progress >= 1) {
        diveToChannel(diveCandidate.channelId, diveCandidate.world);
        return;
      }
      raf = window.requestAnimationFrame(tick);
    };
    raf = window.requestAnimationFrame(tick);
    return () => {
      if (raf !== null) window.cancelAnimationFrame(raf);
    };
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
      setManualBotDrag({
        nodeId: node.id,
        pointerId: e.pointerId,
        grabDx: world.x - node.world_x,
        grabDy: world.y - node.world_y,
        currentX: node.world_x,
        currentY: node.world_y,
      });
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [diving, pointerToWorld],
  );

  const handleBotPointerMove = useCallback(
    (node: SpatialNode, e: ReactPointerEvent<HTMLDivElement>) => {
      if (!manualBotDrag || manualBotDrag.nodeId !== node.id || manualBotDrag.pointerId !== e.pointerId) return;
      const world = pointerToWorld(e.clientX, e.clientY);
      if (!world) return;
      e.preventDefault();
      e.stopPropagation();
      setManualBotDrag((drag) =>
        drag && drag.nodeId === node.id
          ? { ...drag, currentX: world.x - drag.grabDx, currentY: world.y - drag.grabDy }
          : drag,
      );
    },
    [manualBotDrag, pointerToWorld],
  );

  const handleBotPointerUp = useCallback(
    (node: SpatialNode, e: ReactPointerEvent<HTMLDivElement>) => {
      if (!manualBotDrag || manualBotDrag.nodeId !== node.id || manualBotDrag.pointerId !== e.pointerId) return;
      e.preventDefault();
      e.stopPropagation();
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* already released */
      }
      setDraggingNodeId(null);
      setManualBotDrag(null);
      if (manualBotDrag.currentX !== node.world_x || manualBotDrag.currentY !== node.world_y) {
        updateNode.mutate({
          nodeId: node.id,
          body: { world_x: manualBotDrag.currentX, world_y: manualBotDrag.currentY },
        });
      }
    },
    [manualBotDrag, updateNode],
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
              const dragPosition = manualBotDrag?.nodeId === node.id
                ? { x: manualBotDrag.currentX, y: manualBotDrag.currentY }
                : null;
              return (
                <ManualBotNode
                  key={node.id}
                  node={node}
                  isDragging={draggingNodeId === node.id}
                  diving={diving}
                  lens={dragPosition ? null : lens}
                  lensSettling={lensSettling}
                  dragPosition={dragPosition}
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
            // Widget node — render via embedded pin payload (P3a). The
            // live iframe at zoom ≥ 0.6 lands in P3b; for now all zoom
            // levels are static cards. If `pin` is missing the node points
            // at a vanished pin row — render nothing rather than a broken
            // placeholder; the next list refresh should clean it up.
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
        <DivePulseOverlay channelLabel={diveCandidate.label} progress={divePulseProgress} />
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

interface WidgetOverviewCluster {
  id: string;
  nodes: SpatialNode[];
  worldX: number;
  worldY: number;
}

function buildWidgetOverviewClusters({
  nodes,
  camera,
  excludedNodeIds,
  enabled,
  radius = 92,
}: {
  nodes: SpatialNode[];
  camera: Camera;
  excludedNodeIds: Set<string>;
  enabled: boolean;
  radius?: number;
}): WidgetOverviewCluster[] {
  if (!enabled) return [];
  const candidates = nodes
    .filter((node) => node.pin && !excludedNodeIds.has(node.id))
    .map((node) => {
      const cx = node.world_x + node.world_w / 2;
      const cy = node.world_y + node.world_h / 2;
      return {
        node,
        worldX: cx,
        worldY: cy,
        screenX: camera.x + cx * camera.scale,
        screenY: camera.y + cy * camera.scale,
      };
    })
    .sort((a, b) => a.node.id.localeCompare(b.node.id));
  const claimed = new Set<string>();
  const clusters: WidgetOverviewCluster[] = [];
  for (const seed of candidates) {
    if (claimed.has(seed.node.id)) continue;
    const members = candidates.filter((candidate) => {
      if (claimed.has(candidate.node.id)) return false;
      const dx = candidate.screenX - seed.screenX;
      const dy = candidate.screenY - seed.screenY;
      return Math.hypot(dx, dy) <= radius;
    });
    for (const member of members) claimed.add(member.node.id);
    const worldX = members.reduce((sum, member) => sum + member.worldX, 0) / members.length;
    const worldY = members.reduce((sum, member) => sum + member.worldY, 0) / members.length;
    clusters.push({
      id: `widget-cluster:${members.map((member) => member.node.id).join(":")}`,
      nodes: members.map((member) => member.node),
      worldX,
      worldY,
    });
  }
  return clusters;
}

function AddWidgetButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      onPointerDown={(e) => e.stopPropagation()}
      title="Add widget to canvas"
      aria-label="Add widget to canvas"
      className="flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-surface-raised/85 backdrop-blur border border-surface-border text-text-dim hover:text-accent text-xs cursor-pointer"
    >
      <LayoutGrid size={13} />
      <span className="hidden sm:inline">Add</span>
    </button>
  );
}

function MovementTraceLayer({ nodes, viewportBbox }: { nodes: SpatialNode[]; viewportBbox?: WorldBbox }) {
  const now = Date.now();
  const traces = nodes
    .map((node) => {
      const movement = node.last_movement;
      if (!movement?.from || !movement?.to || !movement.created_at) return null;
      const created = Date.parse(movement.created_at);
      if (!Number.isFinite(created)) return null;
      const age = now - created;
      const expiresAt = movement.expires_at ? Date.parse(movement.expires_at) : NaN;
      const ttlMs = Number.isFinite(expiresAt)
        ? expiresAt - created
        : Math.max(1, movement.ttl_minutes ?? 30) * 60_000;
      if (ttlMs <= 0 || age < 0 || age > ttlMs) return null;
      const opacity = Math.max(0.18, 1 - age / ttlMs);
      const fromX = movement.from.x + node.world_w / 2;
      const fromY = movement.from.y + node.world_h / 2;
      const toX = movement.to.x + node.world_w / 2;
      const toY = movement.to.y + node.world_h / 2;
      // Cull traces whose chord+halo bbox falls entirely outside the
      // viewport. The halo circle around `to` extends roughly node-radius
      // out, so pad the bbox before testing.
      if (viewportBbox) {
        const haloR = Math.max(node.world_w, node.world_h) * 0.7;
        const tb: WorldBbox = {
          minX: Math.min(fromX, toX) - haloR,
          minY: Math.min(fromY, toY) - haloR,
          maxX: Math.max(fromX, toX) + haloR,
          maxY: Math.max(fromY, toY) + haloR,
        };
        if (tb.minX > viewportBbox.maxX || tb.maxX < viewportBbox.minX
            || tb.minY > viewportBbox.maxY || tb.maxY < viewportBbox.minY) {
          return null;
        }
      }
      return { node, fromX, fromY, toX, toY, opacity };
    })
    .filter(Boolean) as Array<{
      node: SpatialNode;
      fromX: number;
      fromY: number;
      toX: number;
      toY: number;
      opacity: number;
    }>;
  if (traces.length === 0) return null;
  const xs = traces.flatMap((t) => [t.fromX, t.toX]);
  const ys = traces.flatMap((t) => [t.fromY, t.toY]);
  const contentBbox: WorldBbox = {
    minX: Math.min(...xs) - 80,
    minY: Math.min(...ys) - 80,
    maxX: Math.max(...xs) + 80,
    maxY: Math.max(...ys) + 80,
  };
  const drawBbox = viewportBbox ? intersectBbox(contentBbox, viewportBbox) : contentBbox;
  if (!drawBbox) return null;
  const minX = drawBbox.minX;
  const minY = drawBbox.minY;
  const width = Math.min(drawBbox.maxX - drawBbox.minX, SVG_MAX_DIMENSION_PX);
  const height = Math.min(drawBbox.maxY - drawBbox.minY, SVG_MAX_DIMENSION_PX);
  return (
    <svg
      className="absolute pointer-events-none overflow-visible"
      style={{ left: minX, top: minY, width, height }}
      aria-hidden
    >
      <defs>
        <marker
          id="spatial-move-arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="rgb(var(--color-accent))" />
        </marker>
      </defs>
      {traces.map((t) => (
        <g key={t.node.id} opacity={t.opacity}>
          <line
            x1={t.fromX - minX}
            y1={t.fromY - minY}
            x2={t.toX - minX}
            y2={t.toY - minY}
            stroke="rgb(var(--color-accent))"
            strokeWidth={2}
            strokeDasharray="6 5"
            markerEnd="url(#spatial-move-arrow)"
          />
          <circle
            cx={t.toX - minX}
            cy={t.toY - minY}
            r={Math.max(t.node.world_w, t.node.world_h) * 0.7}
            fill="none"
            stroke="rgb(var(--color-accent))"
            strokeWidth={2}
            strokeOpacity={0.35}
          />
        </g>
      ))}
    </svg>
  );
}

function BotTile({
  name,
  botId,
  avatarEmoji,
  zoom,
  reduced,
  onOpenChat,
  chatDisabled,
}: {
  name: string;
  botId: string;
  avatarEmoji: string | null;
  zoom: number;
  reduced: boolean;
  onOpenChat: () => void;
  chatDisabled: boolean;
}) {
  const compact = zoom < 0.55;
  const avatar = avatarEmoji || "🤖";
  const markerScale = compact ? Math.max(1, 34 / ((reduced ? 84 : 112) * Math.max(zoom, MIN_SCALE))) : 1;
  const labelScale = compact ? Math.max(1, 14 / (14 * Math.max(zoom, MIN_SCALE))) : 1;
  const outerSize = reduced ? 84 : 112;
  const innerSize = reduced ? 58 : 82;
  const emojiSize = reduced ? 28 : 38;
  const labelTop = reduced ? 108 : 132;
  const chatLeft = reduced ? 138 : 154;
  const chatTop = reduced ? 90 : 104;
  return (
    <div
      className="relative flex h-full w-full items-center justify-center overflow-visible"
      title={`${name} (${botId})`}
    >
      <div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-accent/55 bg-surface-raised shadow-[0_10px_28px_rgb(var(--color-accent)/0.12)]"
        style={{ width: outerSize, height: outerSize, scale: markerScale }}
      />
      <div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-surface-border/70 bg-surface flex items-center justify-center"
        style={{ width: innerSize, height: innerSize, fontSize: emojiSize, scale: markerScale }}
      >
        <span aria-hidden>{avatar}</span>
      </div>
      <div
        className="absolute left-1/2 max-w-[230px] text-center"
        style={{
          top: labelTop,
          transform: `translateX(-50%) scale(${labelScale})`,
          transformOrigin: "top center",
        }}
      >
        <div className={`truncate rounded-md bg-surface-raised/90 px-2.5 py-1 font-semibold leading-tight text-text shadow-sm ${compact ? "text-[14px]" : "text-[16px]"}`}>
          {name}
        </div>
      </div>
      <button
        type="button"
        disabled={chatDisabled}
        onClick={(e) => {
          e.stopPropagation();
          onOpenChat();
        }}
        onPointerDown={(e) => e.stopPropagation()}
        title={chatDisabled ? "No channel available for this bot" : "Open mini chat"}
        aria-label={chatDisabled ? "No channel available" : `Open mini chat with ${name}`}
        className="absolute flex h-8 w-8 items-center justify-center rounded-full border border-surface-border bg-surface text-text-dim hover:text-accent disabled:opacity-40 disabled:hover:text-text-dim"
        style={{ left: chatLeft, top: chatTop }}
      >
        <MessageCircle className="w-3.5 h-3.5" aria-hidden />
      </button>
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
/**
 * Subtle twinkling starfield rendered behind the spatial canvas world.
 * Sits below the dnd / world layers so panning and tile interaction are
 * unaffected; uses `pointer-events-none` to stay out of the way.
 *
 * Star positions are deterministic per-mount (seeded RNG) so the layout
 * is stable across re-renders within a session. Twinkle is a CSS
 * `@keyframes` opacity loop with phase offsets so individual stars
 * pulse out of sync — feels alive without being noisy.
 */
function CanvasStarfield() {
  const stars = useMemo(() => {
    let s = 0xc0ffee;
    function rand() {
      s |= 0;
      s = (s + 0x6d2b79f5) | 0;
      let t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    const out: Array<{ x: number; y: number; r: number; o: number; phase: number; dur: number; warm: number }> = [];
    for (let i = 0; i < 220; i++) {
      const tier = rand();
      out.push({
        x: rand() * 100,
        y: rand() * 100,
        r: tier > 0.97 ? 1.4 : tier > 0.85 ? 0.9 : 0.5,
        o: tier > 0.97 ? 0.85 : tier > 0.85 ? 0.55 : 0.30,
        phase: rand() * 8,
        dur: 4 + rand() * 4,
        warm: rand(),  // 0..1 — used to pick a color from the theme palette
      });
    }
    return out;
  }, []);
  return (
    <div className="canvas-starfield absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid slice"
      >
        {stars.map((s, i) => {
          // Three subtle blue-spectrum hues that read as "candle-blue starlight"
          // in light mode and stay luminous in dark mode. Mostly cool with a
          // few warm whites for variety.
          const fill =
            s.warm > 0.92 ? "var(--star-warm)" :
            s.warm > 0.6  ? "var(--star-blue-mid)" :
                            "var(--star-blue-deep)";
          return (
            <circle
              key={i}
              cx={s.x}
              cy={s.y}
              r={s.r * 0.05}
              fill={fill}
              opacity={s.o}
              style={{
                animation: `canvas-star-twinkle ${s.dur}s ease-in-out infinite`,
                animationDelay: `${s.phase}s`,
              }}
            />
          );
        })}
      </svg>
      <style>{`
        .canvas-starfield {
          /* Light mode — bluish "candle-blue" stars over the warm canvas bg */
          --star-blue-deep: #5a78c8;
          --star-blue-mid: #88aae0;
          --star-warm: #c8a878;
        }
        :root.dark .canvas-starfield,
        .dark .canvas-starfield {
          /* Dark mode — bright luminous stars */
          --star-blue-deep: #aac4ff;
          --star-blue-mid: #d8e3ff;
          --star-warm: #ffe9c0;
        }
        @keyframes canvas-star-twinkle {
          0%, 100% { opacity: 0.25; }
          50% { opacity: 1; }
        }
        @media (prefers-reduced-motion: reduce) {
          .canvas-starfield svg circle { animation: none !important; }
        }
      `}</style>
    </div>
  );
}

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

/**
 * Bottom-left onboarding pill — flashes the "hold Space to focus" gesture
 * exactly once per browser, then never again. localStorage flag
 * `LENS_HINT_SEEN_KEY` records that the user has seen it. The permanent
 * home for keyboard shortcut reference is the `<ShortcutChip />` top-right.
 */
function LensHint() {
  const [visible, setVisible] = useState(false);
  const [opacity, setOpacity] = useState(0);
  useEffect(() => {
    let seen = false;
    try {
      seen = localStorage.getItem(LENS_HINT_SEEN_KEY) === "1";
    } catch {
      /* storage disabled — show every time */
    }
    if (seen) return;
    setVisible(true);
    // Two-step fade: appear at 95% opacity, then ramp to 0 after 4500ms.
    const inT = window.setTimeout(() => setOpacity(0.95), 30);
    const outT = window.setTimeout(() => setOpacity(0), 4500);
    const removeT = window.setTimeout(() => {
      setVisible(false);
      try {
        localStorage.setItem(LENS_HINT_SEEN_KEY, "1");
      } catch {
        /* ignore */
      }
    }, 6000);
    return () => {
      window.clearTimeout(inT);
      window.clearTimeout(outT);
      window.clearTimeout(removeT);
    };
  }, []);
  if (!visible) return null;
  return (
    <div
      className="absolute bottom-4 left-4 z-[2] flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-md backdrop-blur border bg-surface-raised/85 border-surface-border text-text-dim text-xs select-none pointer-events-none"
      style={{ opacity, transition: "opacity 600ms ease-out" }}
      aria-live="polite"
    >
      <kbd className="rounded px-1.5 py-0 font-mono text-[10px] leading-tight border border-surface-border bg-surface-overlay/70 text-text-muted">
        Space
      </kbd>
      <span>hold to focus</span>
    </div>
  );
}

/**
 * Tiny `[⌘ Q]` indicator top-right — opens a popover listing every keyboard
 * shortcut on hover or focus. Discoverability home for the otherwise-hidden
 * shortcuts (Q for radial menu, Space for lens, F for fit-all, etc.).
 */
function ShortcutChip() {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="relative"
      onPointerEnter={() => setOpen(true)}
      onPointerLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label="Keyboard shortcuts"
        className="flex flex-row items-center gap-1 px-2 py-1.5 rounded-md bg-surface-raised/85 backdrop-blur border border-surface-border text-text-dim hover:text-text text-[11px] font-mono cursor-default"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <span>⌘</span>
        <span>Q</span>
      </button>
      {open && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-[3] flex flex-col gap-1 px-3 py-2.5 rounded-md bg-surface-raised/95 backdrop-blur border border-surface-border text-[11px] text-text-dim min-w-[240px] shadow-lg">
          <div className="text-[10px] uppercase tracking-wider text-text-muted mb-1">
            Keyboard
          </div>
          <ShortcutRow keys={["Q"]} label="Open command menu" />
          <ShortcutRow keys={["Space"]} label="Focus lens (hold)" />
          <ShortcutRow keys={["F"]} label="Fit all to viewport" />
          <ShortcutRow keys={["+", "−"]} label="Zoom in / out" />
          <ShortcutRow keys={["Esc"]} label="Close overlay or menu" />
          <div className="text-[10px] uppercase tracking-wider text-text-muted mt-2 mb-1">
            Pointer
          </div>
          <ShortcutRow keys={["Right-click"]} label="Context menu on tile" />
          <ShortcutRow keys={["Long-press"]} label="Touch: command menu / drag tile" />
        </div>
      )}
    </div>
  );
}

function ShortcutRow({ keys, label }: { keys: string[]; label: string }) {
  return (
    <div className="flex flex-row items-center gap-2">
      <div className="flex flex-row gap-1">
        {keys.map((k, i) => (
          <kbd
            key={i}
            className="rounded px-1.5 py-0 font-mono text-[10px] leading-tight border border-surface-border bg-surface-overlay/70 text-text-muted"
          >
            {k}
          </kbd>
        ))}
      </div>
      <span>{label}</span>
    </div>
  );
}

interface DraggableNodeProps {
  node: SpatialNode;
  scale: number;
  isDragging: boolean;
  diving: boolean;
  /** Per-tile fisheye projection. Null when the lens is not engaged. */
  lens: LensTransform | null;
  /** True for the engage/disengage transition window — apply a CSS
   *  transition; while the lens is steady-engaged + cursor moving, this is
   *  false so tiles track the cursor without lag. */
  lensSettling: boolean;
  /** Optional hover callback — used by the connection-line layer to
   *  brighten the line for the currently-hovered widget. */
  onHoverChange?: (hovered: boolean) => void;
  /** "full" wraps the children in the dnd-kit activator so the entire
   *  tile body starts a drag (default — channels, regular widgets).
   *  "scoped" provides the activator via `DragActivatorContext`; the
   *  child is responsible for attaching it to a specific element (e.g. a
   *  grip handle), which lets the rest of the tile fall through to the
   *  canvas pan. Used by frameless game widgets. */
  activatorMode?: "full" | "scoped";
  onScopedDragStart?: () => void;
  onScopedDragEnd?: () => void;
  children: React.ReactNode;
}

interface ManualBotNodeProps {
  node: SpatialNode;
  isDragging: boolean;
  diving: boolean;
  lens: LensTransform | null;
  lensSettling: boolean;
  dragPosition: { x: number; y: number } | null;
  reduced: boolean;
  onPointerDown: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp: (e: ReactPointerEvent<HTMLDivElement>) => void;
  /** Single-click action — typically "open mini chat". Wrapped in a
   *  ~220ms timer so a follow-up click resolves to `onDoubleClick` instead.
   *  Pass null/undefined to disable. */
  onClick?: () => void;
  onDoubleClick: () => void;
  /** Hover callback — used by the trails layer to reveal this bot's
   *  comet tail when the user points at it. */
  onHoverChange?: (hovered: boolean) => void;
  children: React.ReactNode;
}

function ManualBotNode({
  node,
  isDragging,
  diving,
  lens,
  lensSettling,
  dragPosition,
  reduced,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onClick,
  onDoubleClick,
  onHoverChange,
  children,
}: ManualBotNodeProps) {
  // Click-vs-double-click disambiguation: delay the single-click action so
  // that a follow-up second click within 220ms cancels it and resolves to
  // the navigate-to-admin double-click instead.
  const clickTimerRef = useRef<number | null>(null);
  const cancelPendingClick = () => {
    if (clickTimerRef.current !== null) {
      window.clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
  };
  useEffect(() => () => cancelPendingClick(), []);
  const lensTransform = lens
    ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})`
    : "";
  const reduceTransform = reduced ? "scale(0.82)" : "";
  const transformStack = [lensTransform, reduceTransform].filter(Boolean).join(" ");
  let transition: string;
  if (isDragging) {
    transition = "none";
  } else if (lensSettling) {
    transition = `transform ${LENS_SETTLE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`;
  } else if (lens) {
    transition = "none";
  } else {
    transition = "transform 120ms";
  }
  const style: CSSProperties = {
    position: "absolute",
    left: dragPosition?.x ?? node.world_x,
    top: dragPosition?.y ?? node.world_y,
    width: node.world_w,
    height: node.world_h,
    zIndex: isDragging ? 10 : node.z_index,
    transform: transformStack || undefined,
    transformOrigin: "center center",
    transition,
    touchAction: "none",
    cursor: diving ? "default" : isDragging ? "grabbing" : "grab",
    opacity: reduced ? 0.68 : 1,
  };
  return (
    <div
      style={style}
      data-tile-kind="bot"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onPointerEnter={onHoverChange ? () => onHoverChange(true) : undefined}
      onPointerLeave={onHoverChange ? () => onHoverChange(false) : undefined}
      onClick={(e) => {
        if (!onClick || diving || isDragging) return;
        // Don't fire when the click came from a child that wants its own
        // behavior (e.g. the inline MessageCircle button calls
        // stopPropagation, so it never reaches us). The avatar disc is the
        // bare canvas inside `children` — clicking it lands here.
        e.stopPropagation();
        cancelPendingClick();
        clickTimerRef.current = window.setTimeout(() => {
          clickTimerRef.current = null;
          onClick();
        }, 220);
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        cancelPendingClick();
        if (!diving && !isDragging) onDoubleClick();
      }}
    >
      {children}
    </div>
  );
}

function DraggableNode({
  node,
  scale,
  isDragging,
  diving,
  lens,
  lensSettling,
  onHoverChange,
  activatorMode = "full",
  onScopedDragStart,
  onScopedDragEnd,
  children,
}: DraggableNodeProps) {
  const updateNode = useUpdateSpatialNode();
  const [scopedDrag, setScopedDrag] = useState<{
    pointerId: number;
    startX: number;
    startY: number;
    dx: number;
    dy: number;
  } | null>(null);
  const { setNodeRef, setActivatorNodeRef, listeners, attributes, transform } = useDraggable({
    id: node.id,
    disabled: diving || activatorMode === "scoped",
  });
  const handleScopedPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      if (activatorMode !== "scoped" || diving || e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      setScopedDrag({
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        dx: 0,
        dy: 0,
      });
      onScopedDragStart?.();
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [activatorMode, diving, onScopedDragStart],
  );
  const handleScopedPointerMove = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      if (!scopedDrag || scopedDrag.pointerId !== e.pointerId) return;
      e.preventDefault();
      e.stopPropagation();
      setScopedDrag((drag) =>
        drag && drag.pointerId === e.pointerId
          ? { ...drag, dx: e.clientX - drag.startX, dy: e.clientY - drag.startY }
          : drag,
      );
    },
    [scopedDrag],
  );
  const finishScopedDrag = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      if (!scopedDrag || scopedDrag.pointerId !== e.pointerId) return;
      e.preventDefault();
      e.stopPropagation();
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* already released */
      }
      setScopedDrag(null);
      onScopedDragEnd?.();
      if (scopedDrag.dx === 0 && scopedDrag.dy === 0) return;
      updateNode.mutate({
        nodeId: node.id,
        body: {
          world_x: node.world_x + scopedDrag.dx / scale,
          world_y: node.world_y + scopedDrag.dy / scale,
        },
      });
    },
    [node.id, node.world_x, node.world_y, onScopedDragEnd, scale, scopedDrag, updateNode],
  );
  const activatorBundle: DragActivatorBundle = {
    setRef: activatorMode === "scoped" ? () => {} : setActivatorNodeRef,
    // dnd-kit's generated types don't have an index signature; cast through
    // `unknown` at the boundary so consumers get a stable shape.
    listeners: (activatorMode === "scoped"
      ? {
          onPointerDown: handleScopedPointerDown,
          onPointerMove: handleScopedPointerMove,
          onPointerUp: finishScopedDrag,
          onPointerCancel: finishScopedDrag,
        }
      : listeners) as unknown as DragActivatorBundle["listeners"],
    attributes: (activatorMode === "scoped"
      ? { role: "button", tabIndex: 0 }
      : attributes) as unknown as DragActivatorBundle["attributes"],
  };
  // dnd-kit returns a screen-pixel translate during drag. The tile lives
  // inside a parent that's scaled by `camera.scale`, so dividing by scale
  // makes the tile's screen movement match the cursor 1:1.
  const dragTranslate = transform
    ? `translate(${transform.x / scale}px, ${transform.y / scale}px)`
    : scopedDrag
    ? `translate(${scopedDrag.dx / scale}px, ${scopedDrag.dy / scale}px)`
    : "";
  // Fisheye contribution composes after drag: translate to projected position
  // (in world coords so it pre-multiplies through the parent's scale), then
  // shrink around the tile center. Order — drag first, then lens — means the
  // lens evaluates at the tile's authored position, not the dragged position
  // (drag is suppressed during lens engage anyway, so they don't collide).
  const lensTransform = lens
    ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})`
    : "";
  const transformStack = [dragTranslate, lensTransform].filter(Boolean).join(" ");
  // Transition priority: drag = none (must follow cursor 1:1).
  // Lens settling = 250ms ease-out (smooth pop-in / pop-out).
  // Otherwise default 120ms for nudges and post-drag commit.
  let transition: string;
  if (isDragging || scopedDrag) {
    transition = "none";
  } else if (lensSettling) {
    transition = `transform ${LENS_SETTLE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`;
  } else if (lens) {
    // Lens engaged + steady — track cursor with no transition.
    transition = "none";
  } else {
    transition = "transform 120ms";
  }
  const style: CSSProperties = {
    position: "absolute",
    left: node.world_x,
    top: node.world_y,
    width: node.world_w,
    height: node.world_h,
    zIndex: isDragging || scopedDrag ? 10 : node.z_index,
    transform: transformStack || undefined,
    transformOrigin: "center center",
    transition,
    touchAction: "none",
    pointerEvents: "none",
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      onPointerEnter={onHoverChange ? () => onHoverChange(true) : undefined}
      onPointerLeave={onHoverChange ? () => onHoverChange(false) : undefined}
    >
      <DragActivatorContext.Provider value={activatorBundle}>
        {activatorMode === "full" ? (
          <div
            ref={setActivatorNodeRef}
            style={{ display: "contents", pointerEvents: "auto" }}
            {...attributes}
            {...listeners}
          >
            {children}
          </div>
        ) : (
          // Scoped mode — child consumes the bundle via `useDragActivator`
          // and attaches it to a specific element (e.g. a grip handle).
          // The rest of the tile body stays click-through.
          children
        )}
      </DragActivatorContext.Provider>
    </div>
  );
}
