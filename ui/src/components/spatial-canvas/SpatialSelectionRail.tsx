import type { MouseEvent, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export interface SpatialSelectionAction {
  id: string;
  label: string;
  icon: LucideIcon;
  onSelect: (event: MouseEvent<HTMLButtonElement>) => void;
  disabled?: boolean;
}

interface SpatialSelectionRailProps {
  x: number;
  y: number;
  label: string;
  meta?: string;
  actions: SpatialSelectionAction[];
  leading?: ReactNode;
}

export function SpatialSelectionRail({
  x,
  y,
  label,
  meta,
  actions,
  leading,
}: SpatialSelectionRailProps) {
  const clampedX = Math.max(72, Math.min(x, window.innerWidth - 72));
  const clampedY = Math.max(88, Math.min(y, window.innerHeight - 96));

  return (
    <div
      className="pointer-events-auto absolute z-[7000] -translate-x-1/2 -translate-y-full"
      style={{ left: clampedX, top: clampedY }}
      onPointerDown={(e) => e.stopPropagation()}
      onWheel={(e) => e.stopPropagation()}
    >
      <div className="mb-3 flex min-w-[220px] max-w-[320px] items-center gap-2 rounded-lg border border-surface-border/80 bg-surface-raised/95 px-2.5 py-2 shadow-[0_14px_36px_rgb(0_0_0/0.32)] backdrop-blur-md">
        {leading && (
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-overlay text-accent">
            {leading}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold leading-tight text-text">{label}</div>
          {meta && (
            <div className="mt-0.5 truncate text-[11px] font-medium uppercase tracking-[0.12em] text-text-muted">
              {meta}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {actions.map((action) => {
            const Icon = action.icon;
            return (
              <button
                key={action.id}
                type="button"
                disabled={action.disabled}
                title={action.label}
                aria-label={action.label}
                onClick={action.onSelect}
                className="flex h-8 w-8 items-center justify-center rounded-md border border-transparent text-text-muted transition-colors hover:border-surface-border hover:bg-surface-overlay hover:text-text disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:border-transparent disabled:hover:bg-transparent disabled:hover:text-text-muted"
              >
                <Icon className="h-4 w-4" aria-hidden />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
