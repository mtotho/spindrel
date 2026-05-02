/**
 * DashboardDnd — DnD primitives for the channel dashboard edit surface.
 *
 * The current channel workbench uses one freeform board. This module still
 * owns the shared drag bindings and resize handles used by pinned widgets.
 * Historical helpers below are kept for non-channel dashboard compatibility,
 * but they should not reintroduce panel-zone placement on the workbench.
 *
 * Tiles come in two flavors:
 *
 *   - `SortableTile` — 1-D list canvases in legacy dashboard views.
 *
 *   - `GridTile` — 2-D free-positioning canvas (grid). Uses `useDraggable` +
 *     a drop-time snap calc against the canvas's bounding rect. Resize
 *     handles on the south / east / south-east edges write w/h directly.
 *
 * All layout persistence goes through the same `applyLayout([{id, zone,
 * x, y, w, h}])` path.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import {
  useDraggable,
  useDroppable,
  type DraggableAttributes,
} from "@dnd-kit/core";
import type { SyntheticListenerMap } from "@dnd-kit/core/dist/hooks/utilities";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { ChatZone, GridLayoutItem } from "@/src/types/api";
import { useThemeTokens } from "@/src/theme/tokens";

/** What each tile passes down to `PinnedToolWidget` so the grip icon is the
 *  drag handle regardless of which DnD wrapper surrounds it. */
export interface ExternalDragBinding {
  setNodeRef: (el: HTMLElement | null) => void;
  listeners: SyntheticListenerMap | undefined;
  attributes: DraggableAttributes;
  style: CSSProperties;
  isDragging: boolean;
}

// ---------------------------------------------------------------------------
// Snap math — pure, unit-tested.
// ---------------------------------------------------------------------------

export interface GridSnapConfig {
  cols: number;
  rowHeight: number;
  /** Pixel gap between cells (vertical + horizontal). */
  gap: number;
  /** Total pixel width of the canvas's grid area. */
  canvasWidth: number;
  /** Pixel padding between the `canvasWidth` reference rect and the actual
   *  grid cells. Needed when the measured rect includes wrapper padding
   *  (e.g. the grid canvas uses `p-3 = 12px`); without it, pointer math is
   *  biased by one cell near the canvas edges. Defaults to 0 for callers
   *  that pass already-inner rect widths. */
  paddingLeft?: number;
  paddingTop?: number;
}

/** Snap a pointer position (relative to the canvas top-left) to `{x, y}`
 *  grid coordinates. Returns non-negative integer cell indices. */
export function pointerToCell(
  relX: number,
  relY: number,
  cfg: GridSnapConfig,
): { x: number; y: number } {
  const padX = cfg.paddingLeft ?? 0;
  const padY = cfg.paddingTop ?? 0;
  const innerW = Math.max(1, cfg.canvasWidth - padX * 2);
  const cellW = (innerW + cfg.gap) / cfg.cols;
  const cellH = cfg.rowHeight + cfg.gap;
  const x = Math.max(0, Math.min(cfg.cols - 1, Math.floor((relX - padX) / cellW)));
  const y = Math.max(0, Math.floor((relY - padY) / cellH));
  return { x, y };
}

/** Clamp a proposed tile placement so it fits within the column count. */
export function clampPlacement(
  x: number,
  y: number,
  w: number,
  h: number,
  cols: number,
): { x: number; y: number; w: number; h: number } {
  const cw = Math.max(1, Math.min(cols, w));
  const cx = Math.max(0, Math.min(cols - cw, x));
  return { x: cx, y: Math.max(0, y), w: cw, h: Math.max(1, h) };
}

// ---------------------------------------------------------------------------
// Droppable canvas
// ---------------------------------------------------------------------------

interface DroppableCanvasProps {
  zone: ChatZone;
  /** Wrapper className for width/order responsive rules. */
  extraClass?: string;
  /** Style forwarded to the wrapper (widths, flex sizing). */
  extraStyle?: CSSProperties;
  /** Whether edit mode outline is shown. */
  editMode: boolean;
  /** True when any tile is being dragged anywhere in the DndContext. */
  anyDragging: boolean;
  /** True when this canvas is the current drop target. */
  isOver: boolean;
  children: ReactNode;
  /** Exposed so the parent can resolve pointer → grid coords at drag end. */
  measureRef?: (el: HTMLDivElement | null) => void;
  /** Rounded radius to match the enclosing card's radius (used on the ring). */
  ringRadius?: string;
}

