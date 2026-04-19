/**
 * MobileOmniSheet — bottom sheet overlay for OmniPanel on mobile.
 *
 * Two snap points only: tall (88% of viewport) and dismissed. The mushy
 * middle resting state is gone. Default opens tall.
 *
 * Tabs are a segmented pill control (not an underline) so the surface
 * reads as a sheet with switchable sections. Last-selected tab is
 * persisted to localStorage so returning to the sheet feels sticky.
 * Default when unset = Widgets (the channel dashboard's rail), not Files.
 *
 * Body scroll is locked while open so iOS doesn't leak overscroll bounce
 * into the chat underneath. Safe-area padding at the bottom keeps the
 * last list row clear of the home indicator.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { OmniPanel } from "./OmniPanel";

interface MobileOmniSheetProps {
  open: boolean;
  onClose: () => void;
  channelId: string;
  workspaceId: string | undefined;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onBrowseFiles: () => void;
}

/** Tall snap = top at 12vh → sheet covers ~88% of the viewport. */
const SNAP_TALL_FRAC = 0.12;
/** Velocity (px/ms) needed to dismiss on a flick-down. */
const DISMISS_VELOCITY = 0.5;
/** Distance in px past which a slow drag-down dismisses. */
const DISMISS_DISTANCE = 120;

export function MobileOmniSheet({
  open,
  onClose,
  channelId,
  workspaceId,
  activeFile,
  onSelectFile,
  onBrowseFiles,
}: MobileOmniSheetProps) {
  const t = useThemeTokens();
  const [dragging, setDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);
  const dragStartY = useRef(0);
  const dragStartTime = useRef(0);

  // Lock body scroll while the sheet is open. Restore original value on
  // close / unmount so we don't stomp on whatever the page had set.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    setDragging(true);
    dragStartY.current = e.touches[0].clientY;
    dragStartTime.current = Date.now();
    setDragOffset(0);
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!dragging) return;
    const delta = e.touches[0].clientY - dragStartY.current;
    // Clamp upward drag to 0 — the sheet is already at its tall snap, no
    // taller snap exists.
    setDragOffset(delta > 0 ? delta : 0);
  }, [dragging]);

  const handleTouchEnd = useCallback(() => {
    if (!dragging) return;
    setDragging(false);
    const elapsed = Math.max(Date.now() - dragStartTime.current, 1);
    const velocity = dragOffset / elapsed;
    if (velocity > DISMISS_VELOCITY || dragOffset > DISMISS_DISTANCE) {
      onClose();
    }
    setDragOffset(0);
  }, [dragging, dragOffset, onClose]);

  if (!open) return null;

  const viewportH = typeof window !== "undefined" ? window.innerHeight : 800;
  const sheetTop = SNAP_TALL_FRAC * viewportH + (dragging ? dragOffset : 0);

  return (
    <>
      <div
        className="fixed inset-0 z-40 transition-opacity duration-200"
        style={{ backgroundColor: "rgba(0,0,0,0.45)" }}
        onClick={onClose}
        aria-hidden
      />

      <div
        className="fixed left-0 right-0 bottom-0 z-50 flex flex-col rounded-t-2xl overflow-hidden"
        style={{
          top: sheetTop,
          backgroundColor: t.surfaceRaised,
          transition: dragging ? "none" : "top 280ms cubic-bezier(0.32, 0.72, 0, 1)",
          touchAction: "none",
          boxShadow: "0 -8px 24px rgba(0,0,0,0.25)",
        }}
        role="dialog"
        aria-label="Channel side panel"
      >
        {/* Drag handle — generous hit area above the visible pill. */}
        <div
          className="flex items-center justify-center cursor-grab active:cursor-grabbing"
          style={{ paddingTop: 10, paddingBottom: 8, minHeight: 28 }}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        >
          <div
            className="w-10 h-1.5 rounded-full"
            style={{ backgroundColor: `${t.textMuted}55` }}
          />
        </div>

        {/* OmniPanel content — mobileTabs mode supplies the segmented control. */}
        <div
          className="flex-1 min-h-0 flex flex-col"
          style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
        >
          <OmniPanel
            channelId={channelId}
            workspaceId={workspaceId}
            activeFile={activeFile}
            onSelectFile={onSelectFile}
            onBrowseFiles={onBrowseFiles}
            onClose={onClose}
            fullWidth
            mobileTabs
          />
        </div>
      </div>
    </>
  );
}
