import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Check, Info, LayoutDashboard, Move, Plus, Wrench } from "lucide-react";
// Using the v1-compat legacy entry — flat props (cols, rowHeight, draggableHandle)
// match the API older examples/docs use and keep this file readable.
import {
  Responsive,
  WidthProvider,
  type Layout,
  type LayoutItem,
} from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
import { PinnedToolWidget } from "@/app/(app)/channels/[channelId]/PinnedToolWidget";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useChannel } from "@/src/api/hooks/useChannels";
import type {
  GridLayoutItem,
  PinnedWidget,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";
import AddFromChannelSheet from "./AddFromChannelSheet";
import { EditPinDrawer } from "./EditPinDrawer";
import { DashboardTabs } from "./DashboardTabs";
import { CreateDashboardSheet } from "./CreateDashboardSheet";
import { EditDashboardDrawer } from "./EditDashboardDrawer";
import { ChannelDashboardBreadcrumb } from "./ChannelDashboardBreadcrumb";
import { SidebarRailOverlay } from "./SidebarRailOverlay";
import {
  channelIdFromSlug,
  channelSlug,
  isChannelSlug,
  useDashboards,
} from "@/src/stores/dashboards";
import { resolvePreset, type GridPreset } from "@/src/lib/dashboardGrid";

/** A pin lives in the sidebar rail when it's anchored at the leftmost column
 *  (x === 0) and is narrow enough to fit. The width cutoff depends on the
 *  active dashboard's grid preset (2 units in standard, 4 in fine). */
export function isRailPin(pin: WidgetDashboardPin, railMaxWidth = 2): boolean {
  const gl = pin.grid_layout as GridLayoutItem | undefined;
  return (
    !!gl
    && typeof gl === "object"
    && gl.x === 0
    && typeof gl.w === "number"
    && gl.w <= railMaxWidth
  );
}

const ResponsiveGridLayout = WidthProvider(Responsive);

/** Screen-width breakpoints are preset-agnostic; only column counts and row
 *  heights change per preset (see `@/src/lib/dashboardGrid`). */
const BREAKPOINTS = { lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 } as const;
const GRID_MARGIN: [number, number] = [12, 12];

/** Adapt a WidgetDashboardPin row to the PinnedWidget shape the PinnedToolWidget
 *  renderer expects. Dashboard-scope calls use `widget_config` while channel-
 *  scope calls use `config`; the scope prop is what routes the store writes. */
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

/** Default tile size for a pin with no saved grid_layout. Auto-packs into
 *  the first free slot via react-grid-layout's compactType, sized from the
 *  active preset's default tile dimensions. */
function defaultLayoutForIndex(index: number, preset: GridPreset): GridLayoutItem {
  const { w, h } = preset.defaultTile;
  return { x: (index % 2) * w, y: Math.floor(index / 2) * h, w, h };
}

function hasLayout(pin: WidgetDashboardPin): pin is WidgetDashboardPin & {
  grid_layout: GridLayoutItem;
} {
  const gl = pin.grid_layout;
  return !!gl && typeof gl === "object" && "w" in gl && "h" in gl;
}

export default function WidgetsDashboardPage() {
  // Two parameterized routes feed this page:
  //   /widgets/:slug                  — user dashboards (`default`, `home`, …)
  //   /widgets/channel/:channelId     — friendly alias for `channel:<uuid>`
  const { slug: slugParam, channelId: channelIdParam } = useParams<{
    slug: string;
    channelId: string;
  }>();
  const slug = channelIdParam
    ? channelSlug(channelIdParam)
    : slugParam || "default";
  const channelScopedId = channelIdParam ?? channelIdFromSlug(slug);
  const isChannelScoped = isChannelSlug(slug);

  const { pins, isLoading, error } = useDashboardPins(slug);
  const unpinWidget = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  const { list: dashboards } = useDashboards();
  const currentDashboard = dashboards.find((d) => d.slug === slug);
  const preset = useMemo(
    () => resolvePreset(currentDashboard?.grid_config ?? null),
    [currentDashboard?.grid_config],
  );
  // Only fetched when we're on a channel dashboard — gives the breadcrumb the
  // channel's real `name` without colliding with the main channel-chat route.
  const { data: channelRow } = useChannel(channelScopedId ?? undefined);
  const railCount = useMemo(
    () => pins.filter((p) => isRailPin(p, preset.railMaxWidth)).length,
    [pins, preset.railMaxWidth],
  );
  const gridRowCount = useMemo(() => {
    let max = 0;
    for (const p of pins) {
      const gl = p.grid_layout as GridLayoutItem | undefined;
      if (!gl) continue;
      const bottom = (gl.y ?? 0) + (gl.h ?? 0);
      if (bottom > max) max = bottom;
    }
    return max;
  }, [pins]);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editingPinId, setEditingPinId] = useState<string | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [manageSlug, setManageSlug] = useState<string | null>(null);
  /** Last-added pin id — drives scroll-into-view + accent flash on the matching
   *  grid tile, cleared after ~1.4s. Set via `highlightPin` from Add sheet. */
  const [highlightPinId, setHighlightPinId] = useState<string | null>(null);
  // Track viewport width for mobile-only behavior — drag/resize on touch is
  // unusable, so the grid is read-only below the `sm` breakpoint even when
  // edit mode is toggled on (e.g. user hopped from desktop to phone).
  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined" ? window.innerWidth < 768 : false,
  );
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 767px)");
    const update = () => setIsMobile(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);
  const layoutEditable = editMode && !isMobile;

  const highlightPin = useCallback((pinId: string) => {
    setHighlightPinId(pinId);
    // Scroll next frame so the new tile is in the DOM before we query for it.
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-pin-id="${pinId}"]`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    window.setTimeout(() => setHighlightPinId((cur) => (cur === pinId ? null : cur)), 1400);
  }, []);

  const handleUnpin = async (pinId: string) => {
    try {
      await unpinWidget(pinId);
    } catch (err) {
      console.error("Failed to unpin dashboard widget:", err);
    }
  };

  const handleEnvelopeUpdate = (pinId: string, envelope: ToolResultEnvelope) => {
    updateEnvelope(pinId, envelope);
  };

  const layouts = useMemo(() => {
    const lg: LayoutItem[] = pins.map((p, idx) => {
      const base = hasLayout(p) ? p.grid_layout : defaultLayoutForIndex(idx, preset);
      return {
        i: p.id,
        x: base.x,
        y: base.y,
        w: base.w,
        h: base.h,
        minW: preset.minTile.w,
        minH: preset.minTile.h,
        maxW: preset.cols.lg,
      };
    });
    return { lg };
  }, [pins, preset]);

  // Debounce layout commits — drag/resize fires many `onLayoutChange` events.
  const pendingTimer = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
    };
  }, []);

  const scheduleCommit = (items: Layout) => {
    if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
    pendingTimer.current = window.setTimeout(() => {
      void applyLayout(
        items.map((it) => ({ id: it.i, x: it.x, y: it.y, w: it.w, h: it.h })),
      )
        .then(() => setLayoutError(null))
        .catch((err) => {
          console.error("Failed to persist dashboard layout:", err);
          setLayoutError(
            err instanceof Error ? err.message : "Failed to save layout",
          );
        });
    }, 400);
  };

  const actions = (
    <>
      {pins.length > 0 && (
        <button
          type="button"
          onClick={() => setEditMode((v) => !v)}
          className={
            "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12px] font-medium transition-colors " +
            (editMode
              ? "border-accent/60 bg-accent/10 text-accent"
              : "border-surface-border text-text-muted hover:bg-surface-overlay")
          }
          aria-pressed={editMode}
          aria-label={editMode ? "Finish editing layout" : "Rearrange widgets"}
          title={editMode ? "Finish editing" : "Rearrange widgets"}
        >
          {editMode ? <Check size={13} /> : <Move size={13} />}
          <span className="hidden md:inline">
            {editMode ? "Done" : "Edit layout"}
          </span>
        </button>
      )}
      <button
        type="button"
        onClick={() => setSheetOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2 py-1 text-[12px] font-medium text-white hover:opacity-90 transition-opacity"
        aria-label="Add widget"
        title="Add widget"
      >
        <Plus size={13} />
        <span className="hidden md:inline">Add widget</span>
      </button>
      <Link
        to="/widgets/dev"
        className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2 py-1 text-[12px] font-medium text-text-muted hover:bg-surface-overlay transition-colors"
        aria-label="Developer panel"
        title="Developer panel"
      >
        <Wrench size={13} />
        <span className="hidden lg:inline">Developer panel</span>
      </Link>
    </>
  );

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      {isChannelScoped && channelScopedId ? (
        <>
          <ChannelDashboardBreadcrumb
            channelId={channelScopedId}
            channelName={channelRow?.name}
            railCount={railCount}
            pinCount={pins.length}
          />
          <div
            className="flex shrink-0 items-center justify-end gap-2 border-b border-surface-border bg-surface px-3 py-1.5"
            role="toolbar"
            aria-label="Dashboard actions"
          >
            {actions}
          </div>
        </>
      ) : (
        <DashboardTabs
          activeSlug={slug}
          onOpenCreate={() => setCreateOpen(true)}
          onOpenManage={() => setManageSlug(slug)}
          right={actions}
        />
      )}

      <div className="relative flex-1 overflow-auto p-2 sm:p-4 md:p-6">
        {layoutError && (
          <div
            className="mx-auto mb-3 flex max-w-2xl items-center justify-between gap-3 rounded-lg border border-danger/40 bg-danger/10 px-4 py-2 text-[12px] text-danger"
            role="alert"
          >
            <span>Couldn't save layout — your changes reverted. {layoutError}</span>
            <button
              type="button"
              onClick={() => setLayoutError(null)}
              className="rounded px-2 py-0.5 text-[11px] font-medium text-danger hover:bg-danger/20"
            >
              Dismiss
            </button>
          </div>
        )}
        {editMode && isMobile && pins.length > 0 && (
          <div
            className="mx-auto mb-3 flex max-w-2xl items-center gap-2 rounded-lg border border-surface-border bg-surface-raised px-4 py-2 text-[12px] text-text-muted"
            role="status"
          >
            <Info size={13} className="shrink-0 text-text-dim" />
            <span>Layout editing is desktop-only. View pins as configured.</span>
          </div>
        )}
        {isLoading && <DashboardSkeleton />}
        {!isLoading && error && (
          <div className="mx-auto max-w-2xl rounded-lg border border-danger/40 bg-danger/10 p-4 text-center text-[13px] text-danger">
            Failed to load dashboard: {error}
          </div>
        )}
        {!isLoading && !error && pins.length === 0 && (
          <EmptyState onAddClick={() => setSheetOpen(true)} />
        )}
        {!isLoading && !error && pins.length > 0 && (
          <div className="relative">
            {isChannelScoped && layoutEditable && (
              <SidebarRailOverlay
                rowCount={Math.max(gridRowCount, 6)}
                rowHeight={preset.rowHeight}
                rowGap={GRID_MARGIN[1]}
                railCount={railCount}
              />
            )}
            <ResponsiveGridLayout
              className={layoutEditable ? "rgl-edit-mode" : ""}
              layouts={layouts}
              breakpoints={BREAKPOINTS}
              cols={preset.cols}
              rowHeight={preset.rowHeight}
              margin={GRID_MARGIN}
              isDraggable={layoutEditable}
              isResizable={layoutEditable}
              draggableHandle=".widget-drag-handle"
              compactType="vertical"
              preventCollision={false}
              onLayoutChange={(current) => {
                if (layoutEditable) scheduleCommit(current);
              }}
            >
              {pins.map((p) => (
                <div
                  key={p.id}
                  data-pin-id={p.id}
                  className={"min-w-0 " + (highlightPinId === p.id ? "pin-flash" : "")}
                >
                  <PinnedToolWidget
                    widget={asPinnedWidget(p)}
                    scope={{ kind: "dashboard" }}
                    onUnpin={handleUnpin}
                    onEnvelopeUpdate={handleEnvelopeUpdate}
                    editMode={layoutEditable}
                    onEdit={() => setEditingPinId(p.id)}
                  />
                </div>
              ))}
            </ResponsiveGridLayout>
          </div>
        )}
      </div>

      <AddFromChannelSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        dashboardName={currentDashboard?.name ?? "dashboard"}
        onPinned={highlightPin}
      />
      <EditPinDrawer
        pinId={editingPinId}
        onClose={() => setEditingPinId(null)}
      />
      <CreateDashboardSheet
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
      <EditDashboardDrawer
        slug={manageSlug}
        onClose={() => setManageSlug(null)}
      />
    </div>
  );
}

function EmptyState({ onAddClick }: { onAddClick: () => void }) {
  return (
    <div className="mx-auto max-w-2xl rounded-lg border border-dashed border-surface-border bg-surface-raised p-10 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent/10">
        <LayoutDashboard size={22} className="text-accent" />
      </div>
      <h2 className="mb-2 text-[16px] font-semibold text-text">No widgets yet</h2>
      <p className="mb-6 text-[13px] text-text-muted">
        Pin widgets here from a channel, or build them from scratch in the developer panel.
      </p>
      <div className="flex justify-center gap-2">
        <button
          type="button"
          onClick={onAddClick}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90 transition-opacity"
        >
          <Plus size={13} />
          Add from channel
        </button>
        <Link
          to="/widgets/dev#tools"
          className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-[12px] font-medium text-text-muted hover:bg-surface-overlay transition-colors"
        >
          <Wrench size={13} />
          Open developer panel
        </Link>
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-40 animate-pulse rounded-lg border border-surface-border bg-surface-raised"
        />
      ))}
    </div>
  );
}