export function DroppableCanvas({
  zone,
  extraClass = "",
  extraStyle,
  editMode,
  anyDragging,
  isOver,
  children,
  measureRef,
  ringRadius = "8px",
}: DroppableCanvasProps) {
  const t = useThemeTokens();
  const { setNodeRef } = useDroppable({ id: `canvas:${zone}`, data: { zone } });

  const combinedRef = useCallback(
    (el: HTMLDivElement | null) => {
      setNodeRef(el);
      measureRef?.(el);
    },
    [setNodeRef, measureRef],
  );

  if (!editMode) {
    return (
      <div className={extraClass} style={extraStyle}>
        {children}
      </div>
    );
  }

  // Edit-mode chrome is just a dashed overlay ring — no card background, no
  // label, no solid border. Ring lights up on `isOver` and warms up slightly
  // when any drag is in flight so the user can see valid targets without the
  // canvas masquerading as a piece of UI.
  const ringColor = isOver
    ? t.accent
    : anyDragging
      ? `${t.textDim}66`
      : `${t.textDim}22`;

  return (
    <div
      ref={combinedRef}
      data-dashboard-canvas={zone}
      className={`relative ${extraClass}`}
      style={extraStyle}
    >
      {children}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          borderRadius: ringRadius,
          border: `1px dashed ${ringColor}`,
          transition: "border-color 120ms",
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// SortableTile — for legacy 1-D dashboard lists.
// ---------------------------------------------------------------------------

interface SortableTileProps {
  id: string;
  disabled?: boolean;
  children: (binding: ExternalDragBinding) => ReactNode;
}

export function SortableTile({ id, disabled = false, children }: SortableTileProps) {
  const {
    setNodeRef,
    attributes,
    listeners,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled });
  // Source tile: hide (DragOverlay is painting the floating copy). Siblings
  // continue to receive their sortable translate for the push-aside animation.
  const style: CSSProperties = disabled
    ? {}
    : isDragging
    ? { opacity: 0, transition: "none" }
    : {
        transform: CSS.Transform.toString(transform),
        transition,
      };
  return <>{children({
    setNodeRef,
    attributes,
    listeners: disabled ? undefined : listeners,
    style,
    isDragging: disabled ? false : isDragging,
  })}</>;
}

// ---------------------------------------------------------------------------
// GridTile — for the multi-column grid canvas (free x/y placement).
// ---------------------------------------------------------------------------

interface GridTileProps {
  id: string;
  disabled?: boolean;
  /** Absolute CSS grid placement from the tile's persisted {x,y,w,h}. */
  gridColumn: string;
  gridRow: string;
  children: (binding: ExternalDragBinding) => ReactNode;
}

export function GridTile({ id, disabled = false, gridColumn, gridRow, children }: GridTileProps) {
  const { setNodeRef, attributes, listeners, isDragging } = useDraggable({ id, disabled });
  // Hide source tile while dragging — the DragOverlay is the visible copy.
  // No CSS transform on the source; it stays parked in its grid cell until
  // the drop commits to new {x,y} and CSS Grid re-lays it out.
  const style: CSSProperties = {
    gridColumn,
    gridRow,
    opacity: disabled ? 1 : (isDragging ? 0 : 1),
    transition: disabled || !isDragging ? "opacity 120ms" : "none",
  };
  return <>{children({
    setNodeRef,
    attributes,
    listeners: disabled ? undefined : listeners,
    style,
    isDragging: disabled ? false : isDragging,
  })}</>;
}

// ---------------------------------------------------------------------------
// Resize handles — pointer-event-based, bypass DnD entirely.
// ---------------------------------------------------------------------------

export type ResizeEdge = "s" | "e" | "se" | "w" | "sw";

export interface TileBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface ResizeHandleProps {
  edges: ResizeEdge[];
  /** Initial persisted {x,y,w,h} for this tile — needed so west-edge
   *  resizes can anchor the right boundary and emit an updated x. */
  initial: TileBox;
  /** Cell width + row height in pixels; used to convert pointer delta to
   *  cell delta. */
  cellPx: { w: number; h: number };
  /** Parent transform scale. Pointer deltas arrive in viewport pixels, so
   *  zoomed canvases divide through this before converting to grid cells. */
  scale?: number;
  /** Min/max column span (rail/dock clamp to 1). */
  clampW: { min: number; max: number };
  /** Min row height (header clamps to 1). */
  clampH: { min: number; max?: number };
  /** When true, handles sit at partial opacity instead of being invisible
   *  until hover. Edit mode flips this on so the affordances are discoverable
   *  without probing every tile. */
  showRest?: boolean;
  /** Live callback during drag so the preview frame tracks the pointer. */
  onResizing?: (box: TileBox) => void;
  /** Called once on pointerup with the final box. */
  onCommit: (box: TileBox) => void;
}

export function ResizeHandles({
  edges,
  initial,
  cellPx,
  scale = 1,
  clampW,
  clampH,
  showRest = false,
  onResizing,
  onCommit,
}: ResizeHandleProps) {
  const t = useThemeTokens();
  const startRef = useRef<{
    pointerX: number;
    pointerY: number;
    tx: number;
    ty: number;
    w: number;
    h: number;
    edge: ResizeEdge;
  } | null>(null);
  const currentRef = useRef<TileBox>(initial);
  // Only sync to the `initial` prop when NOT actively dragging. Parent state
  // updates during resize (live-preview) would otherwise stomp the in-flight
  // box back to the persisted value, and on pointerup we'd commit the
  // original size → "pops back" bug.
  if (!startRef.current) {
    currentRef.current = initial;
  }

  const beginResize = useCallback(
    (edge: ResizeEdge) => (e: ReactPointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
      startRef.current = {
        pointerX: e.clientX,
        pointerY: e.clientY,
        tx: initial.x,
        ty: initial.y,
        w: initial.w,
        h: initial.h,
        edge,
      };
      currentRef.current = { ...initial };
    },
    [initial.x, initial.y, initial.w, initial.h],
  );

  const onMove = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      const s = startRef.current;
      if (!s) return;
      const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1;
      const dxCells = Math.round(((e.clientX - s.pointerX) / safeScale) / cellPx.w);
      const dyCells = Math.round(((e.clientY - s.pointerY) / safeScale) / cellPx.h);
      let nextX = s.tx;
      const nextY = s.ty;
      let nextW = s.w;
      let nextH = s.h;
      const rightBoundary = s.tx + s.w;

      if (s.edge === "e" || s.edge === "se") {
        nextW = Math.max(
          clampW.min,
          Math.min(clampW.max, s.w + dxCells),
        );
      }
      if (s.edge === "w" || s.edge === "sw") {
        // Anchor the right edge; x moves with the pointer and w inverts.
        // nextX is bounded so:
        //   - nextX ≥ 0 (can't go past canvas left)
        //   - nextW = right - nextX stays within [clampW.min, clampW.max]
        const minX = Math.max(0, rightBoundary - clampW.max);
        const maxX = rightBoundary - clampW.min;
        nextX = Math.max(minX, Math.min(maxX, s.tx + dxCells));
        nextW = rightBoundary - nextX;
      }
      if (s.edge === "s" || s.edge === "se" || s.edge === "sw") {
        const candidateH = s.h + dyCells;
        nextH = Math.max(
          clampH.min,
          clampH.max == null ? candidateH : Math.min(clampH.max, candidateH),
        );
      }
      const nextBox = { x: nextX, y: nextY, w: nextW, h: nextH };
      currentRef.current = nextBox;
      onResizing?.(nextBox);
    },
    [cellPx.w, cellPx.h, scale, clampW.min, clampW.max, clampH.min, clampH.max, onResizing],
  );

  const endResize = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!startRef.current) return;
      (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
      const final = currentRef.current;
      startRef.current = null;
      onCommit(final);
    },
    [onCommit],
  );

  // In edit mode the affordance should be discoverable at rest; we land at
  // ~65% opacity and bump to full on hover. Outside edit mode, stays hover-
  // only so view-mode tiles read as calm content.
  const restOpacity = showRest ? "opacity-60" : "opacity-0";
  const base = `absolute z-20 select-none ${restOpacity} hover:opacity-100 transition-opacity duration-150 pointer-events-auto`;
  // Neutral gray — keeps the corner/edge handle from competing with the
  // drop-target accent outline.
  const tint = `${t.textDim}55`;
  const cornerTint = `${t.textDim}88`;

  return (
    <>
      {edges.includes("s") && (
        <div
          role="separator"
          aria-label="Resize vertically"
          className={`${base} left-3 right-3 bottom-0 h-2 cursor-ns-resize`}
          style={{ background: `linear-gradient(to top, ${tint}, transparent)` }}
          onPointerDown={beginResize("s")}
          onPointerMove={onMove}
          onPointerUp={endResize}
          onPointerCancel={endResize}
        />
      )}
      {edges.includes("e") && (
        <div
          role="separator"
          aria-label="Resize horizontally"
          className={`${base} top-3 bottom-3 right-0 w-2 cursor-ew-resize`}
          style={{ background: `linear-gradient(to left, ${tint}, transparent)` }}
          onPointerDown={beginResize("e")}
          onPointerMove={onMove}
          onPointerUp={endResize}
          onPointerCancel={endResize}
        />
      )}
      {edges.includes("w") && (
        <div
          role="separator"
          aria-label="Resize horizontally"
          className={`${base} top-3 bottom-3 left-0 w-2 cursor-ew-resize`}
          style={{ background: `linear-gradient(to right, ${tint}, transparent)` }}
          onPointerDown={beginResize("w")}
          onPointerMove={onMove}
          onPointerUp={endResize}
          onPointerCancel={endResize}
        />
      )}
      {edges.includes("se") && (
        <div
          role="separator"
          aria-label="Resize"
          className={`${base} bottom-0 right-0 w-3 h-3 cursor-nwse-resize rounded-tl`}
          style={{ background: cornerTint }}
          onPointerDown={beginResize("se")}
          onPointerMove={onMove}
          onPointerUp={endResize}
          onPointerCancel={endResize}
        />
      )}
      {edges.includes("sw") && (
        <div
          role="separator"
          aria-label="Resize"
          className={`${base} bottom-0 left-0 w-3 h-3 cursor-nesw-resize rounded-tr`}
          style={{ background: cornerTint }}
          onPointerDown={beginResize("sw")}
          onPointerMove={onMove}
          onPointerUp={endResize}
          onPointerCancel={endResize}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Small hook: track whether any tile is currently being dragged in the
// enclosing DndContext. Useful for EditModeGridGuides's "show column ticks
// while dragging".
// ---------------------------------------------------------------------------

export function useCanvasMeasure() {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const nodeRef = useRef<HTMLDivElement | null>(null);

  const setRef = useCallback((el: HTMLDivElement | null) => {
    nodeRef.current = el;
    if (el) setRect(el.getBoundingClientRect());
    else setRect(null);
  }, []);

  useEffect(() => {
    if (!nodeRef.current) return;
    const el = nodeRef.current;
    const obs = new ResizeObserver(() => setRect(el.getBoundingClientRect()));
    obs.observe(el);
    const onScroll = () => setRect(el.getBoundingClientRect());
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      obs.disconnect();
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  return { rect, setRef };
}

/** Derive sequential y coordinates for rail/dock tiles (1-col, compact-none). */
export function sequentialYLayout(
  ids: string[],
  defaultH: number,
  byId: Map<string, GridLayoutItem>,
): Map<string, { x: number; y: number; w: number; h: number }> {
  const out = new Map<string, { x: number; y: number; w: number; h: number }>();
  let y = 0;
  for (const id of ids) {
    const prev = byId.get(id);
    const h = prev?.h && prev.h > 0 ? prev.h : defaultH;
    out.set(id, { x: 0, y, w: 1, h });
    y += h;
  }
  return out;
}

/** Derive sequential x coordinates for header tiles (1-row, compact-left). */
export function sequentialXLayout(
  ids: string[],
  byId: Map<string, GridLayoutItem>,
): Map<string, { x: number; y: number; w: number; h: number }> {
  const out = new Map<string, { x: number; y: number; w: number; h: number }>();
  let x = 0;
  for (const id of ids) {
    const prev = byId.get(id);
    const w = prev?.w && prev.w > 0 ? prev.w : 1;
    out.set(id, { x, y: 0, w, h: 1 });
    x += w;
  }
  return out;
}
