import { useMemo } from "react";
import { Hash, Lock, MessageCircle } from "lucide-react";
import { LucideIconByName } from "../IconPicker";
import { useBots } from "../../api/hooks/useBots";
import { useChannelReadStore } from "../../stores/channelRead";
import type { Channel, BotConfig } from "../../types/api";
import {
  bodyGradientPrimaryOnly,
  bodyGradients,
  bodyParticles,
  widerOrganicBorderRadius,
  type CosmicIntensity,
} from "./cosmicBody";

/**
 * Channel tile with three semantic-zoom levels (P2, redesigned).
 *
 * The card chrome is gone. Each tile is now a soft, hue-tinted **blob**
 * with deterministic per-channel shape (border-radius hashed off the
 * channel id) and a radial gradient backdrop in the channel hue. Identity
 * comes from the color and the shape, not from a generic `# CHANNEL`
 * label.
 *
 *   - **Dot** at zoom < 0.4 — colored disc + counter-scaled name label
 *     below. Reads from far away.
 *   - **Preview** at 0.4 ≤ zoom < 1.0 — blob with name on top, bot
 *     avatar emoji row + recent-count badge + unread dot at the bottom.
 *   - **Snapshot** at zoom ≥ 1.0 — adds a one-line message preview below
 *     the name (progressive disclosure — the densest tier).
 *
 * Backend fields used: `member_bots` (existing), `recent_message_count_24h`
 * + `last_message_preview` (added to `ChannelOut` and computed alongside
 * `last_active_map`).
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
 * Stable hash → 0..2^32 per channel id. Used for deterministic hue and
 * deterministic blob shape (border-radius corners).
 */
function hashId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h;
}

/**
 * Stable hue per channel id. Same id always lands the same color across
 * reloads / different viewers — no DB column needed for this. Exported so
 * other canvas surfaces (orbital scheduled tiles, density halos, movement
 * trails, minimap) can color themselves to match their source channel.
 */
export function channelHue(id: string): number {
  return hashId(id) % 360;
}

export function dotColor(id: string): string {
  return `hsl(${channelHue(id)}, 55%, 58%)`;
}

function channelName(channel: Channel): string {
  return channel.display_name || channel.name;
}

/**
 * Cosmic-body backdrop for the tile body. Composes four layers:
 *
 *   1. Outer silhouette  (`widerOrganicBorderRadius`, 15..85% with asymmetry)
 *   2. Multi-gradient body (centered core + off-center bright eye + dust)
 *   3. Soft inset glow on the silhouette edge (kept from the previous tile)
 *   4. Star particles overlay (faint dots, snapshot/preview tiers only)
 *
 * `tier = "dot"` collapses to a single cheap radial fill — the dot is
 * visually small enough that internal structure is invisible anyway.
 */
function ChannelBlob({
  channelId,
  intensity = "normal",
  tier,
}: {
  channelId: string;
  intensity?: CosmicIntensity;
  tier: "dot" | "preview" | "snapshot";
}) {
  const radius = useMemo(() => widerOrganicBorderRadius(channelId), [channelId]);
  const hue = channelHue(channelId);
  const background = useMemo(
    () =>
      tier === "dot"
        ? bodyGradientPrimaryOnly(hue, intensity)
        : bodyGradients(channelId, hue, intensity),
    [channelId, hue, intensity, tier],
  );
  const particles = useMemo(() => {
    if (tier === "dot") return [];
    return bodyParticles(channelId, tier === "snapshot" ? 10 : 6);
  }, [channelId, tier]);
  const glowAlpha =
    intensity === "warm" ? 0.22 : intensity === "soft" ? 0.06 : 0.12;
  return (
    <div
      aria-hidden
      className="absolute inset-0 pointer-events-none overflow-hidden"
      style={{
        borderRadius: radius,
        backgroundImage: background,
        boxShadow: `inset 0 0 28px hsla(${hue}, 60%, 65%, ${glowAlpha.toFixed(3)})`,
      }}
    >
      {particles.map((p, i) => (
        <span
          key={i}
          className="absolute rounded-full bg-text/40"
          style={{
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: p.size,
            height: p.size,
          }}
        />
      ))}
    </div>
  );
}

function botAvatarEmoji(botId: string, bots: BotConfig[] | undefined): string {
  const bot = bots?.find((b) => b.id === botId);
  return bot?.avatar_emoji || "🤖";
}

