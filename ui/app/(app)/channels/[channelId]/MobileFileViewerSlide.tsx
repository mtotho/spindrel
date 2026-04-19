/**
 * MobileFileViewerSlide — slide-in overlay wrapper around ChannelFileViewer
 * for mobile chat screens.
 *
 * Replaces the old "ternary swap" pattern (chat fully unmounted, viewer takes
 * over) with a layered overlay: chat stays mounted underneath, viewer slides
 * in from the right with a 220ms iOS-spring transform. Back returns to the
 * exact same chat scroll position — no remount, no fetch flash.
 *
 * Edge-swipe-from-left dismisses (touch-start within 16px of the left edge,
 * horizontal drag past 60px or fast flick).
 */
import { useEffect, useRef, useState } from "react";
import { ChannelFileViewer } from "./ChannelFileViewer";

interface MobileFileViewerSlideProps {
  /** Whether the viewer should be visible. When this flips false, the
   *  wrapper animates out then unmounts the inner viewer after 220ms. */
  open: boolean;
  channelId: string;
  workspaceId?: string;
  filePath: string | null;
  channelName: string | null;
  channelPrivate: boolean;
  onBack: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}

const SLIDE_MS = 220;
/** Distance in px past which an edge-swipe dismisses. */
const DISMISS_DISTANCE = 60;
/** Velocity (px/ms) needed to dismiss on a flick. */
const DISMISS_VELOCITY = 0.5;
/** Touch-start must land within this many px of the left edge to count. */
const EDGE_SLOP = 16;

export function MobileFileViewerSlide({
  open, channelId, workspaceId, filePath, channelName, channelPrivate,
  onBack, onDirtyChange,
}: MobileFileViewerSlideProps) {
  // Track whether we should keep the viewer mounted (for the exit animation).
  const [mounted, setMounted] = useState(open);
  // Drives the translateX transform — true = on-screen.
  const [shown, setShown] = useState(false);
  const exitTimer = useRef<number | null>(null);

  useEffect(() => {
    if (open) {
      // Mount immediately; flip `shown` on the next frame so the transform
      // animates from off-screen → on-screen instead of skipping the entry.
      if (exitTimer.current) { window.clearTimeout(exitTimer.current); exitTimer.current = null; }
      setMounted(true);
      const id = window.requestAnimationFrame(() => setShown(true));
      return () => window.cancelAnimationFrame(id);
    } else {
      setShown(false);
      // Unmount after the exit animation finishes.
      exitTimer.current = window.setTimeout(() => {
        setMounted(false);
        exitTimer.current = null;
      }, SLIDE_MS);
      return () => {
        if (exitTimer.current) { window.clearTimeout(exitTimer.current); exitTimer.current = null; }
      };
    }
  }, [open]);

  // Edge-swipe-from-left dismissal.
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
    if (dismiss) onBack();
  };

  if (!mounted || !filePath) return null;

  // While dragging, follow the finger. While not dragging, snap to shown/hidden.
  const tx = dragStartX.current != null ? dragX : (shown ? 0 : window.innerWidth);

  return (
    <div
      className="absolute inset-0 z-30 flex flex-col"
      style={{
        transform: `translateX(${tx}px)`,
        transition: dragStartX.current != null ? "none" : `transform ${SLIDE_MS}ms cubic-bezier(0.32, 0.72, 0, 1)`,
        willChange: "transform",
      }}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={handleTouchEnd}
    >
      <ChannelFileViewer
        channelId={channelId}
        workspaceId={workspaceId}
        filePath={filePath}
        onBack={onBack}
        onDirtyChange={onDirtyChange}
        channelDisplayName={channelName}
        channelPrivate={channelPrivate}
      />
    </div>
  );
}
