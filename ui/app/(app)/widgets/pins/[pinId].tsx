import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Bot, Bug, ExternalLink, Hash, LayoutDashboard, Menu, Minimize2, RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { PinnedToolWidget, type PinnedToolWidgetControls } from "@/app/(app)/channels/[channelId]/PinnedToolWidget";
import { WidgetInspector } from "@/app/(app)/channels/[channelId]/WidgetInspector";
import { useDashboardPin } from "@/src/api/hooks/useDashboardPin";
import { useChannel } from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { useSpatialNodes } from "@/src/api/hooks/useWorkspaceSpatial";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { channelIdFromSlug, isChannelSlug, isWorkspaceSpatialSlug } from "@/src/stores/dashboards";
import { asPinnedWidget } from "@/src/lib/widgetPins";
import { writeSpatialHandoff } from "@/src/lib/spatialHandoff";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import { readContextualNavigationState } from "@/src/lib/contextualNavigation";
import { useUIStore } from "@/src/stores/ui";
import type { ToolResultEnvelope, WidgetDashboardPin } from "@/src/types/api";

function dashboardHref(pin: WidgetDashboardPin): string {
  if (isWorkspaceSpatialSlug(pin.dashboard_key)) return "/canvas";
  if (isChannelSlug(pin.dashboard_key)) {
    const channelId = channelIdFromSlug(pin.dashboard_key);
    if (channelId) return `/widgets/channel/${encodeURIComponent(channelId)}`;
  }
  return `/widgets/${encodeURIComponent(pin.dashboard_key)}`;
}

function fallbackBackHref(pin: WidgetDashboardPin | undefined): string {
  if (!pin) return "/canvas";
  if (pin.source_channel_id) return `/channels/${encodeURIComponent(pin.source_channel_id)}`;
  return dashboardHref(pin);
}

function shortId(value: string | null | undefined): string {
  if (!value) return "none";
  return value.length > 12 ? value.slice(0, 8) : value;
}

function matchesCanvasPin(nodePinId: string | null, nodePinOrigin: unknown, pinId: string): boolean {
  if (nodePinId === pinId) return true;
  if (!nodePinOrigin || typeof nodePinOrigin !== "object") return false;
  const origin = nodePinOrigin as { source_dashboard_pin_id?: unknown };
  return origin.source_dashboard_pin_id === pinId;
}

