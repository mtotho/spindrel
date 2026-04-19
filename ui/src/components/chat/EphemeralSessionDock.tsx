import { useEffect, useState } from "react";
import { MessageSquare, X } from "lucide-react";

interface EphemeralSessionDockProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}

/**
 * Bottom-right FAB dock shell for ephemeral sessions.
 *
 * open=false → hidden entirely.
 * open=true  → FAB (collapsed) or expanded panel (user-controlled).
 * onClose collapses to FAB; parent sets open=false to hide entirely.
 */
export function EphemeralSessionDock({ open, onClose, title, children }: EphemeralSessionDockProps) {
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [expanded]);

  // Collapse when parent hides the dock
  useEffect(() => {
    if (!open) setExpanded(false);
  }, [open]);

  if (!open) return null;

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
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
      {/* Invisible scrim — click outside collapses */}
      <div
        className="fixed inset-0 z-[9990]"
        onClick={() => setExpanded(false)}
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
        {/* Close button overlaid on top-right so children (header) own the rest */}
        <button
          onClick={() => { setExpanded(false); onClose(); }}
          aria-label="Close chat"
          className="absolute top-2 right-2 z-10 p-1.5 rounded
                     text-text-dim hover:text-text hover:bg-white/5
                     transition-colors"
        >
          <X size={14} />
        </button>

        {children}
      </div>
    </>
  );
}
