import { useLocation } from "react-router-dom";
import { X } from "lucide-react";
import { useUIStore } from "../../stores/ui";
import { SpatialCanvas } from "./SpatialCanvas";
import { parseChannelSurfaceFromPath } from "../../stores/channelLastSurface";
import { useIsMobile } from "../../hooks/useIsMobile";

/**
 * Overlay shell for the spatial canvas. Wraps `<SpatialCanvas />` with the
 * AppShell-level open/close lifecycle: on `Ctrl+Shift+Space` the overlay
 * mounts as a sibling of the route `<Outlet />` (NOT replacing it), so
 * active SSE streams in `useChannelChat`, composer drafts, and transient
 * route state survive open/close.
 *
 * Dive flow: when a channel tile is double-clicked, `<SpatialCanvas />`
 * runs the 300ms zoom animation, fires `router.push('/channels/:id')`,
 * and then calls `onAfterDive` — which closes this overlay one tick later
 * so the channel route paints before we disappear.
 */
export function SpatialCanvasOverlay() {
  const open = useUIStore((s) => s.spatialOverlayOpen);
  const close = useUIStore((s) => s.closeSpatialOverlay);
  const location = useLocation();
  if (!open) return null;
  // Contextual camera: when the user hits Ctrl+Shift+Space from a channel
  // route, fly to that channel's tile instead of restoring the last-saved
  // camera. Read once per mount — overlay close+reopen re-mounts and
  // re-evaluates against the current route.
  // Match either `/channels/:id/...` (chat) or `/widgets/channel/:id` (the
  // channel's widget dashboard). Both surfaces should fly back to the same
  // tile when the user beams up.
  const initialFlyToChannelId = parseChannelSurfaceFromPath(location.pathname)?.channelId ?? null;
  return (
    <div className="absolute inset-0 z-30">
      <SpatialCanvas onAfterDive={close} initialFlyToChannelId={initialFlyToChannelId} />
      <ChromeBar onClose={close} />
    </div>
  );
}

function ChromeBar({ onClose }: { onClose: () => void }) {
  const isMobile = useIsMobile();
  if (isMobile) {
    // 44×44 hit target — no text label (mobile users can't hit Esc anyway,
    // and the canvas pan/zoom area is the entire viewport, so a button
    // wide enough to read takes meaningful canvas real estate).
    // env(safe-area-inset-*) keeps the button clear of the iPhone notch /
    // Dynamic Island when running as a home-screen PWA in standalone mode.
    return (
      <button
        type="button"
        onClick={onClose}
        onPointerDown={(e) => e.stopPropagation()}
        onPointerUp={(e) => e.stopPropagation()}
        onWheel={(e) => e.stopPropagation()}
        aria-label="Close spatial canvas"
        className="absolute z-[2] flex items-center justify-center w-11 h-11 rounded-full bg-surface-raised/90 backdrop-blur border border-surface-border text-text active:bg-surface"
        style={{
          top:   "max(12px, env(safe-area-inset-top))",
          right: "max(12px, env(safe-area-inset-right))",
        }}
      >
        <X className="w-5 h-5" aria-hidden />
      </button>
    );
  }
  return (
    <div
      onPointerDown={(e) => e.stopPropagation()}
      onWheel={(e) => e.stopPropagation()}
      className="absolute top-3 right-3 z-[2] flex items-center gap-2 bg-surface-raised/85 backdrop-blur border border-surface-border rounded-lg px-2.5 py-1.5 text-xs text-text-dim"
    >
      <button
        onClick={onClose}
        className="bg-transparent border border-surface-border text-text px-2.5 py-1 rounded text-xs cursor-pointer hover:bg-surface"
      >
        Close (Esc)
      </button>
    </div>
  );
}
