import type { DensityMode, DensityWindow } from "./UsageDensityLayer";

interface UsageDensityChromeProps {
  enabled: boolean;
  onToggle: () => void;
  window: DensityWindow;
  onWindowChange: (w: DensityWindow) => void;
  mode: DensityMode;
  onModeChange: (m: DensityMode) => void;
  animate: boolean;
  onAnimateChange: (a: boolean) => void;
  connectionsEnabled: boolean;
  onConnectionsToggle: () => void;
}

const WINDOWS: DensityWindow[] = ["24h", "7d", "30d"];

export function UsageDensityChrome({
  enabled,
  onToggle,
  window,
  onWindowChange,
  mode,
  onModeChange,
  animate,
  onAnimateChange,
  connectionsEnabled,
  onConnectionsToggle,
}: UsageDensityChromeProps) {
  return (
    <div
      className="absolute top-4 right-4 z-[2] flex flex-col items-stretch gap-2 max-w-[260px]"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div className="flex flex-row items-center gap-2">
        <button
          type="button"
          onClick={onToggle}
          aria-pressed={enabled}
          title={enabled ? "Hide token-usage halos" : "Show token-usage halos"}
          className={`flex-1 flex flex-row items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md backdrop-blur border text-xs cursor-pointer ${
            enabled
              ? "bg-accent/15 border-accent/60 text-accent"
              : "bg-surface-raised/85 border-surface-border text-text-dim hover:text-text"
          }`}
        >
          <span className="text-sm leading-none">◉</span>
          <span>Token density</span>
        </button>
        <button
          type="button"
          onClick={onConnectionsToggle}
          aria-pressed={connectionsEnabled}
          title={connectionsEnabled ? "Hide widget→channel lines" : "Show widget→channel lines"}
          className={`flex flex-row items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md backdrop-blur border text-xs cursor-pointer ${
            connectionsEnabled
              ? "bg-accent/15 border-accent/60 text-accent"
              : "bg-surface-raised/85 border-surface-border text-text-dim hover:text-text"
          }`}
        >
          <span className="text-sm leading-none">↬</span>
          <span>Lines</span>
        </button>
      </div>
      {enabled && (
        <div className="flex flex-col gap-1.5 px-3 py-2 rounded-md bg-surface-raised/85 backdrop-blur border border-surface-border text-xs text-text-dim">
          <div className="flex flex-row items-center justify-between gap-2">
            <span className="text-[10px] uppercase tracking-wider">Window</span>
            <div className="flex flex-row items-center rounded border border-surface-border overflow-hidden">
              {WINDOWS.map((w) => (
                <button
                  key={w}
                  type="button"
                  onClick={() => onWindowChange(w)}
                  className={`px-2 py-0.5 text-xs ${
                    window === w
                      ? "bg-accent/20 text-accent"
                      : "text-text-dim hover:bg-surface-hover"
                  }`}
                >
                  {w}
                </button>
              ))}
            </div>
          </div>
          <label className="flex flex-row items-center justify-between cursor-pointer">
            <span>Deviation only</span>
            <input
              type="checkbox"
              checked={mode === "deviation"}
              onChange={(e) => onModeChange(e.target.checked ? "deviation" : "absolute")}
              className="ml-2 accent-accent cursor-pointer"
            />
          </label>
          <label className="flex flex-row items-center justify-between cursor-pointer">
            <span>Animate</span>
            <input
              type="checkbox"
              checked={animate}
              onChange={(e) => onAnimateChange(e.target.checked)}
              className="ml-2 accent-accent cursor-pointer"
            />
          </label>
        </div>
      )}
    </div>
  );
}
