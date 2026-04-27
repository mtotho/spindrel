import type { ComponentType } from "react";
import type { LucideProps } from "lucide-react";
import type { Camera } from "./spatialGeometry";
import { computeEdgeBeaconPosition } from "./spatialWayfinding";

interface SpatialEdgeBeacon {
  id: string;
  label: string;
  shortLabel: string;
  worldX: number;
  worldY: number;
  colorClass: string;
  icon: ComponentType<LucideProps>;
  onClick: () => void;
  persistent?: boolean;
}

interface SpatialEdgeBeaconsProps {
  camera: Camera;
  viewport: { w: number; h: number };
  beacons: SpatialEdgeBeacon[];
  maxVisible?: number;
}

export function SpatialEdgeBeacons({
  camera,
  viewport,
  beacons,
  maxVisible = 9,
}: SpatialEdgeBeaconsProps) {
  if (!viewport.w || !viewport.h) return null;
  const visible = beacons
    .map((beacon) => {
      const screen = {
        x: beacon.worldX * camera.scale + camera.x,
        y: beacon.worldY * camera.scale + camera.y,
      };
      const pos = computeEdgeBeaconPosition(
        screen,
        viewport,
        42,
        48,
        beacon.persistent ? Number.POSITIVE_INFINITY : 280,
      );
      return pos ? { beacon, pos } : null;
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)
    .sort((a, b) => a.pos.offscreenDistancePx - b.pos.offscreenDistancePx)
    .slice(0, maxVisible);

  if (!visible.length) return null;

  return (
    <div
      className="absolute inset-0 z-[1] pointer-events-none"
      aria-label="Offscreen canvas landmarks"
    >
      {visible.map(({ beacon, pos }) => {
        const Icon = beacon.icon;
        const labelOffset =
          pos.side === "left"
            ? "left-full ml-2"
            : pos.side === "right"
              ? "right-full mr-2"
              : pos.side === "top"
                ? "top-full mt-2"
                : "bottom-full mb-2";
        const labelTransform =
          pos.side === "top" || pos.side === "bottom"
            ? "left-1/2 -translate-x-1/2"
            : "top-1/2 -translate-y-1/2";

        return (
          <button
            key={beacon.id}
            type="button"
            onClick={beacon.onClick}
            onPointerDown={(e) => e.stopPropagation()}
            title={`Fly to ${beacon.label}`}
            aria-label={`Fly to ${beacon.label}`}
            className={`group absolute pointer-events-auto ${beacon.persistent ? "h-11 w-11 opacity-85" : "h-9 w-9 opacity-45"} -translate-x-1/2 -translate-y-1/2 rounded-full border bg-surface-raised/35 backdrop-blur text-xs font-semibold shadow-lg hover:opacity-95 focus-visible:opacity-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 transition-opacity ${beacon.colorClass}`}
            style={{ left: pos.x, top: pos.y }}
          >
            <span
              className="absolute inset-[-5px] rounded-full border opacity-20 group-hover:opacity-45"
              aria-hidden="true"
            />
            <span
              className="absolute left-1/2 top-1/2 block h-4 w-px origin-bottom bg-current opacity-55"
              style={{ transform: `translate(-50%, -100%) rotate(${pos.angleDeg + 90}deg)` }}
              aria-hidden="true"
            />
            <span className="relative flex h-full w-full items-center justify-center">
              <Icon size={15} />
              <span className="sr-only">{beacon.shortLabel}</span>
            </span>
            <span
              className={`absolute ${labelOffset} ${labelTransform} whitespace-nowrap rounded border border-surface-border/70 bg-surface-raised/90 px-2 py-1 text-[11px] text-text opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100`}
              aria-hidden="true"
            >
              {beacon.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
