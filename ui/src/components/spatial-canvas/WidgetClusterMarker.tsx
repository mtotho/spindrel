import { Box } from "lucide-react";

interface WidgetClusterMarkerProps {
  count: number;
  zoom: number;
  opacity: number;
}

export function WidgetClusterMarker({ count, zoom, opacity }: WidgetClusterMarkerProps) {
  const effectiveScale = Math.max(0.05, zoom);
  const markerScale = Math.min(7, Math.max(1, 24 / (58 * effectiveScale)));

  return (
    <div
      data-tile-kind="widget-cluster"
      className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 items-center justify-center"
      style={{
        width: 86,
        height: 86,
        opacity,
        pointerEvents: "none",
      }}
    >
      <div
        className="relative flex h-[58px] w-[58px] rotate-45 items-center justify-center rounded-md border-2 border-accent/70 bg-accent/10 shadow-sm"
        style={{
          transform: `scale(${markerScale}) rotate(45deg)`,
          transformOrigin: "center center",
        }}
      >
        <Box size={22} className="-rotate-45 text-accent/80" />
        {count > 1 && (
          <span className="absolute -right-3 -top-3 -rotate-45 rounded-full border border-surface-border bg-surface-raised px-1.5 py-0.5 text-[10px] font-semibold leading-none text-text shadow-sm">
            {count}
          </span>
        )}
      </div>
    </div>
  );
}
