import { useEffect, type ReactNode } from "react";
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
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
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
      {/* Click-outside scrim. Right-click on the scrim also dismisses so a
          second right-click anywhere closes the menu without re-firing the
          browser's native menu. */}
      <div
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
        className="fixed inset-0"
        style={{ zIndex: 50000 }}
      />
      <div
        role="menu"
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
                  ? "text-status-error hover:bg-status-error/10"
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
