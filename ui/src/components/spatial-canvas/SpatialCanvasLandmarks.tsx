import { Radar } from "lucide-react";

/**
 * Passive landmark at world (0,0). Two faint dashed rings + a center dot —
 * enough to reorient when the user has panned far away or zoomed all the
 * way out, subtle enough to stay out of the way at close zoom.
 */
export function OriginMarker() {
  return (
    <div
      className="absolute pointer-events-none"
      style={{ left: 0, top: 0 }}
      aria-hidden
    >
      <div
        className="absolute rounded-full border border-dashed border-text-dim/25"
        style={{ width: 800, height: 800, left: -400, top: -400 }}
      />
      <div
        className="absolute rounded-full border border-dashed border-text-dim/35"
        style={{ width: 280, height: 280, left: -140, top: -140 }}
      />
      <div
        className="absolute rounded-full bg-text-dim/40"
        style={{ width: 8, height: 8, left: -4, top: -4 }}
      />
    </div>
  );
}

export function AttentionHubLandmark({
  activeCount,
  mappedCount,
  signalsVisible,
  zoom,
  onOpen,
}: {
  activeCount: number;
  mappedCount: number;
  signalsVisible: boolean;
  zoom: number;
  onOpen: () => void;
}) {
  const compact = zoom < 0.45;
  const size = compact ? 178 : 220;
  const visibleCount = signalsVisible ? mappedCount : 0;
  return (
    <button
      type="button"
      className="absolute flex flex-col items-center justify-center rounded-full border border-warning/45 bg-surface-raised/85 text-text backdrop-blur transition-transform hover:scale-105 hover:border-warning/80"
      style={{
        left: -size / 2,
        top: -size / 2,
        width: size,
        height: size,
        zIndex: 4,
      }}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onOpen();
      }}
      title="Open Attention Hub"
    >
      <span className="absolute inset-4 rounded-full border border-warning/20" aria-hidden="true" />
      <span className="absolute inset-10 rounded-full border border-warning/25" aria-hidden="true" />
      <span className="absolute bottom-10 h-14 w-px bg-warning/45" aria-hidden="true" />
      <Radar className="mb-2 text-warning" size={compact ? 46 : 58} />
      {!compact && <span className="text-sm font-semibold">Attention Hub</span>}
      {signalsVisible && visibleCount > 0 ? (
        <span className="mt-1 rounded-full bg-warning/10 px-2.5 py-0.5 text-[11px] font-semibold text-warning">{visibleCount} mapped</span>
      ) : (
        <span className="mt-1 text-[11px] text-text-dim">{activeCount} active</span>
      )}
    </button>
  );
}