function BotAvatarRow({
  channel,
  bots,
  size,
  max,
}: {
  channel: Channel;
  bots: BotConfig[] | undefined;
  size: number;
  max: number;
}) {
  const members = channel.member_bots ?? [];
  if (!members.length) return null;
  const visible = members.slice(0, max);
  const overflow = members.length - visible.length;
  return (
    <div className="flex flex-row items-center gap-1">
      {visible.map((m) => (
        <span
          key={m.id}
          title={m.bot_name || m.bot_id}
          className="flex items-center justify-center rounded-full bg-accent/[0.10] text-accent"
          style={{ width: size, height: size, fontSize: Math.max(10, Math.round(size * 0.6)) }}
        >
          {botAvatarEmoji(m.bot_id, bots)}
        </span>
      ))}
      {overflow > 0 && (
        <span className="text-[10px] text-text-dim ml-0.5">+{overflow}</span>
      )}
    </div>
  );
}

function RecentCountBadge({ count }: { count: number }) {
  if (!count) return null;
  return (
    <span
      className="flex flex-row items-center gap-0.5 text-[10px] text-text-dim"
      title={`${count} message${count === 1 ? "" : "s"} in the last 24h`}
    >
      <MessageCircle size={10} className="opacity-70" />
      <span>{count}</span>
    </span>
  );
}

function UnreadDot() {
  return (
    <span
      className="w-2 h-2 rounded-full bg-accent shrink-0"
      title="Unread activity"
      aria-label="Unread activity"
    />
  );
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
  const effectiveScale = Math.max(0.05, zoom) * Math.max(0.05, extraScale);
  const dotScale = Math.min(5.2, Math.max(1, OVERVIEW_MIN_DOT_SCREEN_PX / (88 * effectiveScale)));
  const labelScale = Math.min(12, Math.max(1, OVERVIEW_MIN_LABEL_SCREEN_PX / (16 * effectiveScale)));
  const radius = useMemo(() => widerOrganicBorderRadius(channel.id), [channel.id]);
  return (
    <div
      data-tile-kind="channel"
      onDoubleClick={onDive}
      className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 cursor-grab flex-col items-center justify-center gap-3 active:cursor-grabbing"
      style={{ width: 240, minHeight: 150 }}
    >
      <div
        className="shadow-md ring-2 ring-text/10"
        style={{
          width: 88,
          height: 88,
          background: dotColor(channel.id),
          borderRadius: radius,
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
  const { data: bots } = useBots();
  const isUnread = useChannelReadStore((s) => s.isUnread(channel.id, channel.updated_at));
  const recentCount = channel.recent_message_count_24h ?? 0;
  return (
    <div
      data-tile-kind="channel"
      onDoubleClick={onDive}
      className="relative w-full h-full cursor-grab active:cursor-grabbing"
    >
      <ChannelBlob channelId={channel.id} intensity={isUnread ? "warm" : "normal"} tier="preview" />
      <div className="absolute inset-0 flex flex-col gap-1.5 p-3">
        <div className="flex flex-row items-center gap-1.5 min-w-0">
          <ChannelGlyph icon={icon} size={14} />
          <span className="text-base font-semibold leading-tight truncate text-text">{name}</span>
          {channel.private && <Lock size={11} className="text-text-dim shrink-0" />}
        </div>
        <div className="flex flex-row items-center gap-2 mt-auto">
          <BotAvatarRow channel={channel} bots={bots} size={18} max={4} />
          <div className="flex flex-row items-center gap-2 ml-auto">
            <RecentCountBadge count={recentCount} />
            {isUnread && <UnreadDot />}
          </div>
        </div>
      </div>
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
  const { data: bots } = useBots();
  const isUnread = useChannelReadStore((s) => s.isUnread(channel.id, channel.updated_at));
  const recentCount = channel.recent_message_count_24h ?? 0;
  const preview = channel.last_message_preview?.trim() || null;
  return (
    <div
      data-tile-kind="channel"
      onDoubleClick={onDive}
      className="relative w-full h-full cursor-grab active:cursor-grabbing"
    >
      <ChannelBlob channelId={channel.id} intensity={isUnread ? "warm" : "normal"} tier="snapshot" />
      <div className="absolute inset-0 flex flex-col gap-1.5 p-4">
        <div className="flex flex-row items-center gap-2 min-w-0">
          <ChannelGlyph icon={icon} size={16} />
          <span className="text-lg font-semibold leading-tight truncate text-text">{name}</span>
          {channel.private && <Lock size={12} className="text-text-dim shrink-0" />}
        </div>
        {preview && (
          <div className="text-[11px] italic text-text-dim leading-snug line-clamp-2 pr-2">
            {preview}
          </div>
        )}
        <div className="flex flex-row items-center gap-2 mt-auto">
          <BotAvatarRow channel={channel} bots={bots} size={20} max={4} />
          <div className="flex flex-row items-center gap-2 ml-auto">
            <RecentCountBadge count={recentCount} />
            {isUnread && <UnreadDot />}
          </div>
        </div>
      </div>
    </div>
  );
}
