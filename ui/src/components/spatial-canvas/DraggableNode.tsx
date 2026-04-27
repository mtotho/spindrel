import {
  useCallback,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { useDraggable } from "@dnd-kit/core";
import {
  useUpdateSpatialNode,
  type SpatialNode,
} from "../../api/hooks/useWorkspaceSpatial";
import { DragActivatorContext, type DragActivatorBundle } from "./dragActivatorContext";
import {
  LENS_SETTLE_MS,
  type LensTransform,
} from "./spatialGeometry";

interface DraggableNodeProps {
  node: SpatialNode;
  scale: number;
  isDragging: boolean;
  diving: boolean;
  lens: LensTransform | null;
  lensSettling: boolean;
  onHoverChange?: (hovered: boolean) => void;
  activatorMode?: "full" | "scoped";
  onScopedDragStart?: () => void;
  onScopedDragEnd?: () => void;
  onDoubleClick?: () => void;
  dragEnabled: boolean;
  children: ReactNode;
}

export function DraggableNode({
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
  onDoubleClick,
  dragEnabled,
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
    disabled: diving || !dragEnabled || activatorMode === "scoped",
  });
  const handleScopedPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      if (activatorMode !== "scoped" || diving || !dragEnabled || e.button !== 0) return;
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
    [activatorMode, diving, dragEnabled, onScopedDragStart],
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
    listeners: (activatorMode === "scoped"
      ? {
          onPointerDown: handleScopedPointerDown,
          onPointerMove: handleScopedPointerMove,
          onPointerUp: finishScopedDrag,
          onPointerCancel: finishScopedDrag,
        }
      : dragEnabled ? listeners : undefined) as unknown as DragActivatorBundle["listeners"],
    attributes: (activatorMode === "scoped"
      ? { role: "button", tabIndex: 0 }
      : attributes) as unknown as DragActivatorBundle["attributes"],
  };
  const handleDoubleClickCapture = useCallback(
    (e: ReactMouseEvent<HTMLDivElement>) => {
      if (!onDoubleClick || diving) return;
      e.preventDefault();
      e.stopPropagation();
      onDoubleClick();
    },
    [diving, onDoubleClick],
  );
  const dragTranslate = transform
    ? `translate(${transform.x / scale}px, ${transform.y / scale}px)`
    : scopedDrag
    ? `translate(${scopedDrag.dx / scale}px, ${scopedDrag.dy / scale}px)`
    : "";
  const lensTransform = lens
    ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})`
    : "";
  const transformStack = [dragTranslate, lensTransform].filter(Boolean).join(" ");
  let transition: string;
  if (isDragging || scopedDrag) {
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
    // `paint` containment would clip CSS-transform-scaled children (e.g. the
    // counter-scaled name label in `ChannelTile.DotView`) to the node's
    // `world_w × world_h` box, cutting off long names laterally at low zoom.
    contain: "layout style",
  };
  return (
    <div
      ref={setNodeRef}
      data-spatial-node-id={node.id}
      style={style}
      onPointerEnter={onHoverChange ? () => onHoverChange(true) : undefined}
      onPointerLeave={onHoverChange ? () => onHoverChange(false) : undefined}
      onDoubleClickCapture={handleDoubleClickCapture}
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
          children
        )}
      </DragActivatorContext.Provider>
    </div>
  );
}
