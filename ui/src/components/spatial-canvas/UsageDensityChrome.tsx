import { useEffect, useRef, useState } from "react";
import { Settings2 } from "lucide-react";
import type { DensityWindow } from "./UsageDensityLayer";
import type { DensityIntensity } from "./spatialGeometry";

interface UsageDensityChromeProps {
  intensity: DensityIntensity;
  onCycleIntensity: () => void;
  window: DensityWindow;
  onWindowChange: (w: DensityWindow) => void;
  compare: boolean;
  onCompareChange: (c: boolean) => void;
  animate: boolean;
  onAnimateChange: (a: boolean) => void;
  connectionsEnabled: boolean;
  onConnectionsToggle: () => void;
}

const WINDOWS: DensityWindow[] = ["24h", "7d", "30d"];

const INTENSITY_LABEL: Record<DensityIntensity, string> = {
  off: "Activity off",
  subtle: "Activity",
  bold: "Activity bold",
};

const INTENSITY_HINT: Record<DensityIntensity, string> = {
  off: "Activity halos hidden — click to enable",
  subtle: "Subtle activity halos — click to brighten",
  bold: "Bold activity halos — click to hide",
};

/** Three-dot intensity indicator inside the button — visualizes off/subtle/bold. */
function IntensityPips({ intensity }: { intensity: DensityIntensity }) {
  const filled = intensity === "off" ? 0 : intensity === "subtle" ? 1 : 2;
  return (
    <span className="inline-flex flex-row items-center gap-[3px] mr-1">
      {[0, 1].map((i) => (
        <span
          key={i}
          className="block rounded-full"
          style={{
            width: 5,
            height: 5,
            background:
              i < filled
                ? "currentColor"
                : "rgb(var(--color-text) / 0.25)",
          }}
        />
      ))}
    </span>
  );
}

export function UsageDensityChrome({
  intensity,
  onCycleIntensity,
  window: densityWindow,
  onWindowChange,
  compare,
  onCompareChange,
  animate,
  onAnimateChange,
  connectionsEnabled,
  onConnectionsToggle,
}: UsageDensityChromeProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Click-outside to close the advanced popover. Skipped when closed for
  // free, so the listener cost only applies while the popover is mounted.
  useEffect(() => {
    if (!advancedOpen) return;
    const handler = (e: MouseEvent) => {
      const el = popoverRef.current;
      if (el && !el.contains(e.target as Node)) {
        setAdvancedOpen(false);
      }
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [advancedOpen]);

  const isActive = intensity !== "off";
  const activityClass = isActive
    ? "bg-accent/15 border-accent/60 text-accent"
    : "bg-surface-raised/85 border-surface-border text-text-dim hover:text-text";
  const linesClass = connectionsEnabled
    ? "bg-accent/15 border-accent/60 text-accent"
    : "bg-surface-raised/85 border-surface-border text-text-dim hover:text-text";

  return (
    <div
      className="absolute top-4 right-4 z-[2] flex flex-row items-stretch gap-2"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={onCycleIntensity}
        title={INTENSITY_HINT[intensity]}
        aria-label={INTENSITY_HINT[intensity]}
        className={`flex flex-row items-center gap-0.5 px-2.5 py-1.5 rounded-md backdrop-blur border text-xs cursor-pointer ${activityClass}`}
      >
        <IntensityPips intensity={intensity} />
        <span>{INTENSITY_LABEL[intensity]}</span>
      </button>
      <button
        type="button"
        onClick={onConnectionsToggle}
        aria-pressed={connectionsEnabled}
        title={connectionsEnabled ? "Hide widget→channel lines" : "Show widget→channel lines"}
        className={`flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-md backdrop-blur border text-xs cursor-pointer ${linesClass}`}
      >
        <span className="text-sm leading-none">↬</span>
        <span>Lines</span>
      </button>
      <div className="relative" ref={popoverRef}>
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          aria-expanded={advancedOpen}
          aria-label="Activity options"
          title="Activity options"
          className={`flex flex-row items-center px-2 py-1.5 rounded-md backdrop-blur border text-xs cursor-pointer ${
            advancedOpen
              ? "bg-accent/15 border-accent/60 text-accent"
              : "bg-surface-raised/85 border-surface-border text-text-dim hover:text-text"
          }`}
        >
          <Settings2 size={14} />
        </button>
        {advancedOpen && (
          <div className="absolute right-0 top-[calc(100%+6px)] flex flex-col gap-2 px-3 py-2.5 rounded-md bg-surface-raised/95 backdrop-blur border border-surface-border text-xs text-text-dim min-w-[220px] shadow-lg">
            <div className="flex flex-row items-center justify-between gap-2">
              <span className="text-[10px] uppercase tracking-wider">Window</span>
              <div className="flex flex-row items-center rounded border border-surface-border overflow-hidden">
                {WINDOWS.map((w) => (
                  <button
                    key={w}
                    type="button"
                    onClick={() => onWindowChange(w)}
                    className={`px-2 py-0.5 text-xs ${
                      densityWindow === w
                        ? "bg-accent/20 text-accent"
                        : "text-text-dim hover:bg-surface-hover"
                    }`}
                  >
                    {w}
                  </button>
                ))}
              </div>
            </div>
            <label className="flex flex-row items-center justify-between cursor-pointer gap-2">
              <span title="Color halos by current vs. prior-period ratio. Cool = below baseline, warm = above. Useful for spotting spikes.">
                Spike colors
              </span>
              <input
                type="checkbox"
                checked={compare}
                onChange={(e) => onCompareChange(e.target.checked)}
                className="ml-2 accent-accent cursor-pointer"
              />
            </label>
            <label className="flex flex-row items-center justify-between cursor-pointer gap-2">
              <span>Breathe</span>
              <input
                type="checkbox"
                checked={animate}
                onChange={(e) => onAnimateChange(e.target.checked)}
                className="ml-2 accent-accent cursor-pointer"
              />
            </label>
            <div className="text-[10px] leading-snug pt-1 mt-1 border-t border-surface-border/60 text-text-dim/80">
              Halo size + brightness scale with token volume. Click the
              Activity button to cycle off / subtle / bold.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
