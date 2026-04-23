import { useCallback, useEffect } from "react";
import { resolvePreset } from "@/src/lib/dashboardGrid";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { channelSlug, useDashboardsStore } from "@/src/stores/dashboards";
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
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
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
}

export function ChannelHeaderChip({ channelId }: Props) {
  const { header: pins } = useChannelChatZones(channelId);
  const dashboards = useDashboardsStore((s) => s.list);
  const dashboardsHydrated = useDashboardsStore((s) => s.hasHydrated);
  const hydrateDashboards = useDashboardsStore((s) => s.hydrate);
  const unpin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);

  useEffect(() => {
    if (!dashboardsHydrated) void hydrateDashboards();
  }, [dashboardsHydrated, hydrateDashboards]);

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

  const headerCols = resolvePreset(
    dashboards.find((d) => d.slug === channelSlug(channelId))?.grid_config ?? null,
  ).cols.lg;
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
              className="pointer-events-auto min-w-0"
              style={{
                gridColumn: `${gl.x + 1} / span ${gl.w}`,
                gridRow: `${gl.y + 1} / span ${gl.h}`,
              }}
            >
              <PinnedToolWidget
                widget={asPinnedWidget(pin)}
                scope={scope}
                layout={chipLike ? "chip" : "header"}
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
