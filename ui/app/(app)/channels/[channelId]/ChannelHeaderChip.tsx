/**
 * ChannelHeaderChip — compact chip-row rendering of channel dashboard pins
 * that land in the "header" band (y=0, h=1, middle columns). Multiple chips
 * are allowed; the first few render inline, the rest collapse into a `+N`
 * popover.
 *
 * Desktop-only — mobile hides entirely; header real estate contested by back
 * chevron + channel name.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { MoreHorizontal } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import type { PinnedWidget, ToolResultEnvelope, WidgetDashboardPin } from "@/src/types/api";
import { PinnedToolWidget } from "./PinnedToolWidget";

const INLINE_CAP = 3;

function asPinnedWidget(pin: WidgetDashboardPin): PinnedWidget {
  return {
    id: pin.id,
    tool_name: pin.tool_name,
    display_name: pin.display_label ?? pin.tool_name,
    bot_id: pin.source_bot_id ?? "",
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
    config: pin.widget_config ?? {},
  };
}

interface Props {
  channelId: string;
}

export function ChannelHeaderChip({ channelId }: Props) {
  const t = useThemeTokens();
  const { header_chip: pins } = useChannelChatZones(channelId);
  const unpin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const [overflowOpen, setOverflowOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!overflowOpen) return;
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOverflowOpen(false);
      }
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [overflowOpen]);

  const handleUnpin = useCallback(
    async (pinId: string) => {
      try {
        await unpin(pinId);
      } catch (err) {
        console.error("Failed to unpin header chip:", err);
      }
    },
    [unpin],
  );

  const handleEnvelopeUpdate = useCallback(
    (pinId: string, envelope: ToolResultEnvelope) => updateEnvelope(pinId, envelope),
    [updateEnvelope],
  );

  if (pins.length === 0) return null;

  const inlinePins = pins.slice(0, INLINE_CAP);
  const overflowPins = pins.slice(INLINE_CAP);

  return (
    <div className="flex items-center gap-1.5">
      {inlinePins.map((p) => (
        <PinnedToolWidget
          key={p.id}
          widget={asPinnedWidget(p)}
          scope={{ kind: "channel", channelId, compact: "chip" }}
          onUnpin={handleUnpin}
          onEnvelopeUpdate={handleEnvelopeUpdate}
        />
      ))}
      {overflowPins.length > 0 && (
        <div className="relative" ref={popoverRef}>
          <button
            type="button"
            className="flex items-center gap-1 h-8 rounded-md border border-surface-border/60 bg-surface-raised/40 px-2 text-[11px] font-medium transition-colors hover:bg-surface-overlay"
            style={{ color: t.textMuted }}
            onClick={() => setOverflowOpen((v) => !v)}
            title={`${overflowPins.length} more chip${overflowPins.length === 1 ? "" : "s"}`}
          >
            <MoreHorizontal size={12} />
            <span>+{overflowPins.length}</span>
          </button>
          {overflowOpen && (
            <div
              className="absolute right-0 top-[calc(100%+6px)] z-30 flex flex-col gap-2 rounded-md border border-surface-border bg-surface-raised p-2 shadow-lg"
              style={{ minWidth: 200 }}
            >
              {overflowPins.map((p) => (
                <PinnedToolWidget
                  key={p.id}
                  widget={asPinnedWidget(p)}
                  scope={{ kind: "channel", channelId, compact: "chip" }}
                  onUnpin={handleUnpin}
                  onEnvelopeUpdate={handleEnvelopeUpdate}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
