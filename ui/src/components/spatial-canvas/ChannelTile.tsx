import { useId, useMemo } from "react";
import { Hash, Lock, MessageCircle } from "lucide-react";
import { LucideIconByName } from "../IconPicker";
import { useBots } from "../../api/hooks/useBots";
import { useChannelReadStore } from "../../stores/channelRead";
import type { Channel, BotConfig } from "../../types/api";
import {
  planetAtmosphereStops,
  planetBandRects,
  planetMoonProps,
  planetMottledCircles,
  planetRingProps,
  planetSphereStops,
  planetSpotCircles,
  planetSwirlPath,
  planetTraits,
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
 * Per-channel planet rendered as inline SVG. Layers in z-order:
 *
 *   1. Atmosphere glow — soft outer halo that lifts the tile off the dark
 *      canvas. Read tiles still get it; unread amps the alpha.
 *   2. Ring back-half — only when accessory === "ring". Drawn before the
 *      planet so the sphere occludes the front arc.
 *   3. Planet sphere — `<circle r=40>` filled with a fixed-light-source
 *      radial gradient (lit upper-left, terminator lower-right).
 *   4. Surface pattern — clipped to the sphere. One of:
 *      smooth / bands / swirl / spots / mottled, deterministic per channel.
 *   5. Specular highlight — small bright ellipse upper-left, sells the
 *      "this is a 3D body" read.
 *   6. Ring front-half — only when accessory === "ring". Same ellipse as (2)
 *      drawn on top, clipped to the lower half so the front arc crosses the
 *      sphere.
 *   7. Moon — only when accessory === "moon". Small lit circle in the
 *      atmosphere zone.
 *
 * `tier === "dot"` short-circuits the SVG entirely and renders a flat hue
 * disc — at that zoom every internal feature is sub-pixel anyway.
 */
function ChannelPlanet({
  channelId,
  intensity = "normal",
  tier,
}: {
  channelId: string;
  intensity?: CosmicIntensity;
  tier: "dot" | "preview" | "snapshot";
}) {
  const uid = useId().replace(/[:]/g, "");
  const hue = channelHue(channelId);
  const traits = useMemo(() => planetTraits(channelId), [channelId]);

  if (tier === "dot") {
    return (
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none rounded-full"
        style={{
          background: `radial-gradient(circle at 35% 35%, hsl(${hue}, 70%, 70%) 0%, hsl(${hue}, 60%, 50%) 60%, hsl(${hue}, 50%, 28%) 100%)`,
          boxShadow:
            intensity === "warm"
              ? `0 0 18px hsla(${hue}, 80%, 65%, 0.55)`
              : `0 0 10px hsla(${hue}, 70%, 60%, 0.18)`,
        }}
      />
    );
  }

  const atmStops = planetAtmosphereStops(hue, intensity);
  const sphereStops = planetSphereStops(hue);
  const bands = traits.surface === "bands" ? planetBandRects(traits, hue) : [];
  const spots = traits.surface === "spots" ? planetSpotCircles(traits) : [];
  const mottled = traits.surface === "mottled" ? planetMottledCircles(traits, hue) : [];
  const swirl = traits.surface === "swirl" ? planetSwirlPath(traits, hue) : null;
  const ring = traits.accessory === "ring" ? planetRingProps(traits, hue) : null;
  const moon = traits.accessory === "moon" ? planetMoonProps(traits, hue) : null;

  return (
    <svg
      aria-hidden
      viewBox="-10 -10 120 120"
      preserveAspectRatio="xMidYMid meet"
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ overflow: "visible" }}
    >
      <defs>
        <radialGradient id={`atm-${uid}`} cx="50%" cy="50%" r="50%">
          {atmStops.map((s, i) => (
            <stop key={i} offset={s.offset} stopColor={s.color} />
          ))}
        </radialGradient>
        <radialGradient id={`sphere-${uid}`} cx="35%" cy="35%" r="70%">
          {sphereStops.map((s, i) => (
            <stop key={i} offset={s.offset} stopColor={s.color} />
          ))}
        </radialGradient>
        <clipPath id={`clip-${uid}`}>
          <circle cx="50" cy="50" r="40" />
        </clipPath>
        <clipPath id={`ring-front-${uid}`}>
          <rect x="-15" y="50" width="130" height="65" />
        </clipPath>
      </defs>

      {/* Atmosphere halo — covers the SVG out to viewBox edge. */}
      <rect x="-10" y="-10" width="120" height="120" fill={`url(#atm-${uid})`} />

      {/* Ring back-half: full ellipse drawn behind the planet; the sphere
          occludes the front arc, leaving only the back arc visible. */}
      {ring && (
        <ellipse
          cx="50"
          cy="50"
          rx={ring.rx}
          ry={ring.ry}
          fill="none"
          stroke={ring.stroke}
          strokeWidth={ring.strokeWidth}
          strokeOpacity={0.55}
          transform={`rotate(${ring.angle.toFixed(1)} 50 50)`}
        />
      )}

      {/* Planet sphere. */}
      <circle cx="50" cy="50" r="40" fill={`url(#sphere-${uid})`} />

      {/* Surface pattern, clipped to the sphere. */}
      <g clipPath={`url(#clip-${uid})`}>
        {bands.map((b, i) => (
          <rect key={i} x="10" y={b.y.toFixed(2)} width="80" height={b.height.toFixed(2)} fill={b.fill} />
        ))}
        {swirl && (
          <path
            d={swirl.d}
            fill={swirl.fill}
            transform={`rotate(${swirl.rotate.toFixed(1)} 50 50)`}
          />
        )}
        {spots.map((c, i) => (
          <circle key={i} cx={c.cx.toFixed(2)} cy={c.cy.toFixed(2)} r={c.r.toFixed(2)} fill={c.fill} />
        ))}
        {mottled.map((c, i) => (
          <circle key={i} cx={c.cx.toFixed(2)} cy={c.cy.toFixed(2)} r={c.r.toFixed(2)} fill={c.fill} />
        ))}
      </g>

      {/* Specular highlight — sells the spherical read. */}
      <ellipse cx="35" cy="32" rx="11" ry="7" fill="rgba(255,255,255,0.22)" />

      {/* Ring front-half: same ellipse re-drawn on top of the planet, clipped
          to the lower half of the SVG. Approximates the "front arc crosses
          the sphere" Saturn look for the modest tilts (-45..+45) we use. */}
      {ring && (
        <ellipse
          cx="50"
          cy="50"
          rx={ring.rx}
          ry={ring.ry}
          fill="none"
          stroke={ring.stroke}
          strokeWidth={ring.strokeWidth}
          strokeOpacity={0.85}
          transform={`rotate(${ring.angle.toFixed(1)} 50 50)`}
          clipPath={`url(#ring-front-${uid})`}
        />
      )}

      {/* Moon — sits in the atmosphere zone, just outside the sphere edge. */}
      {moon && (
        <>
          <circle cx={moon.cx.toFixed(2)} cy={moon.cy.toFixed(2)} r={moon.r.toFixed(2)} fill={moon.fill} />
          <circle
            cx={(moon.cx + moon.r * 0.35).toFixed(2)}
            cy={(moon.cy + moon.r * 0.35).toFixed(2)}
            r={(moon.r * 0.6).toFixed(2)}
            fill={moon.shadowFill}
            opacity={0.45}
          />
        </>
      )}
    </svg>
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
  const hue = channelHue(channel.id);
  return (
    <div
      data-tile-kind="channel"
      onDoubleClick={onDive}
      className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 cursor-grab flex-col items-center justify-center gap-3 active:cursor-grabbing"
      style={{ width: 240, minHeight: 150 }}
    >
      <div
        className="shadow-md ring-2 ring-text/10 rounded-full"
        style={{
          width: 88,
          height: 88,
          background: `radial-gradient(circle at 35% 35%, hsl(${hue}, 70%, 70%) 0%, hsl(${hue}, 60%, 50%) 60%, hsl(${hue}, 50%, 28%) 100%)`,
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
      <ChannelPlanet channelId={channel.id} intensity={isUnread ? "warm" : "normal"} tier="preview" />
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
      <ChannelPlanet channelId={channel.id} intensity={isUnread ? "warm" : "normal"} tier="snapshot" />
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
