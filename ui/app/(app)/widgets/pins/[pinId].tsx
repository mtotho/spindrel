import { useEffect, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronLeft, Minimize2, RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { PinnedToolWidget } from "@/app/(app)/channels/[channelId]/PinnedToolWidget";
import { useDashboardPin } from "@/src/api/hooks/useDashboardPin";
import { useSpatialNodes } from "@/src/api/hooks/useWorkspaceSpatial";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { channelIdFromSlug, isChannelSlug } from "@/src/stores/dashboards";
import { asPinnedWidget } from "@/src/lib/widgetPins";
import { writeSpatialHandoff } from "@/src/lib/spatialHandoff";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import type { ToolResultEnvelope, WidgetDashboardPin } from "@/src/types/api";

function dashboardHref(pin: WidgetDashboardPin): string {
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

function matchesCanvasPin(nodePinId: string | null, nodePinOrigin: unknown, pinId: string): boolean {
  if (nodePinId === pinId) return true;
  if (!nodePinOrigin || typeof nodePinOrigin !== "object") return false;
  const origin = nodePinOrigin as { source_dashboard_pin_id?: unknown };
  return origin.source_dashboard_pin_id === pinId;
}

export default function WidgetPinPage() {
  const { pinId } = useParams<{ pinId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();
  const { data: pin, isLoading, error, refetch } = useDashboardPin(pinId);
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

  const goBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate(fallbackBackHref(pin));
  };

  const collapseToSpace = () => {
    if (!pin) return;
    writeSpatialHandoff({ kind: "widgetPin", pinId: pin.id, ts: Date.now() });
    navigate("/canvas");
  };

  const handleEnvelopeUpdate = (widgetId: string, envelope: ToolResultEnvelope) => {
    updateEnvelope(widgetId, envelope);
    queryClient.setQueryData<WidgetDashboardPin>(["dashboard-pin", widgetId], (current) =>
      current ? { ...current, envelope } : current,
    );
  };

  const right = pin ? (
    <>
      {!isMobile && (
        <button
          type="button"
          onClick={collapseToSpace}
          disabled={!canvasNode}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-surface-border px-3 text-sm text-text-muted transition-colors hover:bg-surface-overlay hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
          title={canvasNode ? "Collapse to spatial canvas" : "This widget is not on the spatial canvas"}
        >
          <Minimize2 size={15} />
          <span>Collapse to space</span>
        </button>
      )}
      <button
        type="button"
        onClick={() => void refetch()}
        className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-surface-border text-text-muted transition-colors hover:bg-surface-overlay hover:text-text"
        title="Reload widget"
        aria-label="Reload widget"
      >
        <RefreshCw size={15} />
      </button>
    </>
  ) : null;

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <PageHeader
        variant="detail"
        parentLabel="Widgets"
        title={title}
        subtitle={pin?.source_channel_id ? "Pinned channel widget" : "Pinned widget"}
        onBack={goBack}
        right={right}
      />
      <main className="flex min-h-0 flex-1 flex-col p-0 md:items-center md:justify-center md:p-4">
        {isLoading ? (
          <div className="m-4 rounded-md border border-surface-border bg-surface-raised px-4 py-3 text-sm text-text-muted">
            Loading widget...
          </div>
        ) : error || !pin ? (
          <div className="m-4 flex max-w-lg flex-col gap-3 rounded-md border border-surface-border bg-surface-raised px-4 py-4 text-sm text-text-muted">
            <div>Widget could not be loaded.</div>
            <button
              type="button"
              onClick={goBack}
              className="inline-flex w-fit items-center gap-2 rounded-md border border-surface-border px-3 py-2 text-text hover:bg-surface-overlay"
            >
              <ChevronLeft size={15} />
              Back
            </button>
          </div>
        ) : (
          <div className="flex min-h-0 w-full flex-1 flex-col md:h-[min(760px,calc(100vh-156px))] md:max-w-[1120px] md:flex-none">
            <PinnedToolWidget
              widget={asPinnedWidget(pin)}
              scope={{ kind: "dashboard", channelId: pin.source_channel_id ?? undefined }}
              onUnpin={() => undefined}
              onEnvelopeUpdate={handleEnvelopeUpdate}
              panelSurface
              borderless={isMobile}
              hideTitles={false}
              hoverScrollbars
            />
          </div>
        )}
      </main>
    </div>
  );
}

