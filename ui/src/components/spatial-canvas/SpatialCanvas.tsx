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
  PointerSensor,
  useDraggable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { LayoutGrid, MessageCircle } from "lucide-react";
import { useChannels } from "../../api/hooks/useChannels";
import { useDashboards, channelIdFromSlug } from "../../stores/dashboards";
import {
  useSpatialNodes,
  useUpdateSpatialNode,
  type SpatialNode,
} from "../../api/hooks/useWorkspaceSpatial";
import { useSpatialUpcomingActivity } from "../../api/hooks/useUpcomingActivity";
import type { Channel } from "../../types/api";
import { ChannelTile } from "./ChannelTile";
import { WidgetTile } from "./WidgetTile";
import { NowWell } from "./NowWell";
import { UpcomingTile } from "./UpcomingTile";
import { ConnectionLineLayer } from "./ConnectionLineLayer";
import { UsageDensityLayer } from "./UsageDensityLayer";
import { UsageDensityChrome } from "./UsageDensityChrome";
import { CanvasLibrarySheet } from "./CanvasLibrarySheet";
import { ChatSession } from "../chat/ChatSession";
import { usePaletteOverrides } from "../../stores/paletteOverrides";
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
  loadConnectionsEnabled,
  loadDensityAnimate,
  loadDensityCompare,
  loadDensityIntensity,
  loadDensityWindow,
  loadBotsReduced,
  loadBotsVisible,
  clampCamera,
  loadStoredCamera,
  projectFisheye,
  type Camera,
  type LensTransform,
} from "./spatialGeometry";
import {
  upcomingOrbit,
  upcomingReactKey,
} from "./spatialActivity";

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

interface SpatialCanvasProps {
  /** Called after the dive animation completes and `router.push` has fired.
   *  Used by the overlay to close itself a tick after the route paints. */
  onAfterDive?: () => void;
}

