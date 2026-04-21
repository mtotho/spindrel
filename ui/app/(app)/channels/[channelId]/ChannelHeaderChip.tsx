/**
 * ChannelHeaderChip — compact chip-row rendering of channel dashboard pins
 * that land in the "header" band (single fixed slot for now).
 *
 * Desktop-only — mobile hides entirely; header real estate contested by back
 * chevron + channel name.
 */
import { useCallback } from "react";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import type { PinnedWidget, ToolResultEnvelope, WidgetDashboardPin } from "@/src/types/api";
import { PinnedToolWidget } from "./PinnedToolWidget";

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
  const { header: pins } = useChannelChatZones(channelId);
  const unpin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);

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
  const pin = pins[0];

  return (
    <div className="flex items-center gap-1.5">
      <PinnedToolWidget
        key={pin.id}
        widget={asPinnedWidget(pin)}
        scope={{ kind: "channel", channelId, compact: "chip" }}
        onUnpin={handleUnpin}
        onEnvelopeUpdate={handleEnvelopeUpdate}
      />
    </div>
  );
}
