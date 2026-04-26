/**
 * UpcomingFirePulse — brief expanding-ring overlay that plays when an
 * `UpcomingItem`'s `scheduled_at` crosses `tickedNow`. The ring fades out
 * over ~1.4s; SpatialCanvas mounts these on demand and unmounts them via
 * the `onDone` callback so the component is fire-and-forget.
 *
 * Pure presentation — no data fetching, no timers other than the unmount
 * deadline. Uses a CSS keyframe so the GPU handles the scale/opacity.
 */

import { useEffect } from "react";
import type { LensTransform } from "./spatialGeometry";

interface UpcomingFirePulseProps {
  x: number;
  y: number;
  color: string;
  /** Lens projection from SpatialCanvas — keeps the pulse anchored to the
   *  same world point as the orbit it fires from. */
  lens?: LensTransform | null;
  onDone: () => void;
}

const PULSE_DURATION_MS = 1400;

export function UpcomingFirePulse({ x, y, color, lens = null, onDone }: UpcomingFirePulseProps) {
  useEffect(() => {
    const id = window.setTimeout(onDone, PULSE_DURATION_MS);
    return () => window.clearTimeout(id);
  }, [onDone]);

  return (
    <div
      className="absolute pointer-events-none"
      style={{
        left: x - 60,
        top: y - 60,
        width: 120,
        height: 120,
        transform: lens
          ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})`
          : undefined,
        transformOrigin: "center center",
      }}
      aria-hidden
    >
      <div
        className="spatial-fire-pulse-ring"
        style={
          {
            "--pulse-color": color,
          } as React.CSSProperties
        }
      />
      <div
        className="spatial-fire-pulse-core"
        style={
          {
            "--pulse-color": color,
          } as React.CSSProperties
        }
      />
    </div>
  );
}
