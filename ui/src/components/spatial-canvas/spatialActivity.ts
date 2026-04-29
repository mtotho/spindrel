import type { UpcomingItem } from "../../api/hooks/useUpcomingActivity";
import {
  WELL_X,
  WELL_Y,
  WELL_Y_SQUASH,
  radiusForMinutes,
} from "./spatialGeometry.ts";

/** Live well center used by orbit math. Defaults to the seed coords; the
 *  canvas overrides this each render with the live landmark position so
 *  orbits track user drags of the Now Well landmark. */
export interface WellCenter {
  x: number;
  y: number;
}
const DEFAULT_WELL_CENTER: WellCenter = { x: WELL_X, y: WELL_Y };

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
  if (item.type === "heartbeat" && item.channel_id) return `/channels/${item.channel_id}/settings#automation`;
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
  well: WellCenter = DEFAULT_WELL_CENTER,
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
    x: well.x + r * Math.cos(theta) + tangentX * spreadOffset,
    y: well.y + r * Math.sin(theta) * WELL_Y_SQUASH + tangentY * spreadOffset,
    minutesUntil,
    radius: r,
    theta,
  };
}

export function upcomingOrbitBucket(
  item: UpcomingItem,
  tickedNow: number,
  well: WellCenter = DEFAULT_WELL_CENTER,
): string {
  const orbit = upcomingOrbit(item, tickedNow, undefined, well);
  const radiusBucket = Math.round(orbit.radius / 56);
  const angleBucket = Math.round((orbit.theta * 180 / Math.PI) / 18);
  return `${radiusBucket}:${angleBucket}`;
}

export interface ChannelScheduleAnchor {
  channelId: string;
  nodeId?: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export type ChannelScheduleSatelliteState = "normal" | "soon" | "imminent" | "due";

export interface ChannelScheduleSatellite {
  key: string;
  channelId: string;
  nodeId?: string;
  item: UpcomingItem;
  x: number;
  y: number;
  anchorX: number;
  anchorY: number;
  minutesUntil: number;
  state: ChannelScheduleSatelliteState;
  index: number;
  visibleCount: number;
  totalCount: number;
}

export interface ChannelScheduleOverflow {
  key: string;
  channelId: string;
  nodeId?: string;
  x: number;
  y: number;
  anchorX: number;
  anchorY: number;
  count: number;
}

export interface ChannelScheduleSatelliteLayout {
  satellites: ChannelScheduleSatellite[];
  overflow: ChannelScheduleOverflow[];
}

const CHANNEL_SCHEDULE_SLOT_DEGREES = [-68, -24, 20];
const CHANNEL_SCHEDULE_OVERFLOW_DEGREES = 56;

export function isChannelScheduleItem(item: UpcomingItem): boolean {
  return Boolean(item.channel_id && (item.type === "heartbeat" || (item.type === "task" && item.task_id)));
}

export function scheduleSatelliteState(
  iso: string | null | undefined,
  now: number = Date.now(),
): { state: ChannelScheduleSatelliteState; minutesUntil: number } {
  const t = iso ? Date.parse(iso) : NaN;
  const minutesUntil = Number.isNaN(t) ? 0 : (t - now) / 60_000;
  if (minutesUntil <= 0) return { state: "due", minutesUntil };
  if (minutesUntil < 15) return { state: "imminent", minutesUntil };
  if (minutesUntil < 60) return { state: "soon", minutesUntil };
  return { state: "normal", minutesUntil };
}

export function channelScheduleSatellites(
  items: UpcomingItem[],
  anchors: ChannelScheduleAnchor[],
  tickedNow: number,
  limitPerChannel = 3,
): ChannelScheduleSatelliteLayout {
  const anchorByChannel = new Map(anchors.map((anchor) => [anchor.channelId, anchor]));
  const grouped = new Map<string, UpcomingItem[]>();
  for (const item of items) {
    if (!isChannelScheduleItem(item) || !item.channel_id || !anchorByChannel.has(item.channel_id)) continue;
    const bucket = grouped.get(item.channel_id) ?? [];
    bucket.push(item);
    grouped.set(item.channel_id, bucket);
  }

  const satellites: ChannelScheduleSatellite[] = [];
  const overflow: ChannelScheduleOverflow[] = [];
  for (const [channelId, bucket] of grouped) {
    const anchor = anchorByChannel.get(channelId);
    if (!anchor) continue;
    bucket.sort((a, b) => Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at));
    const visible = bucket.slice(0, limitPerChannel);
    const anchorX = anchor.x + anchor.w / 2;
    const anchorY = anchor.y + anchor.h / 2;
    const radius = Math.max(136, Math.min(190, Math.max(anchor.w, anchor.h) * 0.62));
    const rotation = ((stableHue(channelId) % 9) - 4) * (Math.PI / 180) * 3;
    visible.forEach((item, index) => {
      const slotDeg = CHANNEL_SCHEDULE_SLOT_DEGREES[Math.min(index, CHANNEL_SCHEDULE_SLOT_DEGREES.length - 1)];
      const theta = slotDeg * (Math.PI / 180) + rotation;
      const { state, minutesUntil } = scheduleSatelliteState(item.scheduled_at, tickedNow);
      satellites.push({
        key: `schedule:${upcomingReactKey(item)}`,
        channelId,
        nodeId: anchor.nodeId,
        item,
        x: anchorX + Math.cos(theta) * radius,
        y: anchorY + Math.sin(theta) * radius * 0.82,
        anchorX,
        anchorY,
        minutesUntil,
        state,
        index,
        visibleCount: visible.length,
        totalCount: bucket.length,
      });
    });
    const extra = bucket.length - visible.length;
    if (extra > 0) {
      const theta = CHANNEL_SCHEDULE_OVERFLOW_DEGREES * (Math.PI / 180) + rotation;
      overflow.push({
        key: `schedule-overflow:${channelId}`,
        channelId,
        nodeId: anchor.nodeId,
        x: anchorX + Math.cos(theta) * radius,
        y: anchorY + Math.sin(theta) * radius * 0.82,
        anchorX,
        anchorY,
        count: extra,
      });
    }
  }
  return { satellites, overflow };
}

function angleFor(key: string): number {
  return stableHue(key) * (Math.PI / 180);
}

function stableHue(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return h % 360;
}
