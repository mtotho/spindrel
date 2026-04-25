/**
 * NowWell — fixed canvas landmark representing "the present moment."
 * Scheduled work (`UpcomingTile`) orbits the well on piecewise time bands;
 * tiles drift inward as their `scheduled_at` approaches now.
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

import { useNavigate } from "react-router-dom";
import {
  type LensTransform,
  WELL_R_MAX,
  WELL_R_MIN,
  WELL_RINGS,
  WELL_X,
  WELL_Y,
  WELL_Y_SQUASH,
  radiusForMinutes,
} from "./spatialGeometry";

export { WELL_R_MAX, WELL_X, WELL_Y, WELL_Y_SQUASH } from "./spatialGeometry";

interface NowWellProps {
  /** Live `Date.now()`-ish tick from the canvas. Drives the center clock
   *  text and re-renders the well in lockstep with orbiting tiles. */
  tickedNow: number;
  zoom: number;
  /** Shared spatial projection from the canvas lens pass. */
  lens?: LensTransform | null;
}

export function NowWell({ tickedNow, zoom, lens = null }: NowWellProps) {
  const navigate = useNavigate();
  const showLabels = zoom >= 0.6;
  // Hit target sized to the inner dark hole — clicking the well takes you
  // to the task list (the "what's all this resolving into?" destination).
  const innerR = WELL_R_MIN * 1.4;
  // SVG is sized to fit the largest ring with a small margin, centered on
  // the absolute (left, top) anchor. Negative offsets center the SVG.
  const pad = 56;
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
        transform: lens
          ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})`
          : undefined,
        transformOrigin: "center center",
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
            <stop offset="0%" stopColor="rgb(var(--color-now-well-core))" stopOpacity="0.98" />
            <stop offset="55%" stopColor="rgb(var(--color-now-well-core))" stopOpacity="0.58" />
            <stop offset="100%" stopColor="rgb(var(--color-now-well-core))" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="now-well-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgb(var(--color-accent))" stopOpacity="0.14" />
            <stop offset="60%" stopColor="rgb(var(--color-accent))" stopOpacity="0.035" />
            <stop offset="100%" stopColor="rgb(var(--color-accent))" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="now-well-orb-blue" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgb(var(--color-accent))" stopOpacity="0.20" />
            <stop offset="45%" stopColor="rgb(var(--color-accent))" stopOpacity="0.07" />
            <stop offset="100%" stopColor="rgb(var(--color-accent))" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="now-well-orb-violet" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgb(var(--color-purple))" stopOpacity="0.15" />
            <stop offset="50%" stopColor="rgb(var(--color-purple))" stopOpacity="0.045" />
            <stop offset="100%" stopColor="rgb(var(--color-purple))" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="now-well-dust" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgb(var(--color-accent))" stopOpacity="0.055" />
            <stop offset="44%" stopColor="rgb(var(--color-text-muted))" stopOpacity="0.038" />
            <stop offset="100%" stopColor="rgb(var(--color-text-muted))" stopOpacity="0" />
          </radialGradient>
          <filter id="now-well-clouds" x="-30%" y="-70%" width="160%" height="240%">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.018 0.085"
              numOctaves="4"
              seed="23"
              result="noise"
            />
            <feColorMatrix
              in="noise"
              type="matrix"
              values="
                0 0 0 0 0.95
                0 0 0 0 0.72
                0 0 0 0 0.55
                0 0 0 0.18 0"
              result="colored"
            />
            <feGaussianBlur in="colored" stdDeviation="2.8" result="soft" />
            <feComposite in="soft" in2="SourceGraphic" operator="in" />
          </filter>
          <mask id="now-well-dust-mask">
            <rect width={svgW} height={svgH} fill="black" />
            <ellipse
              cx={cx}
              cy={cy}
              rx={WELL_R_MIN * 3.45}
              ry={WELL_R_MIN * 1.12}
              fill="white"
              transform={`rotate(-7 ${cx} ${cy})`}
            />
            <ellipse
              cx={cx}
              cy={cy}
              rx={WELL_R_MIN * 1.28}
              ry={WELL_R_MIN * 0.50}
              fill="black"
            />
          </mask>
        </defs>

        {/* Outer glow — visible at far zoom without becoming a second halo system. */}
        <ellipse
          cx={cx}
          cy={cy}
          rx={WELL_R_MAX + pad * 0.65}
          ry={(WELL_R_MAX + pad * 0.65) * WELL_Y_SQUASH}
          fill="url(#now-well-glow)"
        />

        <ellipse
          cx={cx - WELL_R_MIN * 1.55}
          cy={cy - WELL_R_MIN * 0.52}
          rx={WELL_R_MIN * 1.2}
          ry={WELL_R_MIN * 0.72}
          fill="url(#now-well-orb-violet)"
          opacity={0.55}
          transform={`rotate(-12 ${cx - WELL_R_MIN * 1.55} ${cy - WELL_R_MIN * 0.52})`}
        />
        <ellipse
          cx={cx + WELL_R_MIN * 1.85}
          cy={cy + WELL_R_MIN * 0.42}
          rx={WELL_R_MIN * 1.36}
          ry={WELL_R_MIN * 0.58}
          fill="url(#now-well-orb-blue)"
          opacity={0.38}
          transform={`rotate(9 ${cx + WELL_R_MIN * 1.85} ${cy + WELL_R_MIN * 0.42})`}
        />

        <g mask="url(#now-well-dust-mask)" opacity={0.42}>
          <ellipse
            cx={cx}
            cy={cy}
            rx={WELL_R_MIN * 3.2}
            ry={WELL_R_MIN * 0.9}
            fill="url(#now-well-dust)"
            transform={`rotate(-7 ${cx} ${cy})`}
          />
          <ellipse
            cx={cx}
            cy={cy}
            rx={WELL_R_MIN * 3.25}
            ry={WELL_R_MIN * 0.94}
            fill="rgb(var(--color-text-muted))"
            opacity={0.14}
            filter="url(#now-well-clouds)"
            transform={`rotate(-7 ${cx} ${cy})`}
          />
        </g>

        {/* Time-band rings — squashed ellipses to fake isometric tilt. */}
        {WELL_RINGS.map((ring) => {
          const r = radiusForMinutes(ring.minutes);
          const isMajor = ring.major === true;
          return (
            <g key={ring.label}>
              <ellipse
                cx={cx}
                cy={cy}
                rx={r}
                ry={r * WELL_Y_SQUASH}
                fill="none"
                stroke="rgb(var(--color-text) / 0.16)"
                strokeWidth={isMajor ? 1.2 : 0.8}
                strokeDasharray={isMajor ? "5 7" : "2 10"}
                opacity={isMajor ? 1 : 0.58}
              />
              {showLabels && isMajor && (
                <text
                  x={cx}
                  y={cy - r * WELL_Y_SQUASH - 6}
                  textAnchor="middle"
                  className="fill-text-dim"
                  style={{
                    font: "10px ui-sans-serif, system-ui, sans-serif",
                    letterSpacing: "0.08em",
                    opacity: 0.8,
                  }}
                >
                  {ring.label}
                </text>
              )}
            </g>
          );
        })}

        {/* Inner dark radial — event horizon recessed below the canvas plane. */}
        <ellipse
          cx={cx}
          cy={cy}
          rx={WELL_R_MIN * 1.4}
          ry={WELL_R_MIN * 1.4 * WELL_Y_SQUASH}
          fill="url(#now-well-hole)"
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
      <button
        type="button"
        onClick={() => navigate("/admin/tasks")}
        onPointerDown={(e) => e.stopPropagation()}
        title="Open task list"
        aria-label="Open task list"
        className="absolute rounded-full pointer-events-auto cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
        style={{
          left: cx - innerR,
          top: cy - innerR * WELL_Y_SQUASH,
          width: innerR * 2,
          height: innerR * 2 * WELL_Y_SQUASH,
          background: "transparent",
          border: "none",
        }}
      />
    </div>
  );
}
