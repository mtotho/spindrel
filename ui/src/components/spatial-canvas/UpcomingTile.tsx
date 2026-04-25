import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, Clock, Sparkles } from "lucide-react";
import { formatTimeUntil } from "../../utils/format";
import type { UpcomingItem } from "../../api/hooks/useUpcomingActivity";
import { channelHue } from "./ChannelTile";
import {
  WELL_X,
  WELL_Y,
  WELL_Y_SQUASH,
  radiusForMinutes,
} from "./NowWell";

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
}

const TILE_W = 48;
const TILE_H = 48;
const TILE_W_CLOSE = 200;
const TILE_H_CLOSE = 80;

const FAR_THRESHOLD = 0.4;
const CLOSE_THRESHOLD = 1.0;

function identityKey(item: UpcomingItem): string {
  if (item.type === "task" && item.task_id) return `task:${item.task_id}`;
  if (item.type === "heartbeat") return `heartbeat:${item.channel_id ?? item.bot_id}`;
  if (item.type === "memory_hygiene") return `mh:${item.bot_id}`;
  return `${item.type}:${item.scheduled_at}`;
}

function angleFor(key: string): number {
  // Stable hash → [0, 2π). Same item always lands at the same orbital slot.
  let h = 0;
  for (let i = 0; i < key.length; i++) {
    h = (h * 31 + key.charCodeAt(i)) >>> 0;
  }
  return (h % 360) * (Math.PI / 180);
}

function tileColor(item: UpcomingItem): string {
  if (item.channel_id) {
    return `hsl(${channelHue(item.channel_id)}, 55%, 58%)`;
  }
  // Memory-hygiene cycles often have no channel — fall back to bot hue so
  // they're still differentiated from each other (different bots' cycles
  // get different colors), without coopting the channel palette.
  return `hsl(${channelHue(item.bot_id)}, 30%, 55%)`;
}

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

export function UpcomingTile({ item, zoom, tickedNow, extraScale = 1 }: UpcomingTileProps) {
  const navigate = useNavigate();

  const { x, y, color, key, minutesUntil } = useMemo(() => {
    const k = identityKey(item);
    const t = Date.parse(item.scheduled_at);
    const m = Number.isNaN(t) ? 0 : Math.max(0, (t - tickedNow) / 60_000);
    const r = radiusForMinutes(m);
    const theta = angleFor(k);
    return {
      x: WELL_X + r * Math.cos(theta),
      y: WELL_Y + r * Math.sin(theta) * WELL_Y_SQUASH,
      color: tileColor(item),
      key: k,
      minutesUntil: m,
    };
  }, [item, tickedNow]);

  const handleClick = () => {
    if (item.type === "task" && item.task_id) {
      navigate(`/admin/tasks/${item.task_id}`);
    } else if (item.type === "heartbeat" && item.channel_id) {
      navigate(`/channels/${item.channel_id}`);
    }
    // memory_hygiene: no nav for v1 (no bot detail page yet).
  };

  const tooltip = [
    item.title,
    item.type,
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
