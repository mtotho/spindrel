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
import {
  useSpatialNodes,
  useUpdateSpatialNode,
  type SpatialNode,
} from "../../api/hooks/useWorkspaceSpatial";
import type { Channel } from "../../types/api";
import { ChannelTile } from "./ChannelTile";

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
const MIN_SCALE = 0.2;
const MAX_SCALE = 3.0;
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
  const { data: nodes } = useSpatialNodes();
  const { data: channels } = useChannels();
  const updateNode = useUpdateSpatialNode();

  const channelsById = useMemo(() => {
    const m = new Map<string, Channel>();
    for (const c of channels ?? []) m.set(c.id, c);
    return m;
  }, [channels]);

  const [camera, setCamera] = useState<Camera>(DEFAULT_CAMERA);
  const cameraRef = useRef(camera);
  cameraRef.current = camera;
  const [diving, setDiving] = useState(false);
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);

  const viewportRef = useRef<HTMLDivElement>(null);
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
      panState.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        cameraX: camera.x,
        cameraY: camera.y,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [camera.x, camera.y, diving],
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
    [navigate, onAfterDive],
  );

  // dnd-kit sensor with a small activation distance so a click-drag of the
  // tile starts dnd, but a clean click (or double-click for dive) doesn't.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  const handleDragStart = useCallback((e: DragStartEvent) => {
    setDraggingNodeId(String(e.active.id));
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
          {(nodes ?? []).map((node) => {
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
                >
                  <ChannelTile
                    channel={channel}
                    zoom={camera.scale}
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
            // Widget node — placeholder until P3 lands the live iframe.
            return (
              <DraggableNode
                key={node.id}
                node={node}
                scale={camera.scale}
                isDragging={draggingNodeId === node.id}
                diving={diving}
              >
                <WidgetTilePlaceholder />
              </DraggableNode>
            );
          })}
        </div>
      </DndContext>
      <RecenterButton onClick={() => setCamera(DEFAULT_CAMERA)} />
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

function RecenterButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      onPointerDown={(e) => e.stopPropagation()}
      title="Recenter (return to origin)"
      aria-label="Recenter canvas"
      className="absolute bottom-4 right-4 z-[2] flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-surface-raised/85 backdrop-blur border border-surface-border text-text-dim hover:text-text text-xs cursor-pointer"
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
  children: React.ReactNode;
}

function DraggableNode({ node, scale, isDragging, diving, children }: DraggableNodeProps) {
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
  const style: CSSProperties = {
    position: "absolute",
    left: node.world_x,
    top: node.world_y,
    width: node.world_w,
    height: node.world_h,
    zIndex: isDragging ? 10 : node.z_index,
    transform: dragTranslate || undefined,
    transition: isDragging ? "none" : "transform 120ms",
    touchAction: "none",
  };
  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      {children}
    </div>
  );
}

function WidgetTilePlaceholder() {
  return (
    <div
      data-tile-kind="widget"
      className="w-full h-full rounded-xl border border-dashed border-surface-border bg-surface-raised/60 text-text-dim flex flex-col items-center justify-center text-[11px]"
    >
      Widget (placeholder)
    </div>
  );
}
