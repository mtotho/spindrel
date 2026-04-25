import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageSquare, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

interface ChatSessionDockProps {
  open: boolean;
  /** Controlled expansion — FAB vs panel. Lifted so the controller's
      header X button can collapse back to FAB. */
  expanded: boolean;
  onExpandedChange: (next: boolean) => void;
  title: string;
  collapsedTitle?: string;
  collapsedSubtitle?: string | null;
  onCloseCollapsed?: () => void;
  children: React.ReactNode;
  /** When provided, the dock has no FAB lifecycle — dismissal (scrim
   *  click, Escape, mobile swipe-down) calls onDismiss instead of
   *  collapsing to a FAB. Used on the channel screen where the dock is
   *  reachable only from the channel header button. */
  onDismiss?: () => void;
  /** Stable per-surface storage key for persisted desktop dock size. */
  storageKey?: string;
  chatMode?: "default" | "terminal";
}

/** Threshold in px for the mobile swipe-down gesture to dismiss. */
const SWIPE_DOWN_THRESHOLD = 80;
const STORAGE_PREFIX = "spindrel:chat-session-dock:size:";
const DESKTOP_DOCK_DEFAULT = { width: 500, height: 728 };
const DESKTOP_DOCK_MIN = { width: 320, height: 360 };
const DESKTOP_DOCK_MARGIN = 16;

function loadStoredDockSize(storageKey: string | undefined) {
  if (!storageKey || typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { width?: number; height?: number };
    if (
      typeof parsed.width !== "number" ||
      !Number.isFinite(parsed.width) ||
      typeof parsed.height !== "number" ||
      !Number.isFinite(parsed.height)
    ) {
      return null;
    }
    return { width: parsed.width, height: parsed.height };
  } catch {
    return null;
  }
}

function saveDockSize(storageKey: string | undefined, size: { width: number; height: number }) {
  if (!storageKey || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify(size));
  } catch {
    // localStorage may be unavailable.
  }
}

function clampDockSize(
  size: { width: number; height: number },
  viewportWidth: number,
  viewportHeight: number,
) {
  const maxWidth = Math.max(
    DESKTOP_DOCK_MIN.width,
    viewportWidth - DESKTOP_DOCK_MARGIN * 2,
  );
  const maxHeight = Math.max(
    DESKTOP_DOCK_MIN.height,
    viewportHeight - DESKTOP_DOCK_MARGIN * 2,
  );
  return {
    width: Math.min(Math.max(size.width, DESKTOP_DOCK_MIN.width), maxWidth),
    height: Math.min(Math.max(size.height, DESKTOP_DOCK_MIN.height), maxHeight),
  };
}

/**
 * Bottom-right FAB dock shell for ChatSession.
 *
 * open=false → hidden entirely.
 * open=true  → FAB (``expanded=false``) or expanded panel (``expanded=true``).
 * The controller owns ``expanded`` so its header controls can collapse.
 * When ``onDismiss`` is provided, collapsing fires ``onDismiss`` instead
 * of dropping into a FAB (used by the channel-screen scratch/thread
 * docks where there is no FAB entry point).
 */
