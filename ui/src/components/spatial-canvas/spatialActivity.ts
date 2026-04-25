import type { UpcomingItem } from "../../api/hooks/useUpcomingActivity";
import {
  WELL_X,
  WELL_Y,
  WELL_Y_SQUASH,
  radiusForMinutes,
} from "./spatialGeometry.ts";

export interface UpcomingOrbitSpread {
  index: number;
  count: number;
}

export function upcomingIdentityKey(item: UpcomingItem): string {
  if (item.type === "task" && item.task_id) return `task:${item.task_id}`;
  if (item.type === "heartbeat") return `heartbeat:${item.channel_id ?? item.bot_id}`;
  if (item.type === "memory_hygiene") return `mh:${item.bot_id}`;
  return `${item.type}:${item.scheduled_at}`;
}

export function upcomingReactKey(item: UpcomingItem): string {
  if (item.type === "task" && item.task_id) return `task:${item.task_id}`;
  if (item.type === "heartbeat") {
    return `hb:${item.channel_id ?? item.bot_id}:${item.scheduled_at}`;
  }
  return `mh:${item.bot_id}:${item.scheduled_at}`;
}

export function upcomingTypeLabel(item: UpcomingItem): string {
  if (item.type === "memory_hygiene") return "dreaming";
  return item.type;
}

export function upcomingHref(item: UpcomingItem): string | null {
  if (item.type === "task" && item.task_id) return `/admin/automations/${item.task_id}`;
  if (item.type === "heartbeat" && item.channel_id) return `/channels/${item.channel_id}`;
  if (item.type === "memory_hygiene") return "/admin/learning";
  return item.channel_id ? `/channels/${item.channel_id}` : null;
}

export function upcomingTileColor(item: UpcomingItem): string {
  if (item.channel_id) {
    return `hsl(${stableHue(item.channel_id)}, 55%, 58%)`;
  }
  return `hsl(${stableHue(item.bot_id)}, 30%, 55%)`;
}

export function formatTimeUntil(
  iso: string | null | undefined,
  now: number = Date.now(),
): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const diffMs = t - now;
  if (diffMs < -60_000) return "due";
  const sec = Math.floor(Math.abs(diffMs) / 1000);
  if (sec < 60) return "now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `in ${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `in ${hr}h`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `in ${day}d`;
  const wk = Math.floor(day / 7);
  if (wk < 52) return `in ${wk}w`;
  const yr = Math.floor(day / 365);
  return `in ${yr}y`;
}

export function upcomingOrbit(
  item: UpcomingItem,
  tickedNow: number,
  spread: UpcomingOrbitSpread = { index: 0, count: 1 },
): { x: number; y: number; minutesUntil: number; radius: number; theta: number } {
  const t = Date.parse(item.scheduled_at);
  const minutesUntil = Number.isNaN(t) ? 0 : Math.max(0, (t - tickedNow) / 60_000);
  const r = radiusForMinutes(minutesUntil);
  const theta = angleFor(upcomingIdentityKey(item));
  const spreadOffset = spread.count > 1
    ? (spread.index - (spread.count - 1) / 2) * Math.min(28, Math.max(14, r * 0.045))
    : 0;
  const tangentX = -Math.sin(theta);
  const tangentY = Math.cos(theta) * WELL_Y_SQUASH;
  return {
    x: WELL_X + r * Math.cos(theta) + tangentX * spreadOffset,
    y: WELL_Y + r * Math.sin(theta) * WELL_Y_SQUASH + tangentY * spreadOffset,
    minutesUntil,
    radius: r,
    theta,
  };
}

export function upcomingOrbitBucket(
  item: UpcomingItem,
  tickedNow: number,
): string {
  const orbit = upcomingOrbit(item, tickedNow);
  const radiusBucket = Math.round(orbit.radius / 56);
  const angleBucket = Math.round((orbit.theta * 180 / Math.PI) / 18);
  return `${radiusBucket}:${angleBucket}`;
}

function angleFor(key: string): number {
  return stableHue(key) * (Math.PI / 180);
}

function stableHue(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return h % 360;
}
