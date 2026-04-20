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

  if (pins.length === 0) return null;

  const dashboardHref = `/widgets/channel/${encodeURIComponent(channelId)}?zone=dock`;

  return (
    <>
      <ResizeHandle
        direction="horizontal"
        onResize={(delta: number) =>
          setWidth((w) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w - delta)))
        }
        invisible
      />
      <div
        className="flex flex-col h-full overflow-hidden rounded-lg border border-surface-border/50"
        style={{ width, flexShrink: 0, backgroundColor: t.surfaceRaised }}
      >
        <div
          className="flex items-center gap-1 px-2 py-1.5"
          style={{ borderBottom: `1px solid ${t.surfaceBorder}55` }}
        >
          <span
            className="flex-1 text-[10px] font-medium uppercase tracking-wider"
            style={{ color: t.textDim }}
          >
            Right dock
          </span>
          <Link
            to={dashboardHref}
            aria-label="Edit right dock on channel dashboard"
            title="Edit on channel dashboard"
            className="flex items-center justify-center w-6 h-6 rounded-md transition-colors"
            style={{ color: t.textDim, opacity: 0.55 }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = "1";
              e.currentTarget.style.backgroundColor = t.surfaceOverlay;
              e.currentTarget.style.color = t.text;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = "0.55";
              e.currentTarget.style.backgroundColor = "transparent";
              e.currentTarget.style.color = t.textDim;
            }}
          >
            <Settings2 size={12} />
          </Link>
          {/* Collapse chevron — hides the dock; a peek-tab on the viewport's
              right edge brings it back. */}
          <button
            type="button"
            onClick={() => setRightDockHidden(true)}
            aria-label="Collapse right dock"
            title="Collapse dock"
            className="flex items-center justify-center w-6 h-6 rounded-md transition-colors"
            style={{ color: t.textDim, opacity: 0.55 }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = "1";
              e.currentTarget.style.backgroundColor = t.surfaceOverlay;
              e.currentTarget.style.color = t.text;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = "0.55";
              e.currentTarget.style.backgroundColor = "transparent";
              e.currentTarget.style.color = t.textDim;
            }}
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
      </div>
    </>
  );
}
