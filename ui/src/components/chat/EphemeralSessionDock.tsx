import { useEffect } from "react";
import { MessageSquare } from "lucide-react";

interface EphemeralSessionDockProps {
  open: boolean;
  /** Controlled expansion — FAB vs panel. Lifted so the controller's
      header X button can collapse back to FAB. */
  expanded: boolean;
  onExpandedChange: (next: boolean) => void;
  title: string;
  children: React.ReactNode;
}

/**
 * Bottom-right FAB dock shell for ephemeral sessions.
 *
 * open=false → hidden entirely.
 * open=true  → FAB (``expanded=false``) or expanded panel (``expanded=true``).
 * The controller owns ``expanded`` so its header controls can collapse.
 */
export function EphemeralSessionDock({ open, expanded, onExpandedChange, title, children }: EphemeralSessionDockProps) {
  useEffect(() => {
    if (!expanded) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onExpandedChange(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [expanded, onExpandedChange]);

  useEffect(() => {
    if (!open && expanded) onExpandedChange(false);
  }, [open, expanded, onExpandedChange]);

  if (!open) return null;

  if (!expanded) {
    return (
      <button
        onClick={() => onExpandedChange(true)}
        aria-label={`Open ${title}`}
        className="fixed bottom-4 right-4 z-[9990] w-14 h-14 rounded-full
                   bg-accent text-white shadow-[0_4px_16px_rgba(0,0,0,0.35)]
                   flex items-center justify-center
                   hover:brightness-110 active:scale-95 transition-all"
      >
        <MessageSquare size={22} />
      </button>
    );
  }

  return (
    <>
      {/* Invisible scrim — click outside collapses to FAB */}
      <div
        className="fixed inset-0 z-[9990]"
        onClick={() => onExpandedChange(false)}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="fixed z-[9991] flex flex-col overflow-hidden
                   bg-surface-raised border border-surface-border
                   shadow-[0_8px_32px_rgba(0,0,0,0.4)]
                   /* mobile: full bottom sheet */
                   inset-x-0 bottom-0 rounded-t-xl h-[80vh]
                   /* desktop: anchored bottom-right */
                   md:inset-auto md:bottom-4 md:right-4
                   md:w-[380px] md:h-[560px]
                   md:rounded-xl"
      >
        {children}
      </div>
    </>
  );
}
