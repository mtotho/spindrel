// Overflow (…) menu for the channel header. Keeps the top bar slim by
// collapsing secondary controls (compact toggle, split view, browse files,
// dashboard, participants, findings) behind a single trigger.

import { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { MoreHorizontal } from "lucide-react";

import { useThemeTokens } from "@/src/theme/tokens";

export interface OverflowItem {
  key: string;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  active?: boolean;
  /** Optional right-side numeric badge (e.g. participant count, findings count). */
  badge?: number;
  /** Badge that should read as attention-grabbing (e.g. pulsing amber for findings). */
  attention?: boolean;
  hidden?: boolean;
}

interface ChannelHeaderOverflowMenuProps {
  items: OverflowItem[];
  isMobile?: boolean;
}

export function ChannelHeaderOverflowMenu({
  items,
  isMobile = false,
}: ChannelHeaderOverflowMenuProps) {
  const t = useThemeTokens();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; right: number }>({ top: 0, right: 0 });

  const visibleItems = items.filter((i) => !i.hidden);
  const anyAttention = visibleItems.some((i) => i.attention && !!i.badge);
  const totalBadge = visibleItems.reduce((sum, i) => sum + (i.badge ?? 0), 0);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        popoverRef.current && !popoverRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open]);

  const toggle = () => {
    if (!triggerRef.current) {
      setOpen((v) => !v);
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    setPos({
      top: rect.bottom + 6,
      right: Math.max(8, window.innerWidth - rect.right),
    });
    setOpen((v) => !v);
  };

  if (visibleItems.length === 0) return null;

  const size = isMobile ? 44 : 36;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="header-icon-btn relative"
        style={{ width: size, height: size, backgroundColor: open ? t.surfaceOverlay : "transparent" }}
        onClick={toggle}
        aria-label="More actions"
        aria-expanded={open}
        title="More"
      >
        <MoreHorizontal size={16} color={open ? t.accent : t.textDim} />
        {anyAttention && totalBadge > 0 && (
          <span
            className="absolute top-1 right-1 min-w-[14px] h-[14px] px-1 rounded-full text-[9px] font-bold flex items-center justify-center leading-none animate-pulse"
            style={{ backgroundColor: t.accent, color: t.surface }}
          >
            {totalBadge > 9 ? "9+" : totalBadge}
          </span>
        )}
        {!anyAttention && totalBadge > 0 && (
          <span
            className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: t.accent }}
          />
        )}
      </button>

      {open &&
        ReactDOM.createPortal(
          <div
            ref={popoverRef}
            role="menu"
            aria-label="More actions"
            className="fixed z-[10000] flex flex-col rounded-lg border shadow-xl overflow-hidden py-1"
            style={{
              top: pos.top,
              right: pos.right,
              width: 240,
              backgroundColor: t.surfaceRaised,
              borderColor: t.surfaceBorder,
            }}
          >
            {visibleItems.map((item) => (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                onClick={() => {
                  item.onClick();
                  setOpen(false);
                }}
                className="flex flex-row items-center gap-2.5 w-full px-3 py-2 bg-transparent border-none cursor-pointer text-left transition-colors hover:bg-white/[0.04]"
                style={{ opacity: 1 }}
              >
                <span
                  className="shrink-0 w-4 h-4 flex items-center justify-center"
                  style={{ color: item.active ? t.accent : t.textMuted }}
                >
                  {item.icon}
                </span>
                <span
                  className="flex-1 text-[13px] truncate"
                  style={{ color: item.active ? t.accent : t.text }}
                >
                  {item.label}
                </span>
                {typeof item.badge === "number" && item.badge > 0 && (
                  <span
                    className="shrink-0 text-[10px] font-semibold rounded"
                    style={{
                      padding: "1px 6px",
                      background: item.attention ? `${t.accent}20` : "rgba(148,163,184,0.18)",
                      color: item.attention ? t.accent : t.textMuted,
                    }}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
