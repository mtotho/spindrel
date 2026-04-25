import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useChannels } from "../../api/hooks/useChannels";
import { useDashboards, channelIdFromSlug } from "../../stores/dashboards";
import {
  useSpatialNodes,
  useUpdateSpatialNode,
  type SpatialNode,
} from "../../api/hooks/useWorkspaceSpatial";
import { useUpcomingActivity } from "../../api/hooks/useUpcomingActivity";
import type { Channel } from "../../types/api";
import { ChannelTile } from "./ChannelTile";
import { WidgetTile } from "./WidgetTile";
import {
  NowWell,
  WELL_X,
  WELL_Y,
  WELL_R_MAX,
  WELL_Y_SQUASH,
} from "./NowWell";
import { UpcomingTile } from "./UpcomingTile";

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

interface Camera {
  x: number;
  y: number;
  scale: number;
}

const DEFAULT_CAMERA: Camera = { x: 0, y: 0, scale: 1 };
const MIN_SCALE = 0.05;
const MAX_SCALE = 3.0;
const DIVE_MS = 300;
const TILE_W = 220;
const TILE_H = 140;
const CAMERA_STORAGE_KEY = "spatial.camera";

// Fisheye lens (P16). Hold Space → tiles outside `lensRadius` are pulled
// toward the cursor focal point and visually shrunk.
//
// `lensRadius` = native zone (screen px). Tiles inside it are untouched.
// `LENS_R_MAX_MULT` caps how far a projected tile can land — distant tiles
// asymptote to `lensRadius * LENS_R_MAX_MULT` regardless of how far away
// they actually are. Drives the visual "everything compresses into a ring"
// look that makes the effect obvious.
// `LENS_SIZE_EXP` amplifies the size shrink (sizeFactor = ratio ** exp).
// >1 makes shrinking visibly stronger than the position pull, which reads
// as proper depth-of-field instead of a subtle wobble.
const LENS_NATIVE_FRACTION = 0.22;
const LENS_R_MAX_MULT = 1.8;
const LENS_SIZE_EXP = 1.5;
const LENS_SETTLE_MS = 250;
const LENS_MIN_SCALE = 0.2;

interface LensTransform {
  dxWorld: number;
  dyWorld: number;
  sizeFactor: number;
}

/**
 * Project a tile's world-coord center through the fisheye lens. Returns
 * additive world-coord translate + a size scale factor; identity when the
 * tile sits inside the native zone.
 *
 * Math runs in screen space (post pan/zoom) so distances are pixel-perceptual.
 * The projection saturates: distant tiles asymptote to `R_max = lensRadius *
 * LENS_R_MAX_MULT`, so no matter how far away a tile lives, it lands somewhere
 * in the ring `[lensRadius, R_max]`. Saturation curve:
 *   r' = lensRadius + (R_max - lensRadius) * (1 - exp(-d / (R_max - lensRadius)))
 * where d = r - lensRadius. This is much more visible than a log curve at
 * typical distances — at r = 2*lensRadius, log gives ratio=1.0 (no shrink),
 * the saturation curve gives ratio ~0.85 with a pronounced size shrink via
 * `sizeFactor = ratio ^ LENS_SIZE_EXP`.
 *
 * Convert back to world coords by dividing by `camera.scale` so the parent
 * world transform's scale composes correctly.
 */
function projectFisheye(
  worldCx: number,
  worldCy: number,
  camera: Camera,
  focalScreen: { x: number; y: number },
  lensRadius: number,
): LensTransform {
  if (lensRadius <= 0) return { dxWorld: 0, dyWorld: 0, sizeFactor: 1 };
  const screenCx = camera.x + worldCx * camera.scale;
  const screenCy = camera.y + worldCy * camera.scale;
  const dxs = screenCx - focalScreen.x;
  const dys = screenCy - focalScreen.y;
  const r = Math.hypot(dxs, dys);
  if (r <= lensRadius) return { dxWorld: 0, dyWorld: 0, sizeFactor: 1 };
  const d = r - lensRadius;
  const Rmax = lensRadius * LENS_R_MAX_MULT;
  const span = Rmax - lensRadius;
  const rPrime = lensRadius + span * (1 - Math.exp(-d / span));
  const ratio = rPrime / r;
  const screenDx = (focalScreen.x - screenCx) * (1 - ratio);
  const screenDy = (focalScreen.y - screenCy) * (1 - ratio);
  const sizeFactor = Math.max(
    LENS_MIN_SCALE,
    Math.min(1, Math.pow(ratio, LENS_SIZE_EXP)),
  );
  return {
    dxWorld: screenDx / camera.scale,
    dyWorld: screenDy / camera.scale,
    sizeFactor,
  };
}

