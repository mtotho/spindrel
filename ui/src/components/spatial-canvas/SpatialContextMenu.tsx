import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Right-click context menu for the spatial canvas. Tile components and the
 * background each compose their own item list; this component only owns
 * positioning, dismissal (Esc / outside-click / scroll), and the row chrome.
 *
 * Style: Tailwind classes (no inline tokens — new spatial chrome is
 * Tailwind-first per project conventions).
 */

export interface SpatialContextMenuItem {
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  danger?: boolean;
  /** Renders a 1px divider above this row. */
  separator?: boolean;
  /** Renders the row in muted/disabled style and skips onClick. */
  disabled?: boolean;
  /** When true, do NOT auto-close after onClick. Used by submenu launchers
   *  (e.g. "Move ... here...") that re-set the menu items inside onClick. */
  keepOpen?: boolean;
}

interface SpatialContextMenuProps {
  screenX: number;
  screenY: number;
  items: SpatialContextMenuItem[];
  onClose: () => void;
}

const MENU_WIDTH = 200;
const ROW_HEIGHT = 30;
const SEPARATOR_HEIGHT = 9;

export function SpatialContextMenu({
  screenX,
  screenY,
  items,
  onClose,
}: SpatialContextMenuProps) {
  // Ref to the menu container — used by the outside-click listener to test
  // whether a pointerdown landed inside the menu (keep open) or anywhere
  // else (close).
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    function onScroll() {
      onClose();
    }
    // Outside-click via document-level capture listener. We deliberately do
    // NOT render a full-viewport scrim — a scrim with `pointer-events: auto`
    // swallows wheel events (so canvas zoom stops working while the menu is
    // open) and competes with the menu's own button clicks during the
    // mouseup→click sequence. This listener fires on the press, doesn't
    // preventDefault, and lets the underlying gesture (pan, wheel, etc.)
    // proceed normally after the menu has closed itself.
    function onPointerDownAnywhere(e: PointerEvent) {
      const menuEl = menuRef.current;
      if (menuEl && menuEl.contains(e.target as Node)) return;
      onClose();
    }
    function onWheelAnywhere() {
      // Wheel-while-menu-open should close the menu so the user's intent
      // (zoom the canvas) lands without an extra dismiss step. The wheel
      // event itself isn't preventDefault'd, so the canvas still zooms.
      onClose();
    }
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointerDownAnywhere, true);
    document.addEventListener("contextmenu", onPointerDownAnywhere, true);
    document.addEventListener("wheel", onWheelAnywhere, { capture: true, passive: true });
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointerDownAnywhere, true);
      document.removeEventListener("contextmenu", onPointerDownAnywhere, true);
      document.removeEventListener("wheel", onWheelAnywhere, { capture: true } as EventListenerOptions);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [onClose]);

  if (typeof document === "undefined") return null;

  const rowCount = items.length;
  const sepCount = items.filter((i) => i.separator).length;
  const menuHeight = rowCount * ROW_HEIGHT + sepCount * SEPARATOR_HEIGHT + 8;
  const clampedX = Math.min(screenX, window.innerWidth - MENU_WIDTH - 8);
  const clampedY = Math.min(screenY, window.innerHeight - menuHeight - 8);

  return createPortal(
    <>
      <div
        ref={menuRef}
        role="menu"
        // Stop pointer/click events from bubbling through the React tree
        // into the SpatialCanvas viewport. Without this, the canvas's
        // `onBgPointerDown` claims the pointer via `setPointerCapture` and
        // the button's `pointerup`/`click` events never reach the menu —
        // so menu items appear dead. The menu is in a portal at body level,
        // but React's synthetic events still propagate through the React
        // component tree, so this stop is required despite the DOM
        // separation.
        onPointerDown={(e) => e.stopPropagation()}
        onPointerUp={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onWheel={(e) => e.stopPropagation()}
        className="fixed bg-surface-raised/95 backdrop-blur border border-surface-border rounded-md shadow-lg py-1"
        style={{
          left: clampedX,
          top: clampedY,
          minWidth: MENU_WIDTH,
          zIndex: 50001,
        }}
      >
        {items.map((item, i) => (
          <div key={i}>
            {item.separator && (
              <div className="h-px bg-surface-border my-1" />
            )}
            <button
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={(e) => {
                e.stopPropagation();
                if (item.disabled) return;
                item.onClick();
                if (!item.keepOpen) onClose();
              }}
              className={`w-full flex flex-row items-center gap-2 px-3 py-1.5 text-left text-xs leading-tight cursor-pointer bg-transparent border-0 ${
                item.disabled
                  ? "text-text-dim/50 cursor-not-allowed"
                  : item.danger
                  ? "text-danger hover:bg-danger/10"
                  : "text-text hover:bg-surface-overlay"
              }`}
            >
              {item.icon && (
                <span className="flex items-center justify-center w-4 h-4 shrink-0" aria-hidden>
                  {item.icon}
                </span>
              )}
              <span className="truncate">{item.label}</span>
            </button>
          </div>
        ))}
      </div>
    </>,
    document.body,
  );
}
