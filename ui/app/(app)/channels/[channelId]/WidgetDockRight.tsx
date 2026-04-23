/**
 * WidgetDockRight — right-side chat dock mirroring OmniPanel's rail.
 *
 * Reads dock pins from the channel's dashboard (positional: left edge inside
 * the rightmost `dockRightCols` band) and renders each via the same
 * `PinnedToolWidget` used by OmniPanel. Ordering is preserved from the
 * channel-chat-zones resolver (y then x).
 *
 * Author on the channel dashboard at `/widgets/channel/:id` — this component
 * is strictly read-only. Width is owned by the channel runtime panel prefs.
 */
import { useCallback, useMemo } from "react";
import { ChevronRight } from "lucide-react";
import { ResizeHandle } from "@/src/components/workspace/ResizeHandle";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useDashboards, channelSlug } from "@/src/stores/dashboards";
import { useUIStore } from "@/src/stores/ui";
import { resolveChrome, resolvePreset } from "@/src/lib/dashboardGrid";
import {
  CHANNEL_PANEL_DEFAULT_WIDTH,
  CHANNEL_PANEL_MAX_WIDTH,
  clampChannelPanelWidth,
} from "@/src/lib/channelPanelLayout";
import type { ToolResultEnvelope } from "@/src/types/api";
import { WidgetRailSection } from "./WidgetRailSection";

interface Props {
  channelId: string;
  dashboardHref?: string;
  width?: number;
  maxWidth?: number;
  onWidthChange?: (width: number) => void;
  onCollapse?: () => void;
}

export function WidgetDockRight({
  channelId,
  width = CHANNEL_PANEL_DEFAULT_WIDTH,
  maxWidth = CHANNEL_PANEL_MAX_WIDTH,
  onWidthChange,
  onCollapse,
}: Props) {
  const { dock: pins } = useChannelChatZones(channelId);
  const unpin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const setRightDockHidden = useUIStore((s) => s.setRightDockHidden);
  // Use `allDashboards` rather than `list` — channel dashboards are filtered
  // out of the tab-bar-friendly `list` slice.
  const { allDashboards } = useDashboards();
  const dashboardRow = allDashboards.find((d) => d.slug === channelSlug(channelId));
  const preset = useMemo(
    () => resolvePreset(dashboardRow?.grid_config ?? null),
    [dashboardRow?.grid_config],
  );
  // Chat-mode rails override the dashboard's saved hover_scrollbars default —
  // the rails are persistent chrome, not a focused widget surface. The
  // standalone dashboard view still honors the author's saved choice.
  const chrome = useMemo(
    () => ({ ...resolveChrome(dashboardRow?.grid_config ?? null), hoverScrollbars: true }),
    [dashboardRow?.grid_config],
  );
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);

  const handleUnpin = useCallback(
    async (pinId: string) => {
      try {
        await unpin(pinId);
      } catch (err) {
        console.error("Failed to unpin dock widget:", err);
      }
    },
    [unpin],
  );

  const handleEnvelopeUpdate = useCallback(
    (pinId: string, envelope: ToolResultEnvelope) => updateEnvelope(pinId, envelope),
    [updateEnvelope],
  );

  // Reserve the gutter the instant we know a dock pin exists — don't wait for
  // each pin's widget envelope/body to hydrate. Width transitions smoothly
  // between 0 and the user-chosen width so a late-arriving pin doesn't
  // displace the chat column with a hard reflow. Viewport responsiveness
  // is preserved because the outer container honors its parent's flex rules.
  const hasPins = pins.length > 0;
  const targetWidth = hasPins ? width : 0;

  return (
    <>
      {hasPins && (
        <ResizeHandle
          direction="horizontal"
          onResize={(delta: number) =>
            onWidthChange?.(clampChannelPanelWidth(width - delta, maxWidth))
          }
          invisible
        />
      )}
      <div
        className="group relative flex h-full flex-col overflow-visible"
        style={{
          width: targetWidth,
          flexShrink: 0,
          transition: "width 220ms cubic-bezier(0.4, 0, 0.2, 1)",
        }}
        aria-hidden={!hasPins}
      >
        {hasPins && <>
          <div className="flex h-8 shrink-0 items-center pl-0 pr-1">
            <button
              type="button"
              onClick={() => {
                if (onCollapse) onCollapse();
                else setRightDockHidden(true);
              }}
              aria-label="Collapse right dock"
              title="Collapse dock"
              className="flex h-7 w-7 items-center justify-center bg-transparent text-text-dim/70 transition-colors hover:bg-surface-overlay/60 hover:text-text focus-visible:bg-surface-overlay/60 focus-visible:text-text focus-visible:outline-none"
            >
              <ChevronRight size={15} />
            </button>
          </div>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto scroll-subtle pb-2 pl-0 pr-1">
            <WidgetRailSection
              channelId={channelId}
              pins={pins}
              preset={preset}
              chrome={chrome}
              onUnpin={handleUnpin}
              onEnvelopeUpdate={handleEnvelopeUpdate}
              applyLayout={applyLayout}
              widgetLayout="dock"
            />
          </div>
        </>}
      </div>
    </>
  );
}
