/**
 * Visual cue while the push-through dive dwell is in flight. As the user
 * keeps zooming into a channel tile past `DIVE_SCALE_THRESHOLD` and the
 * viewport center sits inside the tile bbox, this overlay fades in an accent
 * vignette + a `→ #channel-name` crosshair so the user can either commit
 * (hold the zoom) or back off (zoom out / pan away). Cancel = the parent
 * unmounts this component, which removes the cue instantly.
 *
 * Pure-visual; no pointer events. Sits above the world transform so the
 * vignette frames the actual viewport, not a world-space rect.
 */
interface DivePulseOverlayProps {
  channelLabel: string;
}

export function DivePulseOverlay({ channelLabel }: DivePulseOverlayProps) {
  return (
    <div
      aria-hidden
      className="spatial-dive-pulse absolute inset-0 z-[3] pointer-events-none"
    >
      <div className="spatial-dive-pulse-label absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 px-3 py-1.5 rounded-full text-accent text-sm font-medium">
        →&nbsp;{channelLabel}
      </div>
    </div>
  );
}
