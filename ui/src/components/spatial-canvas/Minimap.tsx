import { useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import { dotColor } from "./spatialIdentity";
import {
  getViewportWorldBbox,
  type Camera,
  type WorldBbox,
} from "./spatialGeometry";

/**
 * Bottom-left corner overview of the entire spatial canvas.
 *
 * Renders channel dots, faint widget rectangles, and bot emoji at world
 * positions auto-fit to the minimap's pixel rect. A camera-derived viewport
 * rect overlay shows where the user currently is. Clicking anywhere flies
 * the camera so that world point centers in the viewport at the user's
 * current zoom (capped at preview zoom so a click on a distant region
 * doesn't slam them into max zoom of empty space).
 *
 * Faint by default (~25% opacity), opaque on hover, so it doesn't compete
 * visually with the canvas itself. A small × dismisses; the main `Map`
 * chrome toggle restores it.
 */
const MINIMAP_W_LG = 200;
const MINIMAP_H_LG = 140;
const MINIMAP_W_SM = 140;
const MINIMAP_H_SM = 100;
const MINIMAP_HIDE_BELOW_PX = 400;
const MINIMAP_SM_BREAKPOINT_PX = 640;
const MINIMAP_PAD_RATIO = 0.1;

function pickMinimapSize(viewportW: number): { w: number; h: number } | null {
  if (viewportW > 0 && viewportW < MINIMAP_HIDE_BELOW_PX) return null;
  if (viewportW > 0 && viewportW < MINIMAP_SM_BREAKPOINT_PX) {
    return { w: MINIMAP_W_SM, h: MINIMAP_H_SM };
  }
  return { w: MINIMAP_W_LG, h: MINIMAP_H_LG };
}
// Fall-back world bbox when there is no content to fit. Keeps the click-math
// well-defined and gives the viewport rect somewhere sensible to live.
const FALLBACK_WORLD_HALF = 1500;

interface MinimapProps {
  camera: Camera;
  viewport: { w: number; h: number };
  nodes: SpatialNode[];
  /** Fly the camera to center the given world point. The minimap doesn't
   *  know about scheduleCamera — caller wires the smooth transition. */
  onJumpTo: (worldX: number, worldY: number) => void;
  onClose: () => void;
}

export function Minimap({ camera, viewport, nodes, onJumpTo, onClose }: MinimapProps) {
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [hovered, setHovered] = useState(false);

  const dim = pickMinimapSize(viewport.w);
  const fit = useMemo(
    () => (dim ? computeFit(nodes, viewport, camera, dim) : null),
    [nodes, viewport, camera, dim],
  );

  if (!dim || !fit) return null;
  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    const btn = buttonRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const localX = e.clientX - rect.left;
    const localY = e.clientY - rect.top;
    if (localX < 0 || localY < 0 || localX > dim.w || localY > dim.h) return;
    const wx = (localX - fit.offsetX) / fit.scale + fit.bbox.minX;
    const wy = (localY - fit.offsetY) / fit.scale + fit.bbox.minY;
    onJumpTo(wx, wy);
  };

  return (
    <div
      className="absolute bottom-4 left-4 z-[2]"
      style={{
        opacity: hovered ? 0.95 : 0.32,
        transition: "opacity 160ms ease-out",
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-label="Spatial canvas minimap — click to fly camera"
        onClick={handleClick}
        onPointerDown={(e) => e.stopPropagation()}
        onWheel={(e) => e.stopPropagation()}
        className="block bg-surface-raised/60 backdrop-blur border border-surface-border/60 rounded-lg overflow-hidden cursor-crosshair"
        style={{ width: dim.w, height: dim.h }}
      >
        <svg
          width={dim.w}
          height={dim.h}
          viewBox={`0 0 ${dim.w} ${dim.h}`}
          style={{ pointerEvents: "none", display: "block" }}
        >
          <MinimapContent nodes={nodes} fit={fit} />
          <MinimapViewportRect camera={camera} viewport={viewport} fit={fit} dim={dim} />
        </svg>
      </button>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        onPointerDown={(e) => e.stopPropagation()}
        aria-label="Hide minimap"
        title="Hide minimap"
        className="absolute top-1 right-1 w-5 h-5 flex items-center justify-center rounded text-text-dim hover:text-text hover:bg-surface/70 cursor-pointer"
      >
        <X size={11} />
      </button>
    </div>
  );
}

interface FitMath {
  bbox: WorldBbox;
  scale: number;
  offsetX: number;
  offsetY: number;
}

function computeFit(
  nodes: SpatialNode[],
  viewport: { w: number; h: number },
  camera: Camera,
  dim: { w: number; h: number },
): FitMath {
  const bbox = boundsOfNodes(nodes, camera, viewport);
  const worldW = Math.max(1, bbox.maxX - bbox.minX);
  const worldH = Math.max(1, bbox.maxY - bbox.minY);
  const padW = dim.w * (1 - MINIMAP_PAD_RATIO * 2);
  const padH = dim.h * (1 - MINIMAP_PAD_RATIO * 2);
  const sx = padW / worldW;
  const sy = padH / worldH;
  const scale = Math.min(sx, sy);
  const fitW = worldW * scale;
  const fitH = worldH * scale;
  const offsetX = (dim.w - fitW) / 2;
  const offsetY = (dim.h - fitH) / 2;
  return { bbox, scale, offsetX, offsetY };
}

function boundsOfNodes(
  nodes: SpatialNode[],
  camera: Camera,
  viewport: { w: number; h: number },
): WorldBbox {
  if (!nodes.length) {
    // No content yet — center on (0, 0) with a sensible fixed half-extent so
    // the viewport rect still has a frame to draw against.
    return {
      minX: -FALLBACK_WORLD_HALF,
      minY: -FALLBACK_WORLD_HALF,
      maxX: FALLBACK_WORLD_HALF,
      maxY: FALLBACK_WORLD_HALF,
    };
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of nodes) {
    if (n.world_x < minX) minX = n.world_x;
    if (n.world_y < minY) minY = n.world_y;
    if (n.world_x + n.world_w > maxX) maxX = n.world_x + n.world_w;
    if (n.world_y + n.world_h > maxY) maxY = n.world_y + n.world_h;
  }
  // Always include the current viewport so the rect overlay isn't clipped
  // when the camera has wandered past the existing content.
  if (viewport.w > 0 && viewport.h > 0) {
    const vp = getViewportWorldBbox(camera, viewport, 0);
    if (vp.minX < minX) minX = vp.minX;
    if (vp.minY < minY) minY = vp.minY;
    if (vp.maxX > maxX) maxX = vp.maxX;
    if (vp.maxY > maxY) maxY = vp.maxY;
  }
  return { minX, minY, maxX, maxY };
}

function MinimapContent({ nodes, fit }: { nodes: SpatialNode[]; fit: FitMath }) {
  const project = (wx: number, wy: number) => ({
    x: (wx - fit.bbox.minX) * fit.scale + fit.offsetX,
    y: (wy - fit.bbox.minY) * fit.scale + fit.offsetY,
  });
  return (
    <g>
      {nodes.map((n) => {
        const cx = n.world_x + n.world_w / 2;
        const cy = n.world_y + n.world_h / 2;
        const pt = project(cx, cy);
        if (n.channel_id) {
          return (
            <circle
              key={n.id}
              cx={pt.x}
              cy={pt.y}
              r={3}
              fill={dotColor(n.channel_id)}
              opacity={0.85}
            />
          );
        }
        if (n.widget_pin_id) {
          // Widget tile — faint outlined rect at its world footprint.
          const tl = project(n.world_x, n.world_y);
          const br = project(n.world_x + n.world_w, n.world_y + n.world_h);
          const w = Math.max(2, br.x - tl.x);
          const h = Math.max(2, br.y - tl.y);
          return (
            <rect
              key={n.id}
              x={tl.x}
              y={tl.y}
              width={w}
              height={h}
              fill="none"
              stroke="currentColor"
              strokeWidth={0.75}
              className="text-text-dim/50"
            />
          );
        }
        if (n.bot_id) {
          const emoji = n.bot?.avatar_emoji || "🤖";
          return (
            <text
              key={n.id}
              x={pt.x}
              y={pt.y}
              fontSize={10}
              textAnchor="middle"
              dominantBaseline="central"
            >
              {emoji}
            </text>
          );
        }
        return null;
      })}
    </g>
  );
}

function MinimapViewportRect({
  camera,
  viewport,
  fit,
  dim,
}: {
  camera: Camera;
  viewport: { w: number; h: number };
  fit: FitMath;
  dim: { w: number; h: number };
}) {
  if (!viewport.w || !viewport.h) return null;
  const vp = getViewportWorldBbox(camera, viewport, 0);
  const tlx = (vp.minX - fit.bbox.minX) * fit.scale + fit.offsetX;
  const tly = (vp.minY - fit.bbox.minY) * fit.scale + fit.offsetY;
  const brx = (vp.maxX - fit.bbox.minX) * fit.scale + fit.offsetX;
  const bry = (vp.maxY - fit.bbox.minY) * fit.scale + fit.offsetY;
  const x = Math.max(0, tlx);
  const y = Math.max(0, tly);
  const w = Math.max(2, Math.min(dim.w, brx) - x);
  const h = Math.max(2, Math.min(dim.h, bry) - y);
  return (
    <rect
      x={x}
      y={y}
      width={w}
      height={h}
      fill="currentColor"
      fillOpacity={0.08}
      stroke="currentColor"
      strokeWidth={1.25}
      className="text-accent"
    />
  );
}
