import { Minimize2 } from "lucide-react";

interface Props {
  /** When true, fades the chip to a low opacity so it doesn't distract on an
   *  idle kiosk display. Hover still brings it back to full opacity, and any
   *  pointer move inside the hook flips `idle` back off. */
  idle: boolean;
  onExit: () => void;
}

/** Floating exit affordance for kiosk dashboards. Top-right, z-50 so it sits
 *  above the iframe renderers. Intentionally NOT part of the grid flow —
 *  kiosk consumers render it as a sibling of the dashboard content. */
export function KioskExitChip({ idle, onExit }: Props) {
  return (
    <button
      type="button"
      onClick={onExit}
      aria-label="Exit kiosk mode"
      title="Exit kiosk (Esc)"
      className={
        "fixed top-3 right-3 z-50 inline-flex items-center gap-1.5 "
        + "rounded-full border border-surface-border bg-surface-raised/90 backdrop-blur "
        + "px-3 py-1.5 text-[12px] font-medium text-text-muted "
        + "shadow-md hover:bg-surface-overlay hover:text-text "
        + "transition-opacity duration-500 "
        + (idle ? "opacity-20 hover:!opacity-100" : "opacity-90")
      }
    >
      <Minimize2 size={13} />
      <span>Exit kiosk</span>
    </button>
  );
}
