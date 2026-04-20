/**
 * WidgetDockRight — right-side chat dock mirroring OmniPanel's rail.
 *
 * Reads dock pins from the channel's dashboard (positional: left edge inside
 * the rightmost `dockRightCols` band) and renders each via the same
 * `PinnedToolWidget` used by OmniPanel. Ordering is preserved from the
 * channel-chat-zones resolver (y then x).
 *
 * Author on the channel dashboard at `/widgets/channel/:id` — this component
 * is strictly read-only. Width is user-persisted in localStorage.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Settings2 } from "lucide-react";
import { ResizeHandle } from "@/src/components/workspace/ResizeHandle";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useDashboards, channelSlug } from "@/src/stores/dashboards";
import { useUIStore } from "@/src/stores/ui";
import { resolveChrome } from "@/src/lib/dashboardGrid";
import type { PinnedWidget, ToolResultEnvelope, WidgetDashboardPin } from "@/src/types/api";
import { PinnedToolWidget } from "./PinnedToolWidget";

const STORAGE_KEY = "chat-dock-right-width";
const DEFAULT_WIDTH = 320;
const MIN_WIDTH = 240;
const MAX_WIDTH = 520;

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

export function WidgetDockRight({ channelId }: Props) {
  const t = useThemeTokens();
  const { dock: pins } = useChannelChatZones(channelId);
  const unpin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const setRightDockHidden = useUIStore((s) => s.setRightDockHidden);
  // Use `allDashboards` rather than `list` — channel dashboards are filtered
  // out of the tab-bar-friendly `list` slice.
  const { allDashboards } = useDashboards();
  const dashboardRow = allDashboards.find((d) => d.slug === channelSlug(channelId));
  const chrome = resolveChrome(dashboardRow?.grid_config ?? null);

  const [width, setWidth] = useState<number>(() => {
    if (typeof window === "undefined") return DEFAULT_WIDTH;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? parseInt(raw, 10) : NaN;
    return Number.isFinite(parsed) && parsed >= MIN_WIDTH && parsed <= MAX_WIDTH
      ? parsed
      : DEFAULT_WIDTH;
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEY, String(width));
  }, [width]);

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
  const dashboardHref = `/widgets/channel/${encodeURIComponent(channelId)}?zone=dock`;

  return (
    <>
      {hasPins && (
        <ResizeHandle
          direction="horizontal"
          onResize={(delta: number) =>
            setWidth((w) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w - delta)))
          }
          invisible
        />
      )}
      <div
        className="group relative flex flex-col h-full overflow-hidden"
        style={{
          width: targetWidth,
          flexShrink: 0,
          transition: "width 220ms cubic-bezier(0.4, 0, 0.2, 1)",
        }}
        aria-hidden={!hasPins}
      >
        {hasPins && <>
        {/* Hover-revealed top-right controls — the bare column has no title
            strip, so Settings + Collapse fade in only on hover to keep the
            column calm at rest. */}
        <div className="absolute top-1 right-1 z-10 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <Link
            to={dashboardHref}
            aria-label="Edit right dock on channel dashboard"
            title="Edit on channel dashboard"
            className="flex items-center justify-center w-6 h-6 rounded-md hover:bg-white/[0.06]"
            style={{ color: t.textDim }}
          >
            <Settings2 size={12} />
          </Link>
          <button
            type="button"
            onClick={() => setRightDockHidden(true)}
            aria-label="Collapse right dock"
            title="Collapse dock"
            className="flex items-center justify-center w-6 h-6 rounded-md hover:bg-white/[0.06]"
            style={{ color: t.textDim }}
          >
            <ChevronRight size={14} />
          </button>
        </div>
        <div className="flex flex-col flex-1 min-h-0 overflow-y-auto gap-2 px-2 py-2">
          {pins.map((p) => (
            <PinnedToolWidget
              key={p.id}
              widget={asPinnedWidget(p)}
              scope={{ kind: "channel", channelId }}
              onUnpin={handleUnpin}
              onEnvelopeUpdate={handleEnvelopeUpdate}
              borderless={chrome.borderless}
              hoverScrollbars={chrome.hoverScrollbars}
            />
          ))}
        </div>
        </>}
      </div>
    </>
  );
}
