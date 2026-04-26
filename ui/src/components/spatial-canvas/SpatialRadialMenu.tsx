import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Footprints,
  Home,
  LocateFixed,
  Map as MapIcon,
  Maximize2,
  Link2,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import type { TrailsMode, DensityIntensity } from "./spatialGeometry";

/**
 * Radial command menu — pressed-Q (or long-press background on touch) opens
 * a wheel of 8 primary actions around the cursor / touch point. Replaces
 * the bottom-right button cluster.
 *
 * Each wedge is one of:
 *   - **command** — fires once on click (Recenter, Now, Fit all)
 *   - **toggle** — flips a boolean (Lines, Map, Bots)
 *   - **cycler** — advances through an enum (Activity, Trails)
 *
 * Toggle / cycler wedges visually indicate their current state via accent
 * tinting so the user can see "what's currently on" at a glance.
 *
 * Dismiss: Esc, click outside the wheel, or trigger again. Auto-clamps to
 * the viewport so the menu never spawns half off-screen.
 */

const SIZE = 200;
const INNER_R = 36;
const OUTER_R = 96;
const WEDGE_GAP_DEG = 3;

export type ActivityState = DensityIntensity;
export type TrailsState = TrailsMode;

export interface RadialActions {
  recenter: () => void;
  fitAll: () => void;
  flyToNow: () => void;
  cycleActivity: () => void;
  cycleTrails: () => void;
  toggleLines: () => void;
  toggleMap: () => void;
  toggleBots: () => void;
}

export interface RadialState {
  activity: ActivityState;
  trails: TrailsState;
  lines: boolean;
  map: boolean;
  bots: boolean;
}

interface SpatialRadialMenuProps {
  /** Screen-space anchor point for the menu (already clamped or unclamped —
   *  the component re-clamps to viewport bounds). */
  anchor: { x: number; y: number };
  state: RadialState;
  actions: RadialActions;
  onClose: () => void;
}

interface WedgeSpec {
  id: string;
  label: string;
  glyph: React.ReactNode;
  active: boolean;
  onClick: () => void;
}

export function SpatialRadialMenu({ anchor, state, actions, onClose }: SpatialRadialMenuProps) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  const wedges: WedgeSpec[] = useMemo(
    () => [
      // 12:00 — Recenter
      {
        id: "recenter",
        label: "Recenter",
        glyph: <Home size={18} strokeWidth={1.7} />,
        active: false,
        onClick: actions.recenter,
      },
      // 1:30 — Activity
      {
        id: "activity",
        label: state.activity === "off" ? "Activity off" : state.activity === "bold" ? "Activity bold" : "Activity",
        glyph: <Sparkles size={18} strokeWidth={1.7} />,
        active: state.activity !== "off",
        onClick: actions.cycleActivity,
      },
      // 3:00 — Lines
      {
        id: "lines",
        label: state.lines ? "Lines on" : "Lines off",
        glyph: <Link2 size={18} strokeWidth={1.7} />,
        active: state.lines,
        onClick: actions.toggleLines,
      },
      // 4:30 — Trails
      {
        id: "trails",
        label: state.trails === "off" ? "Trails off" : state.trails === "all" ? "Trails all" : "Trails hover",
        glyph: <Footprints size={18} strokeWidth={1.7} />,
        active: state.trails !== "off",
        onClick: actions.cycleTrails,
      },
      // 6:00 — Now
      {
        id: "now",
        label: "Now",
        glyph: <Target size={18} strokeWidth={1.7} />,
        active: false,
        onClick: actions.flyToNow,
      },
      // 7:30 — Map
      {
        id: "map",
        label: state.map ? "Map on" : "Map off",
        glyph: <MapIcon size={18} strokeWidth={1.7} />,
        active: state.map,
        onClick: actions.toggleMap,
      },
      // 9:00 — Bots
      {
        id: "bots",
        label: state.bots ? "Bots on" : "Bots off",
        glyph: <Users size={18} strokeWidth={1.7} />,
        active: state.bots,
        onClick: actions.toggleBots,
      },
      // 10:30 — Fit
      {
        id: "fit",
        label: "Fit all",
        glyph: <Maximize2 size={18} strokeWidth={1.7} />,
        active: false,
        onClick: actions.fitAll,
      },
    ],
    [state, actions],
  );

  // Clamp anchor to viewport so the menu stays inside even when triggered at
  // an edge. Use document layout (window.innerWidth/Height) since the portal
  // mounts to body — outside the canvas's coord system.
  const clamped = useMemo(() => {
    const margin = SIZE / 2 + 8;
    const w = window.innerWidth;
    const h = window.innerHeight;
    return {
      x: Math.max(margin, Math.min(w - margin, anchor.x)),
      y: Math.max(margin, Math.min(h - margin, anchor.y)),
    };
  }, [anchor]);

  // Dismiss: Esc keydown anywhere, or pointerdown outside the wedge SVG.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    const onDown = (e: PointerEvent) => {
      const wrap = wrapperRef.current;
      if (!wrap) return;
      const target = e.target as Node | null;
      if (target && wrap.contains(target)) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown, { capture: true });
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown, { capture: true });
    };
  }, [onClose]);

  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const stepDeg = 360 / wedges.length;
  const padDeg = WEDGE_GAP_DEG / 2;

  return createPortal(
    <div
      ref={wrapperRef}
      className="fixed z-[40] pointer-events-none"
      style={{
        left: clamped.x - SIZE / 2,
        top: clamped.y - SIZE / 2,
        width: SIZE,
        height: SIZE,
      }}
    >
      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="pointer-events-auto drop-shadow-[0_8px_24px_rgba(0,0,0,0.45)]"
      >
        {wedges.map((wedge, i) => {
          // Wedge sweeps from (i*stepDeg - 90 - stepDeg/2) to
          // (i*stepDeg - 90 + stepDeg/2). The -90° offset places wedge 0 at
          // 12 o'clock instead of 3 o'clock.
          const startDeg = i * stepDeg - 90 - stepDeg / 2 + padDeg;
          const endDeg = i * stepDeg - 90 + stepDeg / 2 - padDeg;
          const midDeg = (startDeg + endDeg) / 2;
          const path = annulusWedgePath(cx, cy, INNER_R, OUTER_R, startDeg, endDeg);
          const labelR = (INNER_R + OUTER_R) / 2;
          const labelMid = polar(cx, cy, labelR, midDeg);
          return (
            <Wedge
              key={wedge.id}
              path={path}
              wedge={wedge}
              labelMid={labelMid}
              onSelect={() => {
                wedge.onClick();
                onClose();
              }}
            />
          );
        })}
        {/* Center hole — Q glyph + Esc hint. Pure visual; pointer-events on
         *  the surrounding wedges still receive clicks through the empty
         *  center because the wedge paths cover the donut, and the center is
         *  outside any wedge fill so it doesn't intercept. */}
        <circle
          cx={cx}
          cy={cy}
          r={INNER_R - 2}
          fill="rgb(var(--color-surface-raised) / 0.92)"
          stroke="rgb(var(--color-surface-border))"
        />
        <text
          x={cx}
          y={cy - 4}
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-text"
          style={{ font: "600 14px ui-sans-serif, system-ui, sans-serif" }}
        >
          Q
        </text>
        <text
          x={cx}
          y={cy + 12}
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-text-dim"
          style={{ font: "9px ui-sans-serif, system-ui, sans-serif" }}
        >
          Esc to close
        </text>
      </svg>
    </div>,
    document.body,
  );
}