export default function WidgetPinPage() {
  const { pinId } = useParams<{ pinId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();
  const openPalette = useUIStore((s) => s.openPalette);
  const widgetControlsRef = useRef<PinnedToolWidgetControls | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [pageRefreshing, setPageRefreshing] = useState(false);
  const { data: pin, isLoading, error, refetch } = useDashboardPin(pinId);
  const { data: sourceChannel } = useChannel(pin?.source_channel_id ?? undefined);
  const { data: bots = [] } = useBots();
  const hydrateDashboard = useDashboardPinsStore((s) => s.hydrate);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const { data: nodes } = useSpatialNodes();
  const canvasNode = useMemo(() => {
    if (!pinId || !nodes) return null;
    return nodes.find((node) =>
      matchesCanvasPin(node.widget_pin_id, node.pin?.widget_origin, pinId),
    ) ?? null;
  }, [nodes, pinId]);

  useEffect(() => {
    if (pin?.dashboard_key) void hydrateDashboard(pin.dashboard_key);
  }, [pin?.dashboard_key, hydrateDashboard]);

  const title =
    pin?.display_label
    ?? pin?.envelope?.display_label
    ?? pin?.envelope?.panel_title
    ?? pin?.tool_name
    ?? "Widget";
  const bot = bots.find((candidate) => candidate.id === pin?.source_bot_id) ?? null;
  const botLabel =
    bot?.display_name
    ?? bot?.name
    ?? pin?.source_bot_id
    ?? "User scoped";
  const sourceLabel = sourceChannel?.display_name ?? sourceChannel?.name ?? pin?.source_channel_id ?? "No source channel";
  const dashboardLabel = isWorkspaceSpatialSlug(pin?.dashboard_key)
    ? "Spatial canvas"
    : isChannelSlug(pin?.dashboard_key)
      ? "Channel dashboard"
      : pin?.dashboard_key ?? "Dashboard";

  const goBack = () => {
    const contextualBack = readContextualNavigationState(location.state);
    if (contextualBack?.backTo) {
      navigate(contextualBack.backTo, { replace: true });
      return;
    }
    if (window.history.length > 1) navigate(-1);
    else navigate(fallbackBackHref(pin));
  };

  const collapseToSpace = () => {
    if (!pin) return;
    writeSpatialHandoff({ kind: "widgetPin", pinId: pin.id, ts: Date.now() });
    navigate("/canvas");
  };

  const refreshWidget = async () => {
    setPageRefreshing(true);
    try {
      const controls = widgetControlsRef.current;
      if (controls) await controls.refresh();
      await refetch();
    } finally {
      setPageRefreshing(false);
    }
  };

  const handleEnvelopeUpdate = (widgetId: string, envelope: ToolResultEnvelope) => {
    updateEnvelope(widgetId, envelope);
    queryClient.setQueryData<WidgetDashboardPin>(["dashboard-pin", widgetId], (current) =>
      current ? { ...current, envelope } : current,
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <header className="shrink-0 bg-surface px-3 pb-2 pt-3 md:px-5 md:pt-4">
        <div className="flex min-h-11 items-center gap-2 md:gap-3">
          <button
            type="button"
            onClick={goBack}
            className="header-icon-btn h-10 w-10 shrink-0"
            aria-label="Back"
            title="Back"
          >
            <ArrowLeft size={19} className="text-text-muted" />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <LayoutDashboard size={16} className="shrink-0 text-text-dim" />
              <h1 className="truncate text-[15px] font-semibold text-text md:text-base">{title}</h1>
            </div>
            <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-dim">
              <span className="inline-flex min-w-0 items-center gap-1">
                <Bot size={12} />
                <span className="truncate">{botLabel}</span>
              </span>
              <span className="text-text-dim/50">/</span>
              <span className="inline-flex min-w-0 items-center gap-1">
                <Hash size={12} />
                <span className="truncate">{sourceLabel}</span>
              </span>
            </div>
          </div>
          {pin && (
            <div className="flex shrink-0 items-center gap-1.5">
              {!isMobile && (
                <button
                  type="button"
                  onClick={collapseToSpace}
                  disabled={!canvasNode}
                  className="inline-flex h-9 items-center gap-2 rounded-md px-2.5 text-sm text-text-muted transition-colors hover:bg-surface-overlay hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
                  title={canvasNode ? "Collapse to spatial canvas" : "This widget is not on the spatial canvas"}
                >
                  <Minimize2 size={15} />
                  <span className="hidden lg:inline">Collapse to space</span>
                </button>
              )}
              <button
                type="button"
                onClick={() => void refreshWidget()}
                disabled={pageRefreshing}
                className="header-icon-btn h-9 w-9"
                title={widgetControlsRef.current?.refreshTooltip ?? "Refresh"}
                aria-label="Refresh widget"
              >
                <RefreshCw size={15} className={pageRefreshing ? "animate-spin text-text-muted" : "text-text-muted"} />
              </button>
              <button
                type="button"
                onClick={() => setInspectorOpen(true)}
                className="header-icon-btn h-9 w-9"
                title="Inspect widget"
                aria-label="Inspect widget"
              >
                <Bug size={15} className="text-text-muted" />
              </button>
              {isMobile && (
                <button
                  type="button"
                  onClick={openPalette}
                  className="header-icon-btn h-9 w-9"
                  title="Open menu"
                  aria-label="Open menu"
                >
                  <Menu size={15} className="text-text-muted" />
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      <main className="flex min-h-0 flex-1 flex-col px-2 pb-1 md:px-6 md:pb-2">
        {isLoading ? (
          <div className="m-4 rounded-md bg-surface-raised px-4 py-3 text-sm text-text-muted">
            Loading widget...
          </div>
        ) : error || !pin ? (
          <div className="m-4 flex max-w-lg flex-col gap-3 rounded-md bg-surface-raised px-4 py-4 text-sm text-text-muted">
            <div>Widget could not be loaded.</div>
            <button
              type="button"
              onClick={goBack}
              className="inline-flex w-fit items-center gap-2 rounded-md px-3 py-2 text-text hover:bg-surface-overlay"
            >
              <ArrowLeft size={15} />
              Back
            </button>
          </div>
        ) : (
          <div className="mx-auto flex min-h-0 w-full flex-1 flex-col md:h-[min(780px,calc(100vh-170px))] md:max-w-[1180px] md:flex-none">
            <PinnedToolWidget
              widget={asPinnedWidget(pin)}
              scope={{ kind: "dashboard", channelId: pin.source_channel_id ?? undefined }}
              onUnpin={() => undefined}
              onEnvelopeUpdate={handleEnvelopeUpdate}
              bodyOnly
              controlsRef={widgetControlsRef}
              panelSurface
              borderless
              hideTitles
              hoverScrollbars
            />
          </div>
        )}
      </main>

      {pin && (
        <footer className="shrink-0 bg-surface px-3 py-2 md:px-6">
          <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-2 text-xs text-text-dim">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span>{dashboardLabel}</span>
              <span>Pin {shortId(pin.id)}</span>
              <span>{pin.tool_name}</span>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {pin.source_channel_id && (
                <Link
                  to={`/channels/${encodeURIComponent(pin.source_channel_id)}`}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-text-muted hover:bg-surface-overlay hover:text-text"
                >
                  <ExternalLink size={13} />
                  Source
                </Link>
              )}
              <Link
                to={dashboardHref(pin)}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-text-muted hover:bg-surface-overlay hover:text-text"
              >
                <LayoutDashboard size={13} />
                Dashboard
              </Link>
            </div>
          </div>
        </footer>
      )}
      {inspectorOpen && pin && (
        <WidgetInspector
          pinId={pin.id}
          pinLabel={title}
          onClose={() => setInspectorOpen(false)}
        />
      )}
    </div>
  );
}
