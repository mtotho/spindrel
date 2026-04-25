import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import { useUIStore } from "../../stores/ui";
import { useChannels } from "../../api/hooks/useChannels";

/**
 * P1.0 — Integration spike. Three lifecycle proofs:
 *
 *   (a) AppShell overlay lifecycle: this component mounts as a sibling of
 *       the route Outlet. The Outlet stays mounted while the overlay is
 *       open, so active SSE streams (useChannelChat) keep flowing.
 *
 *   (b) Animate-then-navigate: double-click a channel tile → 300ms CSS
 *       transform animation completes first → THEN router.push fires →
 *       overlay closes. Animation runs in this AppShell-level layer, which
 *       survives the route change, so no mid-animation unmount flash.
 *
 *   (c) Iframe gesture shield: the placeholder iframe tile has a drag-
 *       handle chrome strip plus a transparent shield over the iframe
 *       body that blocks pointer events until the tile is "activated"
 *       by click. Esc deactivates.
 *
 * Placeholder visuals — channel tiles are a flat row-grid, not phyllotaxis.
 * Phase 1 (P1+) replaces this with the real backend-driven canvas.
 */

interface Camera {
  x: number;
  y: number;
  scale: number;
}

const DEFAULT_CAMERA: Camera = { x: 0, y: 0, scale: 1 };
const MIN_SCALE = 0.2;
const MAX_SCALE = 3.0;
const DIVE_MS = 300;
const TILE_W = 220;
const TILE_H = 140;
const TILE_GAP = 60;

function tileWorldPos(index: number): { x: number; y: number } {
  const cols = 4;
  const col = index % cols;
  const row = Math.floor(index / cols);
  return {
    x: col * (TILE_W + TILE_GAP),
    y: row * (TILE_H + TILE_GAP),
  };
}

