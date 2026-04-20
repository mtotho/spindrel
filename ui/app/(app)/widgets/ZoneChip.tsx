/**
 * ZoneChip — compact zone-picker dropdown shown in PinnedToolWidget's tile
 * header on channel dashboards in edit mode. Lets the user move a pin
 * between the four canvases (rail / header / dock / grid) without dragging
 * between react-grid-layout instances.
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

interface Props {
  current: ChatZone;
  onSelect: (z: ChatZone) => void;
}

export function ZoneChip({ current, onSelect }: Props) {
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
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className="inline-flex items-center gap-0.5 rounded px-1 py-0 text-[9px] font-semibold uppercase tracking-wide transition-colors"
        style={{
          color: t.accent,
          backgroundColor: `${t.accent}18`,
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Move to another canvas"
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
