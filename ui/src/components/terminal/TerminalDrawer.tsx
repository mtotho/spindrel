import { Suspense, lazy, useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { Spinner } from "@/src/components/shared/Spinner";

const TerminalPanel = lazy(() =>
  import("@/src/components/terminal/TerminalPanel").then((m) => ({ default: m.TerminalPanel })),
);

interface TerminalDrawerProps {
  open: boolean;
  onClose: () => void;
  /** Command piped into the shell on startup. */
  seedCommand?: string;
  /** Working directory to start in. */
  cwd?: string;
  /** Title shown in the drawer header. */
  title?: string;
  /** Subtitle shown below the title — typically the seed command or cwd. */
  subtitle?: string;
  /** Width in px. Default 720. */
  width?: number;
}

/**
 * Right-anchored slide-in drawer that hosts a TerminalPanel. Closing the
 * drawer kills the PTY via the panel's unmount path.
 */
export function TerminalDrawer({
  open,
  onClose,
  seedCommand,
  cwd,
  title = "Terminal",
  subtitle,
  width = 720,
}: TerminalDrawerProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;
  if (typeof document === "undefined") return null;

  return createPortal(
    <>
      <div
        onClick={onClose}
        className="fixed inset-0 z-[10020] bg-black/60"
        aria-hidden
      />
      <aside
        className="fixed inset-y-0 right-0 z-[10021] flex flex-col border-l border-surface-border bg-surface-raised shadow-2xl"
        style={{ width: Math.min(width, 0.92 * window.innerWidth) }}
        role="dialog"
        aria-label={title}
      >
        <header className="flex shrink-0 items-start justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <div className="text-[14px] font-semibold text-text">{title}</div>
            {subtitle && (
              <div className="mt-0.5 truncate font-mono text-[11px] text-text-dim">{subtitle}</div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-text-dim hover:bg-surface-overlay/40 hover:text-text"
            aria-label="Close terminal"
          >
            <X size={16} />
          </button>
        </header>
        <div className="relative flex min-h-0 flex-1 flex-col">
          <Suspense
            fallback={
              <div className="flex flex-1 items-center justify-center bg-[#0a0d12]">
                <Spinner />
              </div>
            }
          >
            <TerminalPanel seedCommand={seedCommand} cwd={cwd} />
          </Suspense>
        </div>
      </aside>
    </>,
    document.body,
  );
}

export default TerminalDrawer;
