import {
  useCallback,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import {
  useLandmarkNode,
  useUpdateSpatialNode,
  type LandmarkKind,
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
  className,
  style,
  children,
}: LandmarkWrapperProps) {
  const node = useLandmarkNode(kind);
  const updateNode = useUpdateSpatialNode();
  const x = node?.world_x ?? fallbackX;
  const y = node?.world_y ?? fallbackY;

  const [drag, setDrag] = useState<{
    pointerId: number;
    startX: number;
    startY: number;
    dx: number;
    dy: number;
  } | null>(null);

  const onPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.button !== 0) return;
      // Always stop the event from reaching the canvas pan handler — the
      // landmark owns its hit area whether or not the user is dragging.
      e.stopPropagation();
      if (!node) return;
      if (!canMoveSpatialNode(interactionMode, e.shiftKey)) return;
      e.preventDefault();
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
      setDrag(null);
      if (dx === 0 && dy === 0) return;
      updateNode.mutate({
        nodeId: node.id,
        body: {
          world_x: node.world_x + dx / scale,
          world_y: node.world_y + dy / scale,
        },
      });
    },
    [drag, node, scale, updateNode],
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

  return (
    <div
      className={className}
      style={composedStyle}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
    >
      {children}
    </div>
  );
}
