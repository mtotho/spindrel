/**
 * ZoneChip — dual-gesture zone mover for channel dashboard tiles in edit
 * mode. A click opens a dropdown to pick a target canvas; a mousedown +
 * drag initiates an HTML5 drag so the user can drop the tile directly
 * onto another canvas (rail / header / dock / grid). React-grid-layout
 * uses mousedown on `.widget-drag-handle` for intra-grid drag; the chip
 * uses HTML5 `dragstart` which is a separate event pipeline, so the two
 * gestures don't conflict. Browsers disambiguate click vs drag via the
 * drag-start threshold — a static press-and-release still fires `click`
 * and opens the menu.
 *
 * Extracted from ChannelDashboardMultiCanvas so PinnedToolWidget can import
 * it without a circular dependency.
 */
import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import type { ChatZone } from "@/src/types/api";

const LABELS: Record<ChatZone, string> = {
  rail: "Rail",
  header: "Header",
  dock: "Dock",
  grid: "Grid",
};

const ZONES: ChatZone[] = ["rail", "header", "dock", "grid"];

/** dataTransfer MIME key for cross-canvas drops. */
export const PIN_DND_MIME = "application/x-spindrel-pin-id";

interface Props {
  current: ChatZone;
  onSelect: (z: ChatZone) => void;
  /** Pin id to stamp in the dataTransfer on dragstart. When omitted the
   *  chip is click-only (no drag). */
  pinId?: string;
  /** Parent signals that a cross-canvas drag is in flight. Used to paint
   *  drop-target highlights on the receiving canvas. */
  onDragStart?: (pinId: string) => void;
  onDragEnd?: () => void;
}

export function ZoneChip({ current, onSelect, pinId, onDragStart, onDragEnd }: Props) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        draggable={!!pinId}
        onDragStart={(e) => {
          if (!pinId) return;
          e.stopPropagation();
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData(PIN_DND_MIME, pinId);
          // Non-empty text/plain helps Firefox actually start the drag.
          e.dataTransfer.setData("text/plain", pinId);
          setOpen(false);
          onDragStart?.(pinId);
        }}
        onDragEnd={() => onDragEnd?.()}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className="inline-flex items-center gap-0.5 rounded px-1 py-0 text-[9px] font-semibold uppercase tracking-wide transition-colors cursor-grab active:cursor-grabbing"
        style={{
          color: t.accent,
          backgroundColor: `${t.accent}18`,
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={pinId ? "Drag to another canvas, or click to pick" : "Move to another canvas"}
      >
        {LABELS[current]}
        <ChevronDown size={8} />
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute right-0 mt-1 z-50 min-w-[104px] rounded-md border shadow-lg py-1"
          style={{
            borderColor: t.surfaceBorder,
            backgroundColor: t.surfaceRaised,
          }}
        >
          {ZONES.map((z) => (
            <button
              key={z}
              type="button"
              role="option"
              aria-selected={z === current}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                if (z !== current) onSelect(z);
              }}
              className="w-full text-left px-2 py-1 text-[11px] transition-colors hover:bg-surface-overlay"
              style={{
                color: z === current ? t.accent : t.text,
                fontWeight: z === current ? 600 : 400,
              }}
            >
              {LABELS[z]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