export function SpatialCanvas({ onAfterDive }: SpatialCanvasProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: nodes } = useSpatialNodes();
  const { data: channels } = useChannels();
  const { data: upcomingItems } = useSpatialUpcomingActivity(50);
  const updateNode = useUpdateSpatialNode();

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

  const channelForBot = useCallback(
    (botId: string): Channel | null => {
      const all = channels ?? [];
      return (
        all.find((c) => c.bot_id === botId) ??
        all.find((c) => (c.member_bots ?? []).some((m) => m.bot_id === botId)) ??
        null
      );
    },
    [channels],
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
  const cameraRef = useRef(camera);
  cameraRef.current = camera;
  const [diving, setDiving] = useState(false);
  // Persist camera on every change EXCEPT during the dive transition. Dive
  // tweens the camera to a tile-fill target right before navigating away;
  // we want to remember the user's *pre-dive* exploration camera, not the
  // fully-zoomed-in dive target. Skipping the write while `diving` is true
  // freezes localStorage at the last pan/zoom the user authored, which is
  // what they expect when they return to the canvas.
  // localStorage writes are synchronous but cheap (sub-ms even at 60fps
  // pan); no debounce.
  useEffect(() => {
    if (diving) return;
    try {
      localStorage.setItem(CAMERA_STORAGE_KEY, JSON.stringify(camera));
    } catch {
      /* quota / disabled storage — silently skip */
    }
  }, [camera, diving]);
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

  // Token-usage density layer state. Defaults: subtle (on), 24h, channel-hued
  // (compare off), breathing on. Persisted to localStorage so the user's
  // preferred visual state survives reloads.
  const [densityIntensity, setDensityIntensity] = useState<DensityIntensity>(loadDensityIntensity);
  const [densityWindow, setDensityWindow] = useState<DensityWindow>(loadDensityWindow);
  const [densityCompare, setDensityCompare] = useState<boolean>(loadDensityCompare);
  const [densityAnimate, setDensityAnimate] = useState<boolean>(loadDensityAnimate);
  // Connection-line layer (widget → source channel curves). On by default —
  // the relationship is most of the value of pinning a widget to the canvas.
  const [connectionsEnabled, setConnectionsEnabled] = useState<boolean>(loadConnectionsEnabled);
  const [botsVisible, setBotsVisible] = useState<boolean>(loadBotsVisible);
  const [botsReduced, setBotsReduced] = useState<boolean>(loadBotsReduced);

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
    } catch {
      /* storage disabled */
    }
  }, [densityIntensity, densityWindow, densityCompare, densityAnimate, connectionsEnabled, botsVisible, botsReduced]);

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

  const viewportRef = useRef<HTMLDivElement>(null);

  const pointerToWorld = useCallback((clientX: number, clientY: number) => {
    const rect = viewportRef.current?.getBoundingClientRect();
    const c = cameraRef.current;
    if (!rect) return null;
    return {
      x: (clientX - rect.left - c.x) / c.scale,
      y: (clientY - rect.top - c.y) / c.scale,
    };
  }, []);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const update = () => {
      const r = el.getBoundingClientRect();
      setViewportSize({ w: r.width, h: r.height });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
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
      const rect = el.getBoundingClientRect();
      const p = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      lastCursorRef.current = p;
      if (lensEngaged) setFocalScreen(p);
    };
    el.addEventListener("pointermove", handler);
    return () => el.removeEventListener("pointermove", handler);
  }, [lensEngaged]);

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
        cameraX: camera.x,
        cameraY: camera.y,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [camera.x, camera.y, diving, activatedTileId, lensEngaged, triggerLensSettle],
  );

  const onBgPointerMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const p = panState.current;
    if (!p || p.pointerId !== e.pointerId) return;
    setCamera((c) =>
      clampCamera({
        ...c,
        x: p.cameraX + (e.clientX - p.startX),
        y: p.cameraY + (e.clientY - p.startY),
      }),
    );
  }, []);

  const onBgPointerUp = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const p = panState.current;
    if (!p || p.pointerId !== e.pointerId) return;
    panState.current = null;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
  }, []);

  // Manual wheel listener with { passive: false } — React's synthetic onWheel
  // is passive by default, so preventDefault() would be silently ignored and
  // the page would scroll underneath.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    function handler(e: WheelEvent) {
      if (diving) return;
      e.preventDefault();
      const rect = viewport!.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const factor = Math.exp(-e.deltaY * 0.001);
      setCamera((c) => {
        const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, c.scale * factor));
        const k = newScale / c.scale;
        return clampCamera({
          scale: newScale,
          x: cx - (cx - c.x) * k,
          y: cy - (cy - c.y) * k,
        });
      });
    }
    viewport.addEventListener("wheel", handler, { passive: false });
    return () => viewport.removeEventListener("wheel", handler);
  }, [diving]);

  const diveToChannel = useCallback(
    (channelId: string, world: { x: number; y: number; w: number; h: number }) => {
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!rect) return;
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
        setCamera(clampCamera({ x: targetX, y: targetY, scale: targetScale }));
      });
      // Animate-THEN-navigate: route change happens after the transition
      // completes. onAfterDive (overlay close) runs a tick later so the new
      // route paints before the overlay disappears.
      window.setTimeout(() => {
        navigate(`/channels/${channelId}`);
        if (onAfterDive) window.setTimeout(onAfterDive, 16);
      }, DIVE_MS);
    },
    [navigate, onAfterDive, lensEngaged, triggerLensSettle],
  );

  // Pan + scale the camera to a single channel tile (Cmd+K override target).
  // Same scale-derivation pattern as `diveToChannel` but capped at scale 1.0
  // so the user lands at the channel's "preview" zoom — readable but not
  // fully zoomed-in (which would overshoot into a single-tile-fills-screen
  // state that's hard to navigate away from).
  const flyToChannel = useCallback(
    (channelId: string): boolean => {
      const node = (nodes ?? []).find((n) => n.channel_id === channelId);
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!node || !rect) return false;
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
      setCamera(clampCamera({ x: targetX, y: targetY, scale: targetScale }));
      return true;
    },
    [nodes, lensEngaged, triggerLensSettle],
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

  // Pan + scale the camera so the Now Well fills the viewport with a small
  // padding margin. Uses the same scale-derivation trick as `diveToChannel`
  // but without the route change at the end.
  const flyToWell = useCallback(() => {
    const rect = viewportRef.current?.getBoundingClientRect();
    if (!rect) return;
    const wellWidth = WELL_R_MAX * 2.4;
    const wellHeight = WELL_R_MAX * WELL_Y_SQUASH * 2.4;
    const targetScale = Math.min(
      rect.width / wellWidth,
      rect.height / wellHeight,
    );
    const targetX = rect.width / 2 - WELL_X * targetScale;
    const targetY = rect.height / 2 - WELL_Y * targetScale;
    setCamera(clampCamera({ x: targetX, y: targetY, scale: targetScale }));
  }, []);

  // dnd-kit sensor with a modest activation distance so exploratory clicks
  // and tiny pointer drift pan/select space instead of immediately moving a
  // nearby tile.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
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

  const nowWellLens =
    lensEngaged && focalScreen
      ? projectFisheye(WELL_X, WELL_Y, camera, focalScreen, lensRadius)
      : null;

  const handleActivate = useCallback((nodeId: string) => {
    setActivatedTileId(nodeId);
  }, []);

  const worldStyle: CSSProperties = {
    transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`,
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
      <CanvasStarfield />
      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div className="absolute inset-0" style={worldStyle}>
          <OriginMarker />
          {densityIntensity !== "off" && (
            <UsageDensityLayer
              nodes={nodes ?? []}
              intensity={densityIntensity}
              window={densityWindow}
              compare={densityCompare}
              animate={densityAnimate}
            />
          )}
          {connectionsEnabled && (
            <ConnectionLineLayer
              nodes={nodes ?? []}
              hoveredNodeId={hoveredNodeId}
            />
          )}
          <MovementTraceLayer nodes={nodes ?? []} />
          <NowWell
            tickedNow={tickedNow}
            zoom={camera.scale}
            lens={nowWellLens}
          />
          {(upcomingItems ?? []).map((item) => {
            const orbit = upcomingOrbit(item, tickedNow);
            const lens =
              lensEngaged && focalScreen
                ? projectFisheye(orbit.x, orbit.y, camera, focalScreen, lensRadius)
                : null;
            return (
              <UpcomingTile
                key={upcomingReactKey(item)}
                item={item}
                zoom={camera.scale}
                tickedNow={tickedNow}
                extraScale={lens?.sizeFactor ?? 1}
                lens={lens}
              />
            );
          })}
          {(nodes ?? []).map((node) => {
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
      <LensHint engaged={lensEngaged} />
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
      <div className="absolute bottom-4 right-4 z-[2] flex flex-row items-center gap-2">
        <AddWidgetButton onClick={() => setLibraryOpen(true)} />
        <NowButton onClick={flyToWell} />
        <RecenterButton onClick={() => setCamera(DEFAULT_CAMERA)} />
      </div>
      <CanvasLibrarySheet
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        worldCenter={
          viewportSize.w && viewportSize.h
            ? {
                x: (viewportSize.w / 2 - camera.x) / camera.scale,
                y: (viewportSize.h / 2 - camera.y) / camera.scale,
              }
            : null
        }
      />
      {openBotChat && (
        <ChatSession
          source={{ kind: "channel", channelId: openBotChat.channelId }}
          shape="dock"
          open={true}
          onClose={() => setOpenBotChat(null)}
          title={`${openBotChat.botName} in #${openBotChat.channelName}`}
          initiallyExpanded
          dockCollapsedTitle={openBotChat.botName}
          dockCollapsedSubtitle={`#${openBotChat.channelName}`}
          dismissMode="close"
        />
      )}
    </div>
  );
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
      <span>Add</span>
    </button>
  );
}

function NowButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      onPointerDown={(e) => e.stopPropagation()}
      title="Fly to Now Well (scheduled work)"
      aria-label="Fly to Now Well"
      className="flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-surface-raised/85 backdrop-blur border border-surface-border text-text-dim hover:text-accent text-xs cursor-pointer"
    >
      <span className="text-sm leading-none">◎</span>
      <span>Now</span>
    </button>
  );
}

function MovementTraceLayer({ nodes }: { nodes: SpatialNode[] }) {
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
  const minX = Math.min(...xs) - 80;
  const minY = Math.min(...ys) - 80;
  const maxX = Math.max(...xs) + 80;
  const maxY = Math.max(...ys) + 80;
  return (
    <svg
      className="absolute pointer-events-none overflow-visible"
      style={{ left: minX, top: minY, width: maxX - minX, height: maxY - minY }}
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
  const labelScale = compact ? Math.min(5, Math.max(1, 1 / Math.max(zoom, 0.2))) : 1;
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
        style={{ width: outerSize, height: outerSize }}
      />
      <div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-surface-border/70 bg-surface flex items-center justify-center"
        style={{ width: innerSize, height: innerSize, fontSize: emojiSize }}
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
 * Bottom-left hint pill — surfaces the otherwise-invisible "hold Space to
 * focus" gesture. Switches to an active state while the user is holding so
 * they can confirm the lens is actually engaged. Static (doesn't auto-hide)
 * because there's no other surface advertising the gesture.
 */
function LensHint({ engaged }: { engaged: boolean }) {
  const base =
    "absolute bottom-4 left-4 z-[2] flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-md backdrop-blur border text-xs select-none pointer-events-none";
  const idle =
    "bg-surface-raised/85 border-surface-border text-text-dim";
  const active =
    "bg-accent/15 border-accent/60 text-accent";
  return (
    <div className={`${base} ${engaged ? active : idle}`} aria-live="polite">
      <kbd className="px-1.5 py-0 rounded border border-current/40 font-mono text-[10px] leading-tight">
        Space
      </kbd>
      <span>{engaged ? "focusing" : "hold to focus"}</span>
    </div>
  );
}

function RecenterButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      onPointerDown={(e) => e.stopPropagation()}
      title="Recenter (return to origin)"
      aria-label="Recenter canvas"
      className="flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-surface-raised/85 backdrop-blur border border-surface-border text-text-dim hover:text-text text-xs cursor-pointer"
    >
      <span className="text-sm leading-none">⌂</span>
      <span>Recenter</span>
    </button>
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
  onDoubleClick: () => void;
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
  onDoubleClick,
  children,
}: ManualBotNodeProps) {
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
      onDoubleClick={(e) => {
        e.stopPropagation();
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
  children,
}: DraggableNodeProps) {
  const { setNodeRef, setActivatorNodeRef, listeners, attributes, transform } = useDraggable({
    id: node.id,
    disabled: diving,
  });
  // dnd-kit returns a screen-pixel translate during drag. The tile lives
  // inside a parent that's scaled by `camera.scale`, so dividing by scale
  // makes the tile's screen movement match the cursor 1:1.
  const dragTranslate = transform
    ? `translate(${transform.x / scale}px, ${transform.y / scale}px)`
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
  if (isDragging) {
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
    zIndex: isDragging ? 10 : node.z_index,
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
      <div
        ref={setActivatorNodeRef}
        style={{ display: "contents", pointerEvents: "auto" }}
        {...attributes}
        {...listeners}
      >
        {children}
      </div>
    </div>
  );
}
