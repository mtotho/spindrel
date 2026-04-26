import { Hash } from "lucide-react";
import { formatRelativeTime } from "../../utils/format";
import { LucideIconByName } from "../IconPicker";
import type { Channel } from "../../types/api";

/**
 * Channel tile with three semantic-zoom levels (P2).
 *
 *   - **Dot** at zoom < 0.4 — colored disc + name label, parses at distance.
 *   - **Preview** at 0.4 ≤ zoom < 1.0 — compact card: hash chip, name, last
 *     activity. The legible default.
 *   - **Snapshot** at zoom ≥ 1.0 — expanded card: name, member-bot row,
 *     last activity, double-click hint. Static — *not* live chat (decision 9
 *     in `Track - Spatial Canvas`; live channel embed is parked at P10).
 */

interface ChannelTileProps {
  channel: Channel;
  /** Icon name from the channel's dashboard (`channel:{id}` slug). When
   *  null, the tile falls back to the generic `#` Hash glyph. */
  icon: string | null;
  zoom: number;
  /** Extra wrapper scale applied by the spatial canvas (e.g., fisheye
   *  shrink). Used by counter-scaled labels so they stay readable when the
   *  whole tile has been visually compressed. Defaults to 1. */
  extraScale?: number;
  onDive: () => void;
}

const DOT_THRESHOLD = 0.4;
const SNAPSHOT_THRESHOLD = 1.0;
const OVERVIEW_MIN_DOT_SCREEN_PX = 22;
const OVERVIEW_MIN_LABEL_SCREEN_PX = 13;

export function ChannelTile({ channel, icon, zoom, extraScale = 1, onDive }: ChannelTileProps) {
  if (zoom < DOT_THRESHOLD)
    return <DotView channel={channel} zoom={zoom} extraScale={extraScale} onDive={onDive} />;
  if (zoom < SNAPSHOT_THRESHOLD)
    return <PreviewView channel={channel} icon={icon} onDive={onDive} />;
  return <SnapshotView channel={channel} icon={icon} onDive={onDive} />;
}

function ChannelGlyph({ icon, size, active }: { icon: string | null; size: number; active?: boolean }) {
  const className = active ? "text-accent" : "text-text-dim";
  if (icon) return <LucideIconByName name={icon} size={size} className={className} />;
  return <Hash size={size} className={className} />;
}

/**
 * Stable hue per channel id. Hash → 0..360. Same id always lands the same
 * color across reloads / different viewers — no DB column needed for this.
 *
 * Exported so other canvas surfaces (e.g. orbital scheduled tiles) can color
 * themselves to match their source channel.
 */
export function channelHue(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h % 360;
}

export function dotColor(id: string): string {
  return `hsl(${channelHue(id)}, 55%, 58%)`;
}

function channelName(channel: Channel): string {
  return channel.display_name || channel.name;
}

function DotView({
  channel,
  zoom,
  extraScale,
  onDive,
}: {
  channel: Channel;
  zoom: number;
  extraScale: number;
  onDive: () => void;
}) {
  const name = channelName(channel);
  // Counter-scale overview marks so they stay readable at whole-map zoom.
  // The canvas parent is world-scaled; these local scales set a lower bound
  // in screen pixels without affecting preview/snapshot card zoom states.
  const effectiveScale = Math.max(0.05, zoom) * Math.max(0.05, extraScale);
  const dotScale = Math.min(5.2, Math.max(1, OVERVIEW_MIN_DOT_SCREEN_PX / (88 * effectiveScale)));
  const labelScale = Math.min(12, Math.max(1, OVERVIEW_MIN_LABEL_SCREEN_PX / (16 * effectiveScale)));
  return (
    <div
      data-tile-kind="channel"
      onDoubleClick={onDive}
      className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 cursor-grab flex-col items-center justify-center gap-3 active:cursor-grabbing"
      style={{ width: 240, minHeight: 150 }}
    >
      <div
        className="rounded-full shadow-md ring-2 ring-text/10"
        style={{
          width: 88,
          height: 88,
          background: dotColor(channel.id),
          transform: `scale(${dotScale})`,
          transformOrigin: "center center",
        }}
      />
      <div
        className="text-base font-semibold text-text whitespace-nowrap max-w-full truncate px-2"
        style={{
          transform: `scale(${labelScale})`,
          transformOrigin: "center top",
        }}
      >
        {name}
      </div>
    </div>
  );
}

function PreviewView({
  channel,
  icon,
  onDive,
}: {
  channel: Channel;
  icon: string | null;
  onDive: () => void;
}) {
  const name = channelName(channel);
  const last = formatRelativeTime(channel.last_message_at);
  return (
    <div
      data-tile-kind="channel"
      onDoubleClick={onDive}
      className="w-full h-full rounded-xl border border-surface-border bg-surface-raised text-text shadow-lg flex flex-col gap-2 p-3 cursor-grab active:cursor-grabbing overflow-hidden"
    >
      <div className="flex flex-row items-center gap-1.5 text-[10px] tracking-wider text-text-dim uppercase">
        <span
          className="w-2.5 h-2.5 rounded-full"
          style={{ background: dotColor(channel.id) }}
        />
        <ChannelGlyph icon={icon} size={14} />
        <span>Channel</span>
        {last && <span className="ml-auto normal-case tracking-normal">{last}</span>}
      </div>
      <div className="text-base font-semibold leading-tight truncate">{name}</div>
      {channel.category && (
        <div className="text-[11px] text-text-dim truncate mt-auto">{channel.category}</div>
      )}
    </div>
  );
}

function SnapshotView({
  channel,
  icon,
  onDive,
}: {
  channel: Channel;
  icon: string | null;
  onDive: () => void;
}) {
  const name = channelName(channel);
  const last = formatRelativeTime(channel.last_message_at);
  const members = channel.member_bots ?? [];
  return (
    <div
      data-tile-kind="channel"
      onDoubleClick={onDive}
      className="w-full h-full rounded-xl border border-surface-border bg-surface-raised text-text shadow-lg flex flex-col gap-2 p-4 cursor-grab active:cursor-grabbing overflow-hidden"
    >
      <div className="flex flex-row items-center gap-2 text-[10px] tracking-wider text-text-dim uppercase">
        <span
          className="w-3 h-3 rounded-full"
          style={{ background: dotColor(channel.id) }}
        />
        <ChannelGlyph icon={icon} size={16} />
        <span>Channel</span>
        {channel.private && <span className="ml-1">· private</span>}
        {last && <span className="ml-auto normal-case tracking-normal">{last}</span>}
      </div>
      <div className="text-lg font-semibold leading-tight truncate">{name}</div>
      {channel.category && (
        <div className="text-[11px] text-text-dim truncate">{channel.category}</div>
      )}
      {members.length > 0 && (
        <div className="flex flex-row flex-wrap gap-1 mt-1">
          {members.slice(0, 4).map((m) => (
            <span
              key={m.id}
              title={m.bot_name || m.bot_id}
              className="text-[10px] px-1.5 py-0.5 rounded bg-surface border border-surface-border text-text-dim truncate max-w-[80px]"
            >
              {m.bot_name || m.bot_id}
            </span>
          ))}
          {members.length > 4 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded text-text-dim">
              +{members.length - 4}
            </span>
          )}
        </div>
      )}
      <div className="text-[10px] text-text-dim mt-auto">Double-click to dive</div>
    </div>
  );
}
