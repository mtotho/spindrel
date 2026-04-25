import { Hash } from "lucide-react";
import { formatRelativeTime } from "../../utils/format";
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
  zoom: number;
  onDive: () => void;
}

const DOT_THRESHOLD = 0.4;
const SNAPSHOT_THRESHOLD = 1.0;

export function ChannelTile({ channel, zoom, onDive }: ChannelTileProps) {
  if (zoom < DOT_THRESHOLD) return <DotView channel={channel} onDive={onDive} />;
  if (zoom < SNAPSHOT_THRESHOLD) return <PreviewView channel={channel} onDive={onDive} />;
  return <SnapshotView channel={channel} onDive={onDive} />;
}

/**
 * Stable hue per channel id. Hash → 0..360. Same id always lands the same
 * color across reloads / different viewers — no DB column needed for this.
 */
function channelHue(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h % 360;
}

function dotColor(id: string): string {
  return `hsl(${channelHue(id)}, 55%, 58%)`;
}

function channelName(channel: Channel): string {
  return channel.display_name || channel.name;
}

function DotView({ channel, onDive }: { channel: Channel; onDive: () => void }) {
  const name = channelName(channel);
  return (
    <div
      data-tile-kind="channel"
      onDoubleClick={onDive}
      className="w-full h-full flex flex-col items-center justify-center gap-2 cursor-grab active:cursor-grabbing"
    >
      <div
        className="rounded-full shadow-md"
        style={{
          width: 56,
          height: 56,
          background: dotColor(channel.id),
        }}
      />
      <div className="text-sm font-semibold text-text whitespace-nowrap max-w-full truncate px-2">
        {name}
      </div>
    </div>
  );
}

function PreviewView({ channel, onDive }: { channel: Channel; onDive: () => void }) {
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
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: dotColor(channel.id) }}
        />
        <Hash size={11} />
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

function SnapshotView({ channel, onDive }: { channel: Channel; onDive: () => void }) {
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
          className="w-2 h-2 rounded-full"
          style={{ background: dotColor(channel.id) }}
        />
        <Hash size={12} />
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