function Wedge({
  path,
  wedge,
  labelMid,
  onSelect,
}: {
  path: string;
  wedge: WedgeSpec;
  labelMid: { x: number; y: number };
  onSelect: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const fill = wedge.active
    ? "rgb(var(--color-accent) / 0.22)"
    : hovered
      ? "rgb(var(--color-accent) / 0.15)"
      : "rgb(var(--color-surface-raised) / 0.92)";
  const stroke = wedge.active || hovered
    ? "rgb(var(--color-accent) / 0.7)"
    : "rgb(var(--color-surface-border))";
  const labelColor = wedge.active || hovered ? "fill-accent" : "fill-text-dim";
  return (
    <g
      className="cursor-pointer"
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      onClick={onSelect}
    >
      <path d={path} fill={fill} stroke={stroke} strokeWidth={1} />
      <foreignObject
        x={labelMid.x - 12}
        y={labelMid.y - 22}
        width={24}
        height={22}
        style={{ pointerEvents: "none" }}
      >
        <div className={`flex items-center justify-center w-full h-full ${labelColor === "fill-accent" ? "text-accent" : "text-text-dim"}`}>
          {wedge.glyph}
        </div>
      </foreignObject>
      <text
        x={labelMid.x}
        y={labelMid.y + 12}
        textAnchor="middle"
        dominantBaseline="central"
        className={labelColor}
        style={{ font: "10px ui-sans-serif, system-ui, sans-serif", pointerEvents: "none" }}
      >
        {wedge.label}
      </text>
    </g>
  );
}

function polar(cx: number, cy: number, r: number, deg: number): { x: number; y: number } {
  const rad = (deg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

/** Build an SVG path for an annulus wedge (donut slice). */
function annulusWedgePath(
  cx: number,
  cy: number,
  innerR: number,
  outerR: number,
  startDeg: number,
  endDeg: number,
): string {
  const outerStart = polar(cx, cy, outerR, startDeg);
  const outerEnd = polar(cx, cy, outerR, endDeg);
  const innerStart = polar(cx, cy, innerR, endDeg);
  const innerEnd = polar(cx, cy, innerR, startDeg);
  const largeArc = endDeg - startDeg > 180 ? 1 : 0;
  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerStart.x} ${innerStart.y}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${innerEnd.x} ${innerEnd.y}`,
    "Z",
  ].join(" ");
}
