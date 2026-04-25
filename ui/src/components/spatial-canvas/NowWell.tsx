/**
 * NowWell — fixed canvas landmark representing "the present moment."
 * Scheduled work (`UpcomingTile`) orbits the well on log-scaled rings; tiles
 * drift inward as their `scheduled_at` approaches now.
 *
 * Visual language: squashed ellipses + a dark inner radial gradient suggest
 * an isometric "hole in the floor" — the well is recessed below the channel
 * plane. Pure SVG so it composes with the world's `transform: translate()
 * scale()` and the P16 fisheye projection without special-casing.
 *
 * Coordinates are absolutely positioned at world-coords WELL.x / WELL.y.
 * Squash factor must match `UpcomingTile`'s orbit math so rings and tiles
 * sit on the same ellipses.
 */

export const WELL_X = 0;
export const WELL_Y = 2200;
export const WELL_Y_SQUASH = 0.55;

// Time-band ring radii in world px. Match the `radiusForMinutes` math in
// UpcomingTile so a heartbeat scheduled "in 1h" lands on the "1h" ring.
export const WELL_RINGS: { minutes: number; label: string }[] = [
  { minutes: 60, label: "1h" },
  { minutes: 60 * 24, label: "1d" },
  { minutes: 60 * 24 * 7, label: "1w" },
];

export const WELL_R_MIN = 90;
export const WELL_R_MAX = 520;
export const WELL_MAX_HORIZON_MIN = 60 * 24 * 7; // 1 week

/**
 * Map minutes-until → world-px radius. Log-scaled so imminent items crowd
 * close to the well and distant items spread to the outer ring.
 */
export function radiusForMinutes(minutes: number): number {
  const m = Math.max(0, minutes);
  const t = Math.min(1, Math.log(m + 1) / Math.log(WELL_MAX_HORIZON_MIN + 1));
  return WELL_R_MIN + (WELL_R_MAX - WELL_R_MIN) * t;
}

interface NowWellProps {
  /** Live `Date.now()`-ish tick from the canvas. Drives the center clock
   *  text and re-renders the well in lockstep with orbiting tiles. */
  tickedNow: number;
  zoom: number;
}

export function NowWell({ tickedNow, zoom }: NowWellProps) {
  const showLabels = zoom >= 0.6;
  // SVG is sized to fit the largest ring with a small margin, centered on
  // the absolute (left, top) anchor. Negative offsets center the SVG.
  const pad = 40;
  const svgW = (WELL_R_MAX + pad) * 2;
  const svgH = WELL_R_MAX * WELL_Y_SQUASH * 2 + pad * 2;
  const cx = svgW / 2;
  const cy = svgH / 2;

  const time = new Date(tickedNow);
  const hh = String(time.getHours()).padStart(2, "0");
  const mm = String(time.getMinutes()).padStart(2, "0");
  const clockText = `${hh}:${mm}`;

  return (
    <div
      className="absolute pointer-events-none"
      style={{
        left: WELL_X - svgW / 2,
        top: WELL_Y - svgH / 2,
        width: svgW,
        height: svgH,
      }}
      aria-hidden
    >
      <svg
        width={svgW}
        height={svgH}
        viewBox={`0 0 ${svgW} ${svgH}`}
        style={{ overflow: "visible" }}
      >
        <defs>
          <radialGradient id="now-well-hole" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgb(var(--color-bg))" stopOpacity="0.95" />
            <stop offset="55%" stopColor="rgb(var(--color-bg))" stopOpacity="0.55" />
            <stop offset="100%" stopColor="rgb(var(--color-bg))" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="now-well-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgb(var(--color-accent))" stopOpacity="0.18" />
            <stop offset="60%" stopColor="rgb(var(--color-accent))" stopOpacity="0.04" />
            <stop offset="100%" stopColor="rgb(var(--color-accent))" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Outer faint accent glow — hints "something is here" at far zoom. */}
        <ellipse
          cx={cx}
          cy={cy}
          rx={WELL_R_MAX + pad / 2}
          ry={(WELL_R_MAX + pad / 2) * WELL_Y_SQUASH}
          fill="url(#now-well-glow)"
        />

        {/* Time-band rings — squashed ellipses to fake isometric tilt. */}
        {WELL_RINGS.map((ring) => {
          const r = radiusForMinutes(ring.minutes);
          return (
            <g key={ring.label}>
              <ellipse
                cx={cx}
                cy={cy}
                rx={r}
                ry={r * WELL_Y_SQUASH}
                fill="none"
                stroke="rgb(var(--color-text) / 0.18)"
                strokeWidth={1}
                strokeDasharray="4 6"
              />
              {showLabels && (
                <text
                  x={cx}
                  y={cy - r * WELL_Y_SQUASH - 6}
                  textAnchor="middle"
                  className="fill-text-dim"
                  style={{
                    font: "10px ui-sans-serif, system-ui, sans-serif",
                    letterSpacing: "0.08em",
                  }}
                >
                  {ring.label}
                </text>
              )}
            </g>
          );
        })}

        {/* Inner dark radial — reads as a hole in the floor. */}
        <ellipse
          cx={cx}
          cy={cy}
          rx={WELL_R_MIN * 1.4}
          ry={WELL_R_MIN * 1.4 * WELL_Y_SQUASH}
          fill="url(#now-well-hole)"
        />

        {/* Center pulse — the "now" itself. Subtle accent dot. */}
        <ellipse
          cx={cx}
          cy={cy}
          rx={6}
          ry={6 * WELL_Y_SQUASH}
          fill="rgb(var(--color-accent))"
          opacity={0.85}
        />

        {showLabels && (
          <text
            x={cx}
            y={cy + WELL_R_MIN * WELL_Y_SQUASH + 18}
            textAnchor="middle"
            className="fill-text"
            style={{
              font: "600 12px ui-sans-serif, system-ui, sans-serif",
              letterSpacing: "0.05em",
            }}
          >
            now · {clockText}
          </text>
        )}
      </svg>
    </div>
  );
}