/**
 * Read the persisted camera position. Returns DEFAULT_CAMERA on any failure
 * (missing key, malformed JSON, missing fields, NaN/Infinity scale, etc.) so
 * a corrupted localStorage entry can never strand the user off-canvas.
 */
function loadStoredCamera(): Camera {
  try {
    const raw = localStorage.getItem(CAMERA_STORAGE_KEY);
    if (!raw) return DEFAULT_CAMERA;
    const parsed = JSON.parse(raw);
    if (
      parsed
      && typeof parsed.x === "number" && Number.isFinite(parsed.x)
      && typeof parsed.y === "number" && Number.isFinite(parsed.y)
      && typeof parsed.scale === "number" && Number.isFinite(parsed.scale)
      && parsed.scale >= MIN_SCALE && parsed.scale <= MAX_SCALE
    ) {
      return { x: parsed.x, y: parsed.y, scale: parsed.scale };
    }
  } catch {
    /* fall through */
  }
  return DEFAULT_CAMERA;
}

interface SpatialCanvasProps {
  /** Called after the dive animation completes and `router.push` has fired.
   *  Used by the overlay to close itself a tick after the route paints. */
  onAfterDive?: () => void;
}

export function SpatialCanvas({ onAfterDive }: SpatialCanvasProps) {
  const navigate = useNavigate();
  const { data: nodes } = useSpatialNodes();
  const { data: channels } = useChannels();
  const { data: upcomingItems } = useUpcomingActivity(50);
  const updateNode = useUpdateSpatialNode();

  // Live tick for the Now Well + orbital tile positions. Server data is
  // 60s-fresh (`useUpcomingActivity` refetchInterval), but tile radii decay
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
  // One activated widget tile at a time. Activation makes a widget tile
  // hand pointer events to its iframe; Esc / click on the canvas background
  // / dragging the tile / activating another tile deactivates.
  const [activatedTileId, setActivatedTileId] = useState<string | null>(null);
  // Viewport size in screen pixels — used together with `camera` to compute
  // each tile's `inViewport` flag for iframe culling. ResizeObserver keeps it
  // current across overlay open/close, sidebar toggles, and window resizes.
  const [viewportSize, setViewportSize] = useState<{ w: number; h: number }>({
    w: 0,
    h: 0,
  });

  const viewportRef = useRef<HTMLDivElement>(null);

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
    setCamera((c) => ({
      ...c,
      x: p.cameraX + (e.clientX - p.startX),
      y: p.cameraY + (e.clientY - p.startY),
    }));
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
        return {
          scale: newScale,
          x: cx - (cx - c.x) * k,
          y: cy - (cy - c.y) * k,
        };
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
        setCamera({ x: targetX, y: targetY, scale: targetScale });
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
    setCamera({ x: targetX, y: targetY, scale: targetScale });
  }, []);

  // dnd-kit sensor with a small activation distance so a click-drag of the
  // tile starts dnd, but a clean click (or double-click for dive) doesn't.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
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
      }}
    >
      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div className="absolute inset-0" style={worldStyle}>
          <OriginMarker />
          <NowWell tickedNow={tickedNow} zoom={camera.scale} />
          {(upcomingItems ?? []).map((item) => {
            const key =
              item.type === "task" && item.task_id
                ? `task:${item.task_id}`
                : item.type === "heartbeat"
                ? `hb:${item.channel_id ?? item.bot_id}:${item.scheduled_at}`
                : `mh:${item.bot_id}:${item.scheduled_at}`;
            return (
              <UpcomingTile
                key={key}
                item={item}
                zoom={camera.scale}
                tickedNow={tickedNow}
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
      <div className="absolute bottom-4 right-4 z-[2] flex flex-row items-center gap-2">
        <NowButton onClick={flyToWell} />
        <RecenterButton onClick={() => setCamera(DEFAULT_CAMERA)} />
      </div>
    </div>
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
  children: React.ReactNode;
}

function DraggableNode({
  node,
  scale,
  isDragging,
  diving,
  lens,
  lensSettling,
  children,
}: DraggableNodeProps) {
  const { setNodeRef, listeners, attributes, transform } = useDraggable({
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
  };
  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      {children}
    </div>
  );
}

