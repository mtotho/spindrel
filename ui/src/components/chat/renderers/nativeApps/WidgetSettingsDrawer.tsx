import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

interface WidgetSettingsDrawerProps {
  open: boolean;
  onClose: () => void;
  /** Optional eyebrow above the title (e.g. "Ecosystem"). */
  kicker?: ReactNode;
  /** Main heading (e.g. "Setup"). */
  title: ReactNode;
  /** Optional small status chip on the right of the header. */
  statusChip?: ReactNode;
  /** Drawer body — typically a stack of `<WidgetSettingsSection>`s. */
  children: ReactNode;
  /** Backdrop click closes by default; pass `false` to suppress. */
  dismissOnBackdrop?: boolean;
  /** Pixel width of the drawer. Default 300px. */
  width?: number;
}

/**
 * Generic right-edge slide-in drawer for native-widget configuration.
 *
 * Native widgets (games, but also any widget that wants config tucked away)
 * mount this from inside their stage area. The drawer is positioned absolute
 * relative to the nearest positioned ancestor — typically the widget body —
 * so it slides in over the widget without escaping its bounds.
 */
export function WidgetSettingsDrawer({
  open,
  onClose,
  kicker,
  title,
  statusChip,
  children,
  dismissOnBackdrop = true,
  width = 300,
}: WidgetSettingsDrawerProps) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  if (typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-[1000]">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-[1px]"
        onClick={dismissOnBackdrop ? onClose : undefined}
      />
      <div
        className="absolute top-0 right-0 bottom-0 max-w-[92vw] bg-surface-raised border-l border-surface-border flex flex-col overflow-hidden text-text shadow-2xl"
        style={{ width }}
      >
        <div className="flex flex-row items-center gap-2 px-3 py-2 border-b border-surface-border shrink-0">
          <div className="flex flex-col leading-tight">
            {kicker && (
              <span className="text-[10px] uppercase tracking-wider text-text-dim">
                {kicker}
              </span>
            )}
            <span className="text-[12px] font-semibold">{title}</span>
          </div>
          <div className="flex-1" />
          {statusChip}
          <button
            type="button"
            onClick={onClose}
            className="text-text-dim hover:text-text"
            title="Close (Esc)"
            aria-label="Close settings"
          >
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 flex flex-col gap-4">
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}

interface WidgetSettingsSectionProps {
  label: ReactNode;
  /** Right-aligned helper text in the section header (e.g. counts). */
  hint?: ReactNode;
  children: ReactNode;
}

export function WidgetSettingsSection({ label, hint, children }: WidgetSettingsSectionProps) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-text-dim">
          {label}
        </span>
        {hint && <span className="text-[10px] text-text-dim">{hint}</span>}
      </div>
      {children}
    </section>
  );
}
