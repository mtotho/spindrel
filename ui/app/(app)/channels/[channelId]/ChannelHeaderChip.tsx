import { useCallback, useMemo } from "react";
import { resolveChrome, resolvePreset } from "@/src/lib/dashboardGrid";
import type { HeaderBackdropMode } from "@/src/lib/widgetHostPolicy";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { channelSlug, useDashboards } from "@/src/stores/dashboards";
import type {
  GridLayoutItem,
  PinnedWidget,
  ToolResultEnvelope,
  WidgetDashboardPin,
  WidgetScope,
} from "@/src/types/api";
import { PinnedToolWidget } from "./PinnedToolWidget";

const HEADER_ROW_HEIGHT_PX = 32;
const HEADER_GAP_PX = 12;

function asPinnedWidget(pin: WidgetDashboardPin): PinnedWidget {
  return {
    id: pin.id,
    tool_name: pin.tool_name,
    display_name: pin.display_label ?? pin.tool_name,
    bot_id: pin.source_bot_id ?? "",
    widget_instance_id: pin.widget_instance_id ?? null,
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
    widget_contract: pin.widget_contract ?? null,
    config: pin.widget_config ?? {},
  };
}

function toGridLayout(pin: WidgetDashboardPin): GridLayoutItem {
  const gl = pin.grid_layout as GridLayoutItem | Record<string, never>;
  if (
    typeof (gl as GridLayoutItem).x === "number"
    && typeof (gl as GridLayoutItem).y === "number"
    && typeof (gl as GridLayoutItem).w === "number"
    && typeof (gl as GridLayoutItem).h === "number"
  ) {
    return gl as GridLayoutItem;
  }
  return { x: 0, y: 0, w: 4, h: 1 };
}

interface Props {
  channelId: string;
  backdropMode?: HeaderBackdropMode;
}

export function ChannelHeaderChip({ channelId, backdropMode = "glass" }: Props) {
  const { header: pins } = useChannelChatZones(channelId);
  const { allDashboards } = useDashboards();
  const unpin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);

  const handleUnpin = useCallback(
    async (pinId: string) => {
      try {
        await unpin(pinId);
      } catch (err) {
        console.error("Failed to unpin header pin:", err);
      }
    },
    [unpin],
  );

  const handleEnvelopeUpdate = useCallback(
    (pinId: string, envelope: ToolResultEnvelope) => updateEnvelope(pinId, envelope),
    [updateEnvelope],
  );

  const dashboardRow = allDashboards.find((d) => d.slug === channelSlug(channelId));
  const headerCols = resolvePreset(
    dashboardRow?.grid_config ?? null,
  ).cols.lg;
  // Header rail is always titleless at the host level. Channel-level backdrop
  // mode controls the shell; per-pin title/surface overrides do not apply here.
  const chrome = useMemo(
    () => ({ ...resolveChrome(dashboardRow?.grid_config ?? null), hoverScrollbars: true, hideTitles: true }),
    [dashboardRow?.grid_config],
  );
  const sortedPins = pins.slice().sort((a, b) => {
    const ag = toGridLayout(a);
    const bg = toGridLayout(b);
    return ag.y - bg.y || ag.x - bg.x;
  });

  if (pins.length === 0) return null;

  const railHeight = HEADER_ROW_HEIGHT_PX * 2 + HEADER_GAP_PX;

  return (
    <div
      className="pointer-events-none relative w-full"
      style={{ height: railHeight }}
    >
      <div
        className="grid h-full w-full"
        style={{
          gridTemplateColumns: `repeat(${headerCols}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(2, ${HEADER_ROW_HEIGHT_PX}px)`,
          gap: `${HEADER_GAP_PX}px`,
        }}
      >
        {sortedPins.map((pin) => {
          const gl = toGridLayout(pin);
          const chipLike = gl.h === 1 && gl.w <= 4;
          const scope: WidgetScope = chipLike
            ? { kind: "channel", channelId, compact: "chip" }
            : { kind: "channel", channelId };
          return (
            <div
              key={pin.id}
              className="pointer-events-auto min-h-0 h-full min-w-0 overflow-hidden"
              style={{
                gridColumn: `${gl.x + 1} / span ${gl.w}`,
                gridRow: `${gl.y + 1} / span ${gl.h}`,
              }}
            >
              <PinnedToolWidget
                widget={asPinnedWidget(pin)}
                scope={scope}
                layout={chipLike ? "chip" : "header"}
                borderless={chrome.borderless}
                hoverScrollbars={chrome.hoverScrollbars}
                hideTitles={chrome.hideTitles}
                headerBackdropMode={backdropMode}
                onUnpin={handleUnpin}
                onEnvelopeUpdate={handleEnvelopeUpdate}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
