import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { getChatShortcutLabel } from "@/src/components/chat/chatKeyboard";

interface ChannelKeyboardShortcutsOverlayProps {
  open: boolean;
  onClose: () => void;
}

const SHORTCUT_GROUPS = [
  {
    label: "Navigation",
    rows: [
      ["commandPalette", "Search and run commands"],
      ["showKeyboardHelp", "Show keyboard shortcuts"],
      ["openSlashCommands", "Focus composer commands"],
    ],
  },
  {
    label: "Sessions",
    rows: [
      ["switchSessions", "Switch sessions"],
      ["Enter", "Open selected session"],
      ["Cmd/Ctrl+Enter", "Open selected session as split"],
      ["Esc", "Close the picker"],
    ],
  },
  {
    label: "Tabs",
    rows: [
      ["← / →", "Move focus across tabs"],
      ["Home / End", "First or last tab"],
      ["Enter / Space", "Activate focused tab"],
      ["closeActiveTab", "Close active tab"],
      ["Delete", "Close focused tab"],
      ["Shift+F10", "Open tab actions"],
    ],
  },
  {
    label: "Chat input",
    rows: [
      ["Enter", "Send on desktop"],
      ["Shift+Enter", "New line"],
      ["Cmd/Ctrl+Enter", "Send"],
      ["Esc", "Clear draft, close menu, or stop active state"],
      ["↑", "Recall queued draft when empty"],
    ],
  },
  {
    label: "Workbench",
    rows: [
      ["toggleWorkbench", "Show or hide workbench"],
      ["browseFiles", "Browse files"],
      ["focusLayout", "Focus chat panes"],
    ],
  },
] as const;

function formatShortcut(value: string) {
  if (value in shortcutIdSet) {
    return getChatShortcutLabel(value as keyof typeof shortcutIdSet);
  }
  return value;
}

const shortcutIdSet = {
  browseFiles: true,
  closeActiveTab: true,
  commandPalette: true,
  focusLayout: true,
  openSlashCommands: true,
  showKeyboardHelp: true,
  switchSessions: true,
  toggleWorkbench: true,
};

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-surface-border bg-surface-overlay/60 px-1.5 py-0.5 font-[inherit] text-[10px] leading-none text-text-muted">
      {children}
    </kbd>
  );
}

export function ChannelKeyboardShortcutsOverlay({
  open,
  onClose,
}: ChannelKeyboardShortcutsOverlayProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose, open]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <>
      <div
        className="fixed inset-0 z-[10080] bg-black/45 backdrop-blur-[2px]"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        className="fixed inset-x-0 bottom-0 z-[10081] max-h-[86dvh] overflow-hidden rounded-t-md bg-surface-raised text-text shadow-[0_-16px_48px_rgba(0,0,0,0.34)] sm:bottom-auto sm:left-1/2 sm:top-[12vh] sm:w-[620px] sm:max-w-[calc(100vw-2rem)] sm:-translate-x-1/2 sm:rounded-md sm:shadow-[0_18px_52px_rgba(0,0,0,0.32)]"
      >
        <div className="flex items-start justify-between gap-3 px-4 py-3">
          <div>
            <div className="text-sm font-semibold">Keyboard shortcuts</div>
            <div className="mt-0.5 text-xs text-text-dim">
              Chat navigation and session controls
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay hover:text-text"
            aria-label="Close keyboard shortcuts"
          >
            <X size={16} />
          </button>
        </div>
        <div className="grid max-h-[calc(86dvh-72px)] gap-4 overflow-y-auto px-4 pb-4 sm:grid-cols-2">
          {SHORTCUT_GROUPS.map((group) => (
            <section key={group.label} className="min-w-0">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
                {group.label}
              </div>
              <div className="space-y-1">
                {group.rows.map(([shortcut, label]) => (
                  <div
                    key={`${group.label}:${shortcut}`}
                    className="flex items-center justify-between gap-3 rounded-md bg-surface-overlay/35 px-2.5 py-2"
                  >
                    <span className="min-w-0 text-xs text-text-muted">
                      {label}
                    </span>
                    <Kbd>{formatShortcut(shortcut)}</Kbd>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </>,
    document.body,
  );
}