export function SpatialCanvasOverlay() {
  const open = useUIStore((s) => s.spatialOverlayOpen);
  const close = useUIStore((s) => s.closeSpatialOverlay);
  const navigate = useNavigate();
  const { data: channels } = useChannels();

  const [camera, setCamera] = useState<Camera>(DEFAULT_CAMERA);
  const [diving, setDiving] = useState(false);
  const [activeTileId, setActiveTileId] = useState<string | null>(null);

  const viewportRef = useRef<HTMLDivElement>(null);
  const panState = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    cameraX: number;
    cameraY: number;
  } | null>(null);

  useEffect(() => {
    if (!open) {
      setDiving(false);
      setActiveTileId(null);
      setCamera(DEFAULT_CAMERA);
    }
  }, [open]);

  const onBgPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.button !== 0 || diving) return;
      // Only start pan on the viewport background itself, never on tiles
      if (e.target !== e.currentTarget) return;
      panState.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        cameraX: camera.x,
        cameraY: camera.y,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
      setActiveTileId(null);
    },
    [camera.x, camera.y, diving],
  );

  const onBgPointerMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const p = panState.current;
    if (!p || p.pointerId !== e.pointerId) return;
    setCamera((c) => ({
      ...c,
      x: p.cameraX + (e.clientX - p.startX),
      y: p.cameraY + (e.clientY - p.startY),
    }));
  }, []);

  const onBgPointerUp = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const p = panState.current;
    if (!p || p.pointerId !== e.pointerId) return;
    panState.current = null;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
  }, []);

  // Wheel listener attached manually with { passive: false } — React's
  // synthetic onWheel is passive by default, so preventDefault() is silently
  // ignored and the page scrolls underneath.
  useEffect(() => {
    if (!open) return;
    const viewport = viewportRef.current;
    if (!viewport) return;
    function handler(e: WheelEvent) {
      if (diving) return;
      const target = e.target as HTMLElement;
      if (activeTileId && target.closest(`[data-tile-id="${activeTileId}"]`)) {
        return;
      }
      e.preventDefault();
      const rect = viewport!.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const factor = Math.exp(-e.deltaY * 0.001);
      setCamera((c) => {
        const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, c.scale * factor));
        const k = newScale / c.scale;
        return {
          scale: newScale,
          x: cx - (cx - c.x) * k,
          y: cy - (cy - c.y) * k,
        };
      });
    }
    viewport.addEventListener("wheel", handler, { passive: false });
    return () => viewport.removeEventListener("wheel", handler);
  }, [open, diving, activeTileId]);

  const diveToTile = useCallback(
    (channelId: string, world: { x: number; y: number; w: number; h: number }) => {
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!rect) return;
      const targetScale = Math.max(rect.width / world.w, rect.height / world.h);
      const targetX = rect.width / 2 - (world.x + world.w / 2) * targetScale;
      const targetY = rect.height / 2 - (world.y + world.h / 2) * targetScale;
      setDiving(true);
      requestAnimationFrame(() => {
        setCamera({ x: targetX, y: targetY, scale: targetScale });
      });
      // Animate-THEN-navigate: route change happens after the transition
      // completes. Overlay closes on the next tick so the route paints first.
      window.setTimeout(() => {
        navigate(`/channels/${channelId}`);
        window.setTimeout(() => close(), 16);
      }, DIVE_MS);
    },
    [close, navigate],
  );

  if (!open) return null;

  const tiles = (channels ?? []).slice(0, 12);
  const iframeWorld = { x: 4 * (TILE_W + TILE_GAP) + 80, y: 0, w: 320, h: 220 };

  const worldStyle: CSSProperties = {
    transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`,
    transformOrigin: "0 0",
    transition: diving ? `transform ${DIVE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)` : "none",
    willChange: "transform",
  };

  return (
    <div
      ref={viewportRef}
      onPointerDown={onBgPointerDown}
      onPointerMove={onBgPointerMove}
      onPointerUp={onBgPointerUp}
      onPointerCancel={onBgPointerUp}
      data-spatial-canvas-overlay="true"
      className="absolute inset-0 z-30 overflow-hidden select-none bg-surface"
      style={{
        backgroundImage:
          "radial-gradient(rgb(var(--color-text) / 0.05) 1px, transparent 1px)",
        backgroundSize: "32px 32px",
        cursor: panState.current ? "grabbing" : "grab",
      }}
    >
      <div className="absolute inset-0" style={worldStyle}>
        {tiles.map((channel, idx) => {
          const pos = tileWorldPos(idx);
          return (
            <ChannelTile
              key={channel.id}
              channelId={channel.id}
              name={channel.display_name || channel.name}
              x={pos.x}
              y={pos.y}
              onDive={() =>
                diveToTile(channel.id, { ...pos, w: TILE_W, h: TILE_H })
              }
            />
          );
        })}
        <IframeTile
          id="iframe-spike"
          x={iframeWorld.x}
          y={iframeWorld.y}
          w={iframeWorld.w}
          h={iframeWorld.h}
          active={activeTileId === "iframe-spike"}
          onActivate={() => setActiveTileId("iframe-spike")}
          onDeactivate={() => setActiveTileId(null)}
        />
      </div>

      <ChromeBar
        camera={camera}
        onClose={close}
        onRecenter={() => setCamera(DEFAULT_CAMERA)}
        diving={diving}
      />
    </div>
  );
}

interface ChannelTileProps {
  channelId: string;
  name: string;
  x: number;
  y: number;
  onDive: () => void;
}

function ChannelTile({ channelId, name, x, y, onDive }: ChannelTileProps) {
  return (
    <div
      data-tile-id={channelId}
      onDoubleClick={onDive}
      className="absolute rounded-xl border border-surface-border bg-surface-raised text-text shadow-lg select-none cursor-zoom-in flex flex-col gap-2 p-4"
      style={{ left: x, top: y, width: TILE_W, height: TILE_H }}
    >
      <div className="text-[10px] tracking-wider text-text-dim uppercase">
        Channel
      </div>
      <div className="text-lg font-semibold leading-tight">{name}</div>
      <div className="text-[11px] text-text-dim mt-auto">
        Double-click to dive
      </div>
    </div>
  );
}

interface IframeTileProps {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  active: boolean;
  onActivate: () => void;
  onDeactivate: () => void;
}

function IframeTile({
  id,
  x,
  y,
  w,
  h,
  active,
  onActivate,
  onDeactivate,
}: IframeTileProps) {
  const srcDoc = useMemo(
    () => `<!doctype html><html><head><style>
        html, body { margin: 0; height: 100%; font-family: ui-sans-serif, system-ui, sans-serif; background: #1a1e26; color: #e6e8ee; }
        body { padding: 16px; box-sizing: border-box; overflow: auto; }
        h2 { margin: 0 0 12px; font-size: 14px; color: #7c9eff; }
        p { font-size: 12px; line-height: 1.5; opacity: 0.8; }
        ul { font-size: 12px; padding-left: 20px; }
        button { background: #7c9eff; color: #0b0d11; border: 0; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-weight: 600; }
      </style></head><body>
        <h2>Placeholder iframe</h2>
        <p>Proves the gesture shield. While inactive, canvas pans and zooms over this tile. After activation, scroll and clicks inside this iframe work normally.</p>
        <ul>
          <li>Scroll me when active</li>
          <li>Click the button</li>
          <li>Press Esc to deactivate</li>
        </ul>
        <button onclick="alert('iframe click works')">Click me</button>
        <p>Filler content to make the iframe scrollable: ${"x ".repeat(400)}</p>
      </body></html>`,
    [],
  );

  useEffect(() => {
    if (!active) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onDeactivate();
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [active, onDeactivate]);

  return (
    <div
      data-tile-id={id}
      className={
        "absolute rounded-xl bg-surface-raised overflow-hidden shadow-lg flex flex-col " +
        (active
          ? "border border-accent ring-2 ring-accent/40"
          : "border border-surface-border")
      }
      style={{ left: x, top: y, width: w, height: h }}
    >
      <div className="h-7 flex-shrink-0 px-3 flex items-center gap-2 bg-surface/60 border-b border-surface-border text-[11px] font-semibold text-text-dim tracking-wider cursor-grab">
        <span className="opacity-60">▦</span>
        <span>WIDGET (placeholder)</span>
        <span className="ml-auto opacity-60 normal-case font-normal">
          {active ? "active — Esc to release" : "click to activate"}
        </span>
      </div>

      <div className="relative flex-1 min-h-0">
        <iframe
          title="spatial-canvas-iframe-spike"
          srcDoc={srcDoc}
          sandbox="allow-scripts"
          className="absolute inset-0 w-full h-full border-0"
          style={{ pointerEvents: active ? "auto" : "none" }}
        />
        {!active && (
          <div
            data-iframe-shield="true"
            onClick={(e) => {
              e.stopPropagation();
              onActivate();
            }}
            className="absolute inset-0 cursor-pointer"
          />
        )}
      </div>
    </div>
  );
}

interface ChromeBarProps {
  camera: Camera;
  diving: boolean;
  onClose: () => void;
  onRecenter: () => void;
}

function ChromeBar({ camera, diving, onClose, onRecenter }: ChromeBarProps) {
  return (
    <div
      onPointerDown={(e) => e.stopPropagation()}
      onWheel={(e) => e.stopPropagation()}
      className={
        "absolute top-3 right-3 z-[2] flex items-center gap-2 bg-surface-raised/85 backdrop-blur border border-surface-border rounded-lg px-2.5 py-1.5 text-xs text-text-dim transition-opacity " +
        (diving ? "pointer-events-none opacity-50" : "")
      }
    >
      <span className="font-mono">{Math.round(camera.scale * 100)}%</span>
      <button
        onClick={onRecenter}
        className="bg-transparent border border-surface-border text-text px-2.5 py-1 rounded text-xs cursor-pointer hover:bg-surface"
      >
        Recenter
      </button>
      <button
        onClick={onClose}
        className="bg-transparent border border-surface-border text-text px-2.5 py-1 rounded text-xs cursor-pointer hover:bg-surface"
      >
        Close (Esc)
      </button>
    </div>
  );
}
