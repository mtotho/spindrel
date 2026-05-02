/**
 * MobileNotesSheet — slide-in overlay around NotesTabPanel for mobile.
 *
 * Mirrors MobileFileViewerSlide's structure: chat stays mounted underneath,
 * notes slide in from the right with a 220ms iOS-spring transform. Edge-swipe
 * from the left dismisses. Notes lives here on mobile because the channel
 * drawer's tab strip is reserved for Sessions / Widgets / Files.
 */
import { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { ChevronLeft, NotebookText } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { NotesTabPanel } from "./NotesTabPanel";

interface MobileNotesSheetProps {
  open: boolean;
  channelId: string;
  botId?: string;
  channelLabel?: string | null;
  onClose: () => void;
  onSelectFile?: (path: string, options?: { split?: boolean }) => void;
}

const SLIDE_MS = 220;
const DISMISS_DISTANCE = 60;
const DISMISS_VELOCITY = 0.5;
const EDGE_SLOP = 16;

export function MobileNotesSheet({
  open,
  channelId,
  botId,
  channelLabel,
  onClose,
  onSelectFile,
}: MobileNotesSheetProps) {
  const t = useThemeTokens();
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(false);
  const exitTimer = useRef<number | null>(null);

  useEffect(() => {
    if (open) {
      if (exitTimer.current) {
        window.clearTimeout(exitTimer.current);
        exitTimer.current = null;
      }
      setMounted(true);
      const id = window.requestAnimationFrame(() => setShown(true));
      return () => window.cancelAnimationFrame(id);
    }
    setShown(false);
    exitTimer.current = window.setTimeout(() => {
      setMounted(false);
      exitTimer.current = null;
    }, SLIDE_MS);
    return () => {
      if (exitTimer.current) {
        window.clearTimeout(exitTimer.current);
        exitTimer.current = null;
      }
    };
  }, [open]);

  useEffect(() => {
    if (!shown) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [shown]);

  const dragStartX = useRef<number | null>(null);
  const dragStartT = useRef<number>(0);
  const [dragX, setDragX] = useState(0);

  const handleTouchStart = (e: React.TouchEvent) => {
    if (!shown) return;
    const t0 = e.touches[0];
    if (t0.clientX <= EDGE_SLOP) {
      dragStartX.current = t0.clientX;
      dragStartT.current = Date.now();
      setDragX(0);
    }
  };
  const handleTouchMove = (e: React.TouchEvent) => {
    if (dragStartX.current == null) return;
    const dx = e.touches[0].clientX - dragStartX.current;
    setDragX(dx > 0 ? dx : 0);
  };
  const handleTouchEnd = () => {
    if (dragStartX.current == null) return;
    const elapsed = Math.max(Date.now() - dragStartT.current, 1);
    const v = dragX / elapsed;
    const dismiss = dragX > DISMISS_DISTANCE || v > DISMISS_VELOCITY;
    dragStartX.current = null;
    setDragX(0);
    if (dismiss) onClose();
  };

  if (!mounted || typeof document === "undefined") return null;

  const tx = dragStartX.current != null
    ? dragX
    : shown
      ? 0
      : typeof window !== "undefined" ? window.innerWidth : 0;

  return ReactDOM.createPortal(
    <div
      role="dialog"
      aria-label="Channel notes"
      className="fixed inset-0 flex flex-col"
      style={{
        backgroundColor: t.surface,
        zIndex: 10031,
        paddingTop: "env(safe-area-inset-top)",
        transform: `translateX(${tx}px)`,
        transition:
          dragStartX.current != null
            ? "none"
            : `transform ${SLIDE_MS}ms cubic-bezier(0.32, 0.72, 0, 1)`,
        willChange: "transform",
      }}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={handleTouchEnd}
    >
      <div
        className="flex items-center gap-2 px-2 py-2"
        style={{ backgroundColor: t.surfaceRaised }}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close notes"
          className="flex h-9 w-9 items-center justify-center rounded-md"
          style={{ color: t.textDim }}
        >
          <ChevronLeft size={20} />
        </button>
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <NotebookText size={15} style={{ color: t.text }} />
          <div className="min-w-0">
            <div
              className="truncate text-[13px] font-semibold"
              style={{ color: t.text }}
            >
              Notes
            </div>
            {channelLabel && (
              <div
                className="truncate text-[11px]"
                style={{ color: t.textDim }}
              >
                {channelLabel}
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        <NotesTabPanel
          channelId={channelId}
          botId={botId}
          onSelectFile={onSelectFile}
        />
      </div>
    </div>,
    document.body,
  );
}
