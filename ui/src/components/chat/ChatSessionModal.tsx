import { useEffect } from "react";
import { createPortal } from "react-dom";

interface ChatSessionModalProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  /** Accessible dialog label shown to screen readers. */
  title?: string;
}

/** Generic portal modal shell: centered on desktop, full-screen on mobile.
    Shared by PipelineRunModal and ChatSession's modal shape. */
export function ChatSessionModal({ open, onClose, children, title }: ChatSessionModalProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="fixed inset-0 bg-black/55 z-[10040]"
        aria-hidden="true"
      />
      {/* Modal card */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="fixed z-[10041] overflow-hidden
                   inset-0 md:inset-auto md:top-1/2 md:left-1/2
                   md:-translate-x-1/2 md:-translate-y-1/2
                   md:w-[92vw] md:max-w-[820px] md:h-[85vh]
                   bg-surface-raised md:border md:border-surface-border
                   md:rounded-xl md:shadow-[0_16px_48px_rgba(0,0,0,0.35)]
                   flex flex-col"
      >
        {children}
      </div>
    </>,
    document.body,
  );
}
