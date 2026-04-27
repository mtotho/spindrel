import {
  useCallback,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import { useQueryClient } from "@tanstack/react-query";

import {
  NODES_KEY,
  useLandmarkNode,
  useUpdateSpatialNode,
  type LandmarkKind,
  type SpatialNode,
} from "../../api/hooks/useWorkspaceSpatial";
import { canMoveSpatialNode, type SpatialInteractionMode } from "./spatialInteraction";

interface LandmarkWrapperProps {
  kind: LandmarkKind;
  scale: number;
  interactionMode: SpatialInteractionMode;
  /** Default world coords used while the canvas list query is loading
   *  (matches the server-side seed defaults in `LANDMARK_DEFAULTS`). */
  fallbackX: number;
  fallbackY: number;
  /** World-space dimensions of the landmark's visual extent. Renders as a
   *  transparent hit overlay centered on the anchor so empty regions of
   *  large landmarks (e.g. Memory Observatory's pointer-events-none SVG)
   *  still receive drag activation. Without this the wrapper has no hit
   *  area beyond its descendants' painted pixels and large landmarks are
   *  ungrabable. Defaults to 0 (no overlay). */
  hitWidth?: number;
  hitHeight?: number;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}

/** Wraps a fixed canvas landmark so it persists its world position via the
 *  shared `workspace_spatial_nodes` plumbing. Children render anchored at
 *  (0,0) of the wrapper — they own their own visual offset (e.g.
 *  `left: -size/2, top: -size/2` to center on the anchor).
 *
 *  Drag activation matches `DraggableNode`: only when Arrange mode is on
 *  OR the user is holding Shift. Pan-canvas drag in Browse mode is the
 *  default — Shift+drag escalates to "move this landmark." */
export function LandmarkWrapper({
  kind,
  scale,
  interactionMode,
  fallbackX,
  fallbackY,
  hitWidth,
  hitHeight,
  className,
  style,
  children,
}: LandmarkWrapperProps) {
  const node = useLandmarkNode(kind);
  const updateNode = useUpdateSpatialNode();
  const qc = useQueryClient();
  const x = node?.world_x ?? fallbackX;
  const y = node?.world_y ?? fallbackY;

  const [drag, setDrag] = useState<{
    pointerId: number;
    startX: number;
    startY: number;
    dx: number;
    dy: number;
  } | null>(null);

  const onPointerDownCapture = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.button !== 0) return;
      if (!node) return;
      if (!canMoveSpatialNode(interactionMode, e.shiftKey)) {
        // Not entering drag — let the event continue to the inner element so
        // its click handler still fires. Inner elements call their own
        // stopPropagation to prevent canvas pan in browse mode.
        return;
      }
      // Capture phase: this fires BEFORE descendants' pointerdown handlers.
      // Required because the inner clickable element calls stopPropagation in
      // its own onPointerDown — without capture, the wrapper would never see
      // a Shift+drag intent.
      e.preventDefault();
      e.stopPropagation();
      setDrag({
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        dx: 0,
        dy: 0,
      });
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [interactionMode, node],
  );

  const onPointerMove = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!drag || drag.pointerId !== e.pointerId) return;
      e.preventDefault();
      e.stopPropagation();
      setDrag((d) =>
        d && d.pointerId === e.pointerId
          ? { ...d, dx: e.clientX - d.startX, dy: e.clientY - d.startY }
          : d,
      );
    },
    [drag],
  );

  const finish = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!drag || drag.pointerId !== e.pointerId || !node) return;
      e.preventDefault();
      e.stopPropagation();
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* already released */
      }
      const { dx, dy } = drag;
      if (dx === 0 && dy === 0) {
        setDrag(null);
        return;
      }
      const newX = node.world_x + dx / scale;
      const newY = node.world_y + dy / scale;
      // Write the new coords into the React Query cache SYNCHRONOUSLY before
      // clearing drag state. Without this, the wrapper re-renders with
      // `drag=null` and the still-old `node.world_x/y` for one frame —
      // visible as a snap back to the original position — because
      // `useUpdateSpatialNode.onMutate` defers its optimistic update behind
      // an `await cancelQueries(...)`.
      qc.setQueryData<SpatialNode[]>(NODES_KEY, (old) =>
        (old ?? []).map((n) =>
          n.id === node.id ? { ...n, world_x: newX, world_y: newY } : n,
        ),
      );
      setDrag(null);
      updateNode.mutate({
        nodeId: node.id,
        body: { world_x: newX, world_y: newY },
      });
    },
    [drag, node, scale, qc, updateNode],
  );

  const draggingTransform = drag
    ? `translate(${drag.dx / scale}px, ${drag.dy / scale}px)`
    : undefined;

  const composedStyle: CSSProperties = {
    position: "absolute",
    left: x,
    top: y,
    transform: draggingTransform,
    ...style,
  };

  // Suppress click after a real drag so e.g. dragging the Attention Hub
  // doesn't also open the Attention drawer at the drop location.
  const onClickCapture = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (drag) {
        e.stopPropagation();
        e.preventDefault();
      }
    },
    [drag],
  );

  return (
    <div
      data-tile-kind="landmark"
      className={className}
      style={composedStyle}
      onPointerDownCapture={onPointerDownCapture}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      onClickCapture={onClickCapture}
    >
      {hitWidth && hitHeight ? (
        <div
          aria-hidden
          style={{
            position: "absolute",
            left: -hitWidth / 2,
            top: -hitHeight / 2,
            width: hitWidth,
            height: hitHeight,
            // Behind children by DOM order — interactive descendants stay
            // clickable; this overlay only catches empty-area pointerdowns
            // so the wrapper's capture handler can decide "drag or pan".
            pointerEvents: "auto",
          }}
        />
      ) : null}
      {children}
    </div>
  );
}
