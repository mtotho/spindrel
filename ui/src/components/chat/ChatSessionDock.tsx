import { useCallback, useEffect, useRef, useState } from "react";
import { MessageSquare } from "lucide-react";

interface ChatSessionDockProps {
  open: boolean;
  /** Controlled expansion — FAB vs panel. Lifted so the controller's
      header X button can collapse back to FAB. */
  expanded: boolean;
  onExpandedChange: (next: boolean) => void;
  title: string;
  children: React.ReactNode;
  /** When provided, the dock has no FAB lifecycle — dismissal (scrim
   *  click, Escape, mobile swipe-down) calls onDismiss instead of
   *  collapsing to a FAB. Used on the channel screen where the dock is
   *  reachable only from the channel header button. */
  onDismiss?: () => void;
}

/** Threshold in px for the mobile swipe-down gesture to dismiss. */
const SWIPE_DOWN_THRESHOLD = 80;

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
  children,
  onDismiss,
}: ChatSessionDockProps) {
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
    return (
      <button
        onClick={() => onExpandedChange(true)}
        aria-label={`Open ${title}`}
        className="fixed bottom-4 right-4 z-[30] w-12 h-12 rounded-full
                   bg-accent text-white shadow-[0_4px_16px_rgba(0,0,0,0.35)]
                   flex items-center justify-center
                   hover:brightness-110 active:scale-95 transition-all"
      >
        <MessageSquare size={18} />
      </button>
    );
  }

  // Collapsed + no-FAB mode: render nothing while waiting for the parent
  // to propagate open=false through its own state.
  if (!expanded) return null;

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
                   bg-surface-raised border border-surface-border
                   shadow-[0_8px_32px_rgba(0,0,0,0.4)]
                   /* mobile: full bottom sheet, uses dvh so the soft
                      keyboard doesn't push the top off-screen */
                   inset-x-0 rounded-t-xl h-[80dvh]
                   max-h-[calc(100dvh-env(safe-area-inset-top)-8px)]
                   /* desktop: anchored bottom-right */
                   md:inset-auto md:right-4
                   md:w-[380px] md:h-[560px]
                   md:rounded-xl
                   ${entering ? "chat-dock-panel--entering" : ""}`}
        style={{
          bottom: `calc(${keyboardOffset}px + env(safe-area-inset-bottom, 0px))`,
          transform: dragY > 0 ? `translateY(${dragY}px)` : undefined,
          transition: dragStartYRef.current == null ? "transform 180ms ease" : undefined,
        }}
      >
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
