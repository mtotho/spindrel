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
  /** 0..1 — how far through the dwell timer we are. Linear ramp. */
  progress: number;
}

export function DivePulseOverlay({ channelLabel, progress }: DivePulseOverlayProps) {
  // Eased progress so the cue lands gently then ramps quickly near commit.
  const eased = progress * progress;
  const alpha = Math.max(0, Math.min(0.55, eased * 0.55));
  const inset = Math.max(2, 8 - eased * 6);
  return (
    <div
      aria-hidden
      className="absolute inset-0 z-[3] pointer-events-none"
      style={{
        boxShadow: `inset 0 0 0 ${inset}px rgb(var(--color-accent) / ${alpha.toFixed(3)})`,
        transition: "box-shadow 80ms linear",
      }}
    >
      <div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 px-3 py-1.5 rounded-full text-accent text-sm font-medium"
        style={{
          opacity: Math.min(1, eased * 1.5),
          background: `rgb(var(--color-surface-raised) / ${(0.4 + eased * 0.4).toFixed(2)})`,
          backdropFilter: "blur(6px)",
          transition: "opacity 80ms linear, background 80ms linear",
        }}
      >
        →&nbsp;{channelLabel}
      </div>
    </div>
  );
}