export function ChatSessionDock({
  open,
  expanded,
  onExpandedChange,
  title,
  collapsedTitle,
  collapsedSubtitle,
  onCloseCollapsed,
  children,
  onDismiss,
  storageKey,
  chatMode = "default",
}: ChatSessionDockProps) {
  const t = useThemeTokens();
  // Entry animation — play once per expansion so the panel slides in from
  // ~the viewport center, selling the "chat just moved here" motion when the
  // user clicked Minimize on the channel screen.
  const [entering, setEntering] = useState(false);
  const prevExpandedRef = useRef(expanded);
  useEffect(() => {
    if (expanded && !prevExpandedRef.current) {
      setEntering(true);
      const timer = window.setTimeout(() => setEntering(false), 300);
      prevExpandedRef.current = expanded;
      return () => window.clearTimeout(timer);
    }
    prevExpandedRef.current = expanded;
  }, [expanded]);

  // A single dismiss path: parent-provided close when onDismiss is given;
  // otherwise collapse to FAB.
  const handleDismiss = useCallback(() => {
    if (onDismiss) onDismiss();
    else onExpandedChange(false);
  }, [onDismiss, onExpandedChange]);

  useEffect(() => {
    if (!expanded) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleDismiss();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [expanded, handleDismiss]);

  useEffect(() => {
    if (!open && expanded) onExpandedChange(false);
  }, [open, expanded, onExpandedChange]);

  // Soft-keyboard handling — on mobile the visual viewport shrinks when
  // the keyboard opens. Without this, an ``h-[80dvh]`` sheet anchored at
  // ``bottom: 0`` extends behind the keyboard and its top edge clips
  // above the visible viewport. We apply a CSS var ``--dock-bottom``
  // equal to the keyboard overlap so the sheet floats above.
  const [keyboardOffset, setKeyboardOffset] = useState(0);
  useEffect(() => {
    if (!expanded) return;
    const vv = (window as any).visualViewport as VisualViewport | undefined;
    if (!vv) return;
    const recompute = () => {
      const overlap = Math.max(
        0,
        window.innerHeight - vv.height - vv.offsetTop,
      );
      setKeyboardOffset(overlap);
    };
    recompute();
    vv.addEventListener("resize", recompute);
    vv.addEventListener("scroll", recompute);
    return () => {
      vv.removeEventListener("resize", recompute);
      vv.removeEventListener("scroll", recompute);
    };
  }, [expanded]);

  // Swipe-down to dismiss on mobile. Tracks the drag on the top drag
  // handle (touchstart/move/end). Release below threshold springs back.
  const panelRef = useRef<HTMLDivElement | null>(null);
  const dragStartYRef = useRef<number | null>(null);
  const [dragY, setDragY] = useState(0);
  const resizeOriginRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    startWidth: number;
    startHeight: number;
  } | null>(null);
  const [dockSize, setDockSize] = useState(() =>
    clampDockSize(
      loadStoredDockSize(storageKey) ?? DESKTOP_DOCK_DEFAULT,
      typeof window === "undefined" ? 1440 : window.innerWidth,
      typeof window === "undefined" ? 900 : window.innerHeight,
    ),
  );
  const dockStyle = useMemo(
    () => ({
      width: `${dockSize.width}px`,
      height: `${dockSize.height}px`,
    }),
    [dockSize.height, dockSize.width],
  );
  const isDesktopViewport = typeof window === "undefined"
    ? true
    : window.innerWidth >= 768;
  const isTerminalMode = chatMode === "terminal";

  useEffect(() => {
    setDockSize((current) =>
      clampDockSize(
        loadStoredDockSize(storageKey) ?? current,
        window.innerWidth,
        window.innerHeight,
      ),
    );
  }, [storageKey]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const handleResize = () => {
      setDockSize((current) =>
        clampDockSize(current, window.innerWidth, window.innerHeight),
      );
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    saveDockSize(storageKey, dockSize);
  }, [dockSize, storageKey]);

  const onTouchStart = (e: React.TouchEvent) => {
    dragStartYRef.current = e.touches[0].clientY;
    setDragY(0);
  };
  const onTouchMove = (e: React.TouchEvent) => {
    if (dragStartYRef.current == null) return;
    const delta = e.touches[0].clientY - dragStartYRef.current;
    setDragY(Math.max(0, delta));
  };
  const onTouchEnd = () => {
    if (dragY >= SWIPE_DOWN_THRESHOLD) {
      handleDismiss();
    }
    dragStartYRef.current = null;
    setDragY(0);
  };

  if (!open) return null;

  // Collapsed + no explicit close path → render the FAB.
  if (!expanded && !onDismiss) {
    // FAB lives at a modest z-layer so drawers (scrim z-40, panel z-50) sit
    // on top of it — save buttons at the bottom of a slide-in drawer must be
    // clickable without the FAB intercepting. When a drawer opens, its scrim
    // visually dims the FAB too; when no drawer is open, the FAB is still the
    // top-most button in the bottom-right region.
    if (collapsedTitle) {
      return (
        <div className="fixed bottom-4 right-4 z-[30] flex max-w-[min(360px,calc(100vw-32px))] items-center gap-1 rounded-md border border-surface-border bg-surface-raised p-1 text-text shadow-[0_4px_16px_rgba(0,0,0,0.28)]">
          <button
            onClick={() => onExpandedChange(true)}
            aria-label={`Open ${title}`}
            className="flex min-w-0 flex-1 items-center gap-2 rounded px-2 py-1 text-left transition-colors hover:bg-surface-overlay active:scale-[0.99]"
          >
            <MessageSquare size={15} className="shrink-0" />
            <span className="min-w-0">
              <span className="block truncate text-[12px] font-semibold">{collapsedTitle}</span>
              {collapsedSubtitle && (
                <span className="block truncate text-[10px] text-text-dim">{collapsedSubtitle}</span>
              )}
            </span>
          </button>
          {onCloseCollapsed && (
            <button
              type="button"
              aria-label={`Close ${title}`}
              title="Close mini chat"
              onClick={onCloseCollapsed}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-text-dim hover:bg-surface-overlay hover:text-text"
            >
              <X size={13} />
            </button>
          )}
        </div>
      );
    }
    return (
      <button
        onClick={() => onExpandedChange(true)}
        aria-label={`Open ${title}`}
        className="fixed bottom-4 right-4 z-[30] w-12 h-12 rounded-full bg-accent text-white shadow-[0_4px_16px_rgba(0,0,0,0.35)] flex items-center justify-center hover:brightness-110 active:scale-95 transition-all"
      >
        <MessageSquare size={18} />
      </button>
    );
  }

  // Collapsed + no-FAB mode: render nothing while waiting for the parent
  // to propagate open=false through its own state.
  if (!expanded) return null;

  const handleResizePointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return;
    resizeOriginRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startWidth: dockSize.width,
      startHeight: dockSize.height,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  };

  const handleResizePointerMove = (e: React.PointerEvent<HTMLButtonElement>) => {
    const origin = resizeOriginRef.current;
    if (!origin || origin.pointerId !== e.pointerId) return;
    setDockSize(
      clampDockSize(
        {
          width: origin.startWidth - (e.clientX - origin.startX),
          height: origin.startHeight - (e.clientY - origin.startY),
        },
        window.innerWidth,
        window.innerHeight,
      ),
    );
  };

  const handleResizePointerEnd = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (resizeOriginRef.current?.pointerId !== e.pointerId) return;
    resizeOriginRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
  };

  return (
    <>
      {/* Invisible scrim — click outside dismisses */}
      <div
        className="fixed inset-0 z-[9990]"
        onClick={handleDismiss}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`fixed z-[9991] flex flex-col overflow-hidden
                   bg-surface-raised
                   shadow-[0_8px_32px_rgba(0,0,0,0.4)]
                   /* mobile: full bottom sheet, uses dvh so the soft
                      keyboard doesn't push the top off-screen */
                   inset-x-0 h-[80dvh]
                   max-h-[calc(100dvh-env(safe-area-inset-top)-8px)]
                   /* desktop: anchored bottom-right */
                   md:inset-auto md:right-4
                   ${entering ? "chat-dock-panel--entering" : ""}`}
        style={{
          bottom: `calc(${keyboardOffset}px + env(safe-area-inset-bottom, 0px))`,
          transform: dragY > 0 ? `translateY(${dragY}px)` : undefined,
          transition: dragStartYRef.current == null ? "transform 180ms ease" : undefined,
          border: isTerminalMode ? "none" : `1px solid ${t.surfaceBorder}`,
          borderTopLeftRadius: isTerminalMode ? 0 : undefined,
          borderTopRightRadius: isTerminalMode ? 0 : undefined,
          borderBottomLeftRadius: isTerminalMode ? 0 : undefined,
          borderBottomRightRadius: isTerminalMode ? 0 : undefined,
          ...(isDesktopViewport ? dockStyle : {}),
        }}
      >
        <button
          type="button"
          aria-label="Resize chat window"
          title="Drag to resize"
          onPointerDown={handleResizePointerDown}
          onPointerMove={handleResizePointerMove}
          onPointerUp={handleResizePointerEnd}
          onPointerCancel={handleResizePointerEnd}
          className="hidden md:block absolute left-0 top-0 z-[2] h-7 w-7 cursor-nwse-resize bg-transparent"
        />
        {/* Mobile drag handle — tap target for swipe-down. Hidden on
            desktop (md:hidden) since the close button is the only
            dismissal path there. */}
        <div
          className="md:hidden flex items-center justify-center py-2 cursor-grab active:cursor-grabbing touch-none"
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
          aria-hidden="true"
        >
          <div className="h-1.5 w-10 rounded-full bg-surface-border" />
        </div>

        {children}
      </div>
    </>
  );
}
