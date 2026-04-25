import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, Clock, Sparkles } from "lucide-react";
import type { UpcomingItem } from "../../api/hooks/useUpcomingActivity";
import {
  type LensTransform,
} from "./spatialGeometry";
import {
  formatTimeUntil,
  type UpcomingOrbitSpread,
  upcomingHref,
  upcomingOrbit,
  upcomingTileColor,
  upcomingTypeLabel,
} from "./spatialActivity";

/**
 * UpcomingTile — a single piece of scheduled work orbiting the Now Well
 * (P15). Position is purely time-derived: log-scaled radius from minutes
 * until `scheduled_at`, stable angular slot per item id, squashed orbit so
 * tiles travel along the well's elliptical rings (matching `WELL_Y_SQUASH`).
 *
 * Three semantic-zoom levels:
 *   far  : tiny channel-hued dot, no glyph.
 *   mid  : clock-face diamond glyph, no label.
 *   close: glyph + truncated title + relative time underneath.
 *
 * Click → navigate to the underlying entity (task detail / channel). Hover
 * → native title tooltip with full context. Not draggable; not a spatial
 * node row in the DB.
 */

interface UpcomingTileProps {
  item: UpcomingItem;
  zoom: number;
  /** Live `Date.now()` tick (5s cadence is fine — log-radius motion is
   *  gradual). Recomputes radius each tick so tiles drift inward. */
  tickedNow: number;
  /** Per-tile fisheye scale handed down by SpatialCanvas so labels can
   *  counter-scale through the lens compression. Defaults to 1. */
  extraScale?: number;
  /** Deterministic visual fan-out for items sharing a coarse orbit cell. */
  spread?: UpcomingOrbitSpread;
  /** Shared spatial projection from the canvas lens pass. */
  lens?: LensTransform | null;
}

const TILE_W = 48;
const TILE_H = 48;
const TILE_W_CLOSE = 200;
const TILE_H_CLOSE = 80;

const FAR_THRESHOLD = 0.4;
const CLOSE_THRESHOLD = 1.0;

function TypeGlyph({ type, size, color }: { type: UpcomingItem["type"]; size: number; color: string }) {
  const Icon = type === "heartbeat" ? Activity : type === "memory_hygiene" ? Sparkles : Clock;
  return (
    <div
      className="flex items-center justify-center shadow-sm"
      style={{
        width: size,
        height: size,
        transform: "rotate(45deg)",
        borderRadius: 4,
        background: `${color}26`, // ~15% opacity
        border: `1.5px solid ${color}`,
      }}
    >
      <div style={{ transform: "rotate(-45deg)", color }}>
        <Icon size={Math.round(size * 0.5)} strokeWidth={2} />
      </div>
    </div>
  );
}

export function UpcomingTile({
  item,
  zoom,
  tickedNow,
  extraScale = 1,
  spread = { index: 0, count: 1 },
  lens = null,
}: UpcomingTileProps) {
  const navigate = useNavigate();

  const { x, y, color, minutesUntil } = useMemo(() => {
    const orbit = upcomingOrbit(item, tickedNow, spread);
    return {
      ...orbit,
      color: upcomingTileColor(item),
    };
  }, [item, spread, tickedNow]);

  const handleClick = () => {
    const href = upcomingHref(item);
    if (href) navigate(href);
  };

  const tooltip = [
    item.title,
    upcomingTypeLabel(item),
    item.channel_name || item.bot_name,
    formatTimeUntil(item.scheduled_at, tickedNow),
  ]
    .filter(Boolean)
    .join(" · ");

  // Imminent items get bumped up a zoom tier — a task firing in 10 min
  // should be readable without forcing the user to zoom in.
  const imminentBoost = minutesUntil < 60 ? 0.3 : 0;
  const effectiveZoom = zoom + imminentBoost;

  if (effectiveZoom < FAR_THRESHOLD) {
    return (
      <div
        className="absolute pointer-events-auto cursor-pointer"
        style={{
          left: x - 4,
          top: y - 4,
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: color,
          opacity: 0.9,
          transform: lens ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})` : undefined,
          transformOrigin: "center center",
        }}
        title={tooltip}
        onClick={handleClick}
        data-tile-kind="upcoming"
      />
    );
  }

  if (effectiveZoom < CLOSE_THRESHOLD) {
    return (
      <div
        className="absolute pointer-events-auto cursor-pointer flex items-center justify-center"
        style={{
          left: x - TILE_W / 2,
          top: y - TILE_H / 2,
          width: TILE_W,
          height: TILE_H,
          transform: lens ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})` : undefined,
          transformOrigin: "center center",
        }}
        title={tooltip}
        onClick={handleClick}
        data-tile-kind="upcoming"
      >
        <TypeGlyph type={item.type} size={28} color={color} />
      </div>
    );
  }

  // Close: glyph + label + relative time
  const labelScale = Math.min(2.5, 1 / Math.max(0.05, zoom * Math.max(0.05, extraScale)));
  return (
    <div
      className="absolute pointer-events-auto cursor-pointer flex flex-col items-center justify-start gap-1"
      style={{
        left: x - TILE_W_CLOSE / 2,
        top: y - TILE_H_CLOSE / 2,
        width: TILE_W_CLOSE,
        height: TILE_H_CLOSE,
        transform: lens ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})` : undefined,
        transformOrigin: "center center",
      }}
      title={tooltip}
      onClick={handleClick}
      data-tile-kind="upcoming"
    >
      <TypeGlyph type={item.type} size={32} color={color} />
      <div
        className="text-[11px] font-medium text-text whitespace-nowrap max-w-full truncate px-1"
        style={{
          transform: `scale(${labelScale})`,
          transformOrigin: "center top",
        }}
      >
        {item.title}
      </div>
      <div
        className="text-[10px] text-text-dim whitespace-nowrap"
        style={{
          transform: `scale(${labelScale})`,
          transformOrigin: "center top",
        }}
      >
        {formatTimeUntil(item.scheduled_at, tickedNow)}
      </div>
    </div>
  );
}
