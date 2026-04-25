import type { CSSProperties } from "react";

interface UsageHaloProps {
  centerX: number;
  centerY: number;
  radius: number;
  hue: number;
  saturation: number;
  lightness: number;
  /** Peak opacity. When `animate` is true, the breathe cycle dips toward 75% of this and back. */
  opacity: number;
  animate: boolean;
  /** Higher volume → slower breath (perceived weight). Seconds. */
  breathSeconds: number;
  title: string;
}

export function UsageHalo({
  centerX,
  centerY,
  radius,
  hue,
  saturation,
  lightness,
  opacity,
  animate,
  breathSeconds,
  title,
}: UsageHaloProps) {
  const color = `hsl(${hue}, ${saturation}%, ${lightness}%)`;
  const style: CSSProperties = {
    left: centerX - radius,
    top: centerY - radius,
    width: radius * 2,
    height: radius * 2,
    background: `radial-gradient(circle at center, ${color} 0%, ${color} 12%, transparent 72%)`,
    // The keyframe reads `--halo-opacity` and dips to 75% of it at the breath
    // troughs. When `animate` is off, opacity is set directly.
    ...(animate
      ? ({
          ["--halo-opacity" as string]: String(opacity),
          animation: `spatial-halo-breathe ${breathSeconds}s ease-in-out infinite`,
          willChange: "transform, opacity",
        } as CSSProperties)
      : { opacity }),
  };
  return (
    <div
      className="absolute pointer-events-auto rounded-full"
      style={style}
      title={title}
      aria-hidden
    />
  );
}
