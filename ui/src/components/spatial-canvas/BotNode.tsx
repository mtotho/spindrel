import {
  useEffect,
  useRef,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import {
  LENS_SETTLE_MS,
  MIN_SCALE,
  type LensTransform,
} from "./spatialGeometry";
import type { WorkspaceMapObjectState } from "../../api/hooks/useWorkspaceMapState";
import { ObjectStatusPill, statusRingClass } from "./SpatialObjectStatus";

interface ManualBotNodeProps {
  node: SpatialNode;
  isDragging: boolean;
  diving: boolean;
  dragEnabled: boolean;
  lens: LensTransform | null;
  lensSettling: boolean;
  reduced: boolean;
  onPointerDown: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onClick?: () => void;
  onDoubleClick: () => void;
  onHoverChange?: (hovered: boolean) => void;
  children: ReactNode;
}

export function ManualBotNode({
  node,
  isDragging,
  diving,
  dragEnabled,
  lens,
  lensSettling,
  reduced,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onClick,
  onDoubleClick,
  onHoverChange,
  children,
}: ManualBotNodeProps) {
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
    left: node.world_x,
    top: node.world_y,
    width: node.world_w,
    height: node.world_h,
    zIndex: isDragging ? 10 : node.z_index,
    transform: transformStack || undefined,
    transformOrigin: "center center",
    transition,
    touchAction: "none",
    cursor: diving ? "default" : isDragging ? "grabbing" : dragEnabled ? "grab" : "pointer",
    opacity: reduced ? 0.68 : 1,
    contain: "layout paint style",
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

export function BotTile({
  name,
  botId,
  avatarEmoji,
  zoom,
  reduced,
  workState,
}: {
  name: string;
  botId: string;
  avatarEmoji: string | null;
  zoom: number;
  reduced: boolean;
  workState?: WorkspaceMapObjectState | null;
}) {
  const compact = zoom < 0.55;
  const avatar = avatarEmoji || "🤖";
  const markerScale = compact ? Math.max(1, 34 / ((reduced ? 84 : 112) * Math.max(zoom, MIN_SCALE))) : 1;
  const labelScale = compact ? Math.max(1, 14 / (14 * Math.max(zoom, MIN_SCALE))) : 1;
  const outerSize = reduced ? 84 : 112;
  const innerSize = reduced ? 58 : 82;
  const emojiSize = reduced ? 28 : 38;
  const labelTop = reduced ? 108 : 132;
  return (
    <div
      className="relative flex h-full w-full items-center justify-center overflow-visible"
      title={`${name} (${botId})`}
    >
      <div
        className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-accent/55 bg-surface-raised shadow-[0_10px_28px_rgb(var(--color-accent)/0.12)] ${statusRingClass(workState)}`}
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
        {!compact && (
          <div className="mt-1 flex justify-center">
            <ObjectStatusPill state={workState} compact />
          </div>
        )}
      </div>
    </div>
  );
}
