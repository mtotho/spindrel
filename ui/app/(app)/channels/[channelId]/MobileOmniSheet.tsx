/**
 * MobileOmniSheet — bottom sheet overlay for OmniPanel on mobile.
 *
 * Slides up from bottom, half-screen by default.
 * Drag handle at top to dismiss or expand.
 * Backdrop scrim dismisses on tap.
 */
import { useCallback, useRef, useState, useEffect } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { OmniPanel } from "./OmniPanel";

interface MobileOmniSheetProps {
  open: boolean;
  onClose: () => void;
  channelId: string;
  botId: string | undefined;
  workspaceId: string | undefined;
  channelDisplayName?: string | null;
  channelWorkspaceEnabled: boolean;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
}

const SNAP_HALF = 0.5;   // 50% of viewport
const SNAP_FULL = 0.15;  // 15% from top
const SNAP_DISMISSED = 1; // fully off-screen
const VELOCITY_THRESHOLD = 0.5; // px/ms to trigger snap

export function MobileOmniSheet({
  open,
  onClose,
  channelId,
  botId,
  workspaceId,
  channelDisplayName,
  channelWorkspaceEnabled,
  activeFile,
  onSelectFile,
}: MobileOmniSheetProps) {
  const t = useThemeTokens();
  const [snapPoint, setSnapPoint] = useState(SNAP_HALF);
  const [dragging, setDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);
  const dragStartY = useRef(0);
  const dragStartTime = useRef(0);
  const lastY = useRef(0);

  // Reset to half when opened
  useEffect(() => {
    if (open) setSnapPoint(SNAP_HALF);
  }, [open]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    setDragging(true);
    dragStartY.current = e.touches[0].clientY;
    dragStartTime.current = Date.now();
    lastY.current = e.touches[0].clientY;
    setDragOffset(0);
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!dragging) return;
    const currentY = e.touches[0].clientY;
    const delta = currentY - dragStartY.current;
    lastY.current = currentY;
    setDragOffset(delta);
  }, [dragging]);

  const handleTouchEnd = useCallback(() => {
    if (!dragging) return;
    setDragging(false);

    const elapsed = Date.now() - dragStartTime.current;
    const velocity = dragOffset / Math.max(elapsed, 1);
    const viewportH = window.innerHeight;
    const currentTop = snapPoint * viewportH + dragOffset;
    const currentFrac = currentTop / viewportH;

    // Fast flick down → dismiss
    if (velocity > VELOCITY_THRESHOLD) {
      onClose();
      setDragOffset(0);
      return;
    }
    // Fast flick up → full
    if (velocity < -VELOCITY_THRESHOLD) {
      setSnapPoint(SNAP_FULL);
      setDragOffset(0);
      return;
    }

    // Snap to nearest point
    const points = [SNAP_FULL, SNAP_HALF, SNAP_DISMISSED];
    let closest = SNAP_HALF;
    let minDist = Infinity;
    for (const p of points) {
      const dist = Math.abs(currentFrac - p);
      if (dist < minDist) {
        minDist = dist;
        closest = p;
      }
    }

    if (closest === SNAP_DISMISSED) {
      onClose();
    } else {
      setSnapPoint(closest);
    }
    setDragOffset(0);
  }, [dragging, dragOffset, snapPoint, onClose]);

  if (!open) return null;

  const viewportH = typeof window !== "undefined" ? window.innerHeight : 800;
  const sheetTop = dragging
    ? snapPoint * viewportH + dragOffset
    : snapPoint * viewportH;

  return (
    <>
      {/* Backdrop scrim */}
      <div
        className="fixed inset-0 z-40 transition-opacity duration-200"
        style={{ backgroundColor: "rgba(0,0,0,0.4)" }}
        onClick={onClose}
      />

      {/* Sheet */}
      <div
        className="fixed left-0 right-0 bottom-0 z-50 flex flex-col rounded-t-2xl overflow-hidden"
        style={{
          top: Math.max(sheetTop, SNAP_FULL * viewportH),
          backgroundColor: t.surfaceRaised,
          transition: dragging ? "none" : "top 300ms cubic-bezier(0.32, 0.72, 0, 1)",
          touchAction: "none",
        }}
      >
        {/* Drag handle */}
        <div
          className="flex items-center justify-center pt-2 pb-1 cursor-grab active:cursor-grabbing"
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        >
          <div
            className="w-10 h-1 rounded-full"
            style={{ backgroundColor: `${t.textMuted}33` }}
          />
        </div>

        {/* OmniPanel content */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <OmniPanel
            channelId={channelId}
            botId={botId}
            workspaceId={workspaceId}
            channelDisplayName={channelDisplayName}
            channelWorkspaceEnabled={channelWorkspaceEnabled}
            activeFile={activeFile}
            onSelectFile={onSelectFile}
            onClose={onClose}
            fullWidth
          />
        </div>
      </div>
    </>
  );
}
