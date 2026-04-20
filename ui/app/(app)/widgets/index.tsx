import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useUIStore } from "@/src/stores/ui";
import { useKioskMode } from "@/src/hooks/useKioskMode";
import { Check, Info, LayoutDashboard, Maximize2, MessageSquare, Minimize2, Move, Plus, RotateCcw, Wrench } from "lucide-react";
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
import { EditModeGridGuides } from "./EditModeGridGuides";
import { ChannelDashboardMultiCanvas } from "./ChannelDashboardMultiCanvas";
import { KioskExitChip } from "./KioskExitChip";
import {
  channelIdFromSlug,
  channelSlug,
  isChannelSlug,
  useDashboards,
} from "@/src/stores/dashboards";
import { resolveChrome, resolvePreset, type DashboardChrome, type GridPreset } from "@/src/lib/dashboardGrid";
import { ChatSession } from "@/src/components/chat/ChatSession";

/** True when a pin currently lives on the chat sidebar rail canvas. Zone
 *  is stored explicitly on the pin; this is a convenience predicate so the
 *  dashboard breadcrumb can count rail pins without re-implementing the
 *  filter. */
export function isRailPin(pin: WidgetDashboardPin): boolean {
  return pin.zone === "rail";
}

const ResponsiveGridLayout = WidthProvider(Responsive);

/** Screen-width breakpoints. `lg` = the canonical multi-column layout the
 *  user designs at. We keep the threshold aligned with the mobile cutoff
 *  (768px) so that typical desktop viewports — including ones with sidebars
 *  and DevTools open — stay on the lg layout instead of falling back to the
 *  narrow single-column stack. Narrower breakpoints only kick in for truly
 *  mobile-sized content areas, which are also blocked from editing. */
const BREAKPOINTS = { lg: 768, md: 480, sm: 320, xs: 200, xxs: 0 } as const;
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
  // `allDashboards` rather than `list` — channel dashboards are filtered out
  // of the tab-bar-friendly `list` slice, but we still need to read their
  // `grid_config` (preset + chrome flags) when rendering `/widgets/channel/<id>`.
  const { allDashboards } = useDashboards();
  const currentDashboard = allDashboards.find((d) => d.slug === slug);
  const preset = useMemo(
    () => resolvePreset(currentDashboard?.grid_config ?? null),
    [currentDashboard?.grid_config],
  );
  const chrome = useMemo(
    () => resolveChrome(currentDashboard?.grid_config ?? null),
    [currentDashboard?.grid_config],
  );
  // Only fetched when we're on a channel dashboard — gives the breadcrumb the
  // channel's real `name` without colliding with the main channel-chat route.
  const { data: channelRow } = useChannel(channelScopedId ?? undefined);
  const enrichRecentPage = useUIStore((s) => s.enrichRecentPage);
  const loc = useLocation();
  useEffect(() => {
    const name = isChannelScoped ? channelRow?.name : currentDashboard?.name;
    if (name) enrichRecentPage(loc.pathname, name);
  }, [currentDashboard?.name, channelRow?.name, isChannelScoped, loc.pathname, enrichRecentPage]);
  const railCount = useMemo(
    () => pins.filter((p) => isRailPin(p)).length,
    [pins],
  );
  /** Panel-mode short-circuit: when the dashboard's `grid_config.layout_mode`
   *  is `'panel'` AND a panel pin exists, the right side becomes the panel
   *  pin and the left becomes a narrow RGL strip with rail-zone pins only.
   *  When the mode is set but no pin carries `is_main_panel` (e.g. the panel
   *  pin was just unpinned), we fall back to grid mode rather than render
   *  an empty main area — the server's delete cascade also flips the mode
   *  back, but the UI guards in case a stale dashboards.list is in flight. */
  const layoutMode = currentDashboard?.grid_config?.layout_mode ?? "grid";
  const panelPin = useMemo(
    () => pins.find((p) => p.is_main_panel) ?? null,
    [pins],
  );
  const inPanelMode = layoutMode === "panel" && panelPin !== null;
  /** While a widget is being dragged in edit mode, this tracks that a
   *  drag is in progress so `EditModeGridGuides` can show its column-index
   *  tick row. The channel dashboard now uses the multi-canvas editor, so
   *  chat-zone bands are gone — guide state is dragging/not-dragging. */
  const [dragging, setDragging] = useState(false);
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

  const { kiosk, enterKiosk, exitKiosk, idle: kioskIdle } = useKioskMode();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  /** Current RGL breakpoint. We only persist layout edits at `lg` — smaller
   *  breakpoints are auto-reflowed by RGL and their coordinates should not
   *  become the canonical `grid_layout` (otherwise narrowing the window in
   *  edit mode corrupts the saved layout for everyone). */
  const [breakpoint, setBreakpoint] = useState<string>("lg");
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
  // Edit gestures allowed at any non-mobile width. The grid guides and layout
  // commits are separately gated to `lg` (see render + onLayoutChange) so that
  // dragging at a narrower breakpoint doesn't corrupt the canonical layout.
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

  /** ChatSession dock — channel mode on channel-scoped widget dashboards.
   *  Mirrors the channel's main chat (same session, same store slot, same SSE).
   *  The dock's Maximize button navigates to `/channels/:channelId`. Not
   *  mounted on global dashboards yet — ephemeral mode there is still blocked
   *  by the streaming / React #185 bugs on the ephemeral path (Track §4.0a/c). */
  const chatDockNoop = useCallback(() => {}, []);

  // `?dock=expanded` — the channel screen's Minimize button navigates here
  // with this flag so the dock opens already expanded (landing continuity).
  // Read once, scrub from the URL on mount so a later refresh doesn't re-open.
  const [searchParams, setSearchParams] = useSearchParams();
  const [initialDockExpanded] = useState(() => searchParams.get("dock") === "expanded");
  useEffect(() => {
    if (searchParams.get("dock") === "expanded") {
      const next = new URLSearchParams(searchParams);
      next.delete("dock");
      setSearchParams(next, { replace: true });
    }
    // Mount-only: subsequent ?dock changes are ignored; they'd only happen if
    // the user manually edited the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

    // For narrower breakpoints, stack widgets single-column full-width
    // sorted by their lg (y, x) position. Prevents RGL from deriving weird
    // half-width/gapped arrangements when widget widths don't divide evenly
    // into the breakpoint's col count.
    const sortedForStack = [...pins]
      .map((p, idx) => ({
        p,
        base: hasLayout(p) ? p.grid_layout : defaultLayoutForIndex(idx, preset),
      }))
      .sort((a, b) => a.base.y - b.base.y || a.base.x - b.base.x);

    const stackFor = (cols: number): LayoutItem[] => {
      let y = 0;
      return sortedForStack.map(({ p, base }) => {
        const item: LayoutItem = {
          i: p.id,
          x: 0,
          y,
          w: cols,
          h: base.h,
          minH: preset.minTile.h,
        };
        y += base.h;
        return item;
      });
    };

    return {
      lg,
      md: stackFor(preset.cols.md),
      sm: stackFor(preset.cols.sm),
      xs: stackFor(preset.cols.xs),
      xxs: stackFor(preset.cols.xxs),
    };
  }, [pins, preset]);

  // Debounce layout commits — drag/resize fires many `onLayoutChange` events.
  const pendingTimer = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
    };
  }, []);

  /** Reset-layout two-click confirm. First click arms the button (swaps to
   *  a danger variant + "Confirm reset?" label) for 4 seconds; a second
   *  click within that window runs the repack. Cleared on click-away or
   *  exiting edit mode so it never lingers across sessions. */
  const [resetArmed, setResetArmed] = useState(false);
  const resetArmTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!editMode && resetArmed) setResetArmed(false);
  }, [editMode, resetArmed]);
  useEffect(() => () => {
    if (resetArmTimer.current) window.clearTimeout(resetArmTimer.current);
  }, []);

  const handleResetLayout = () => {
    if (!resetArmed) {
      setResetArmed(true);
      if (resetArmTimer.current) window.clearTimeout(resetArmTimer.current);
      resetArmTimer.current = window.setTimeout(() => setResetArmed(false), 4000);
      return;
    }
    // Pack every pin via defaultLayoutForIndex — same helper used for pins
    // with no grid_layout, so "Reset" is identical to "pretend every pin
    // was freshly pinned".
    setResetArmed(false);
    if (resetArmTimer.current) window.clearTimeout(resetArmTimer.current);
    const items = pins.map((p, idx) => ({
      id: p.id,
      ...defaultLayoutForIndex(idx, preset),
    }));
    void applyLayout(items)
      .then(() => setLayoutError(null))
      .catch((err) => {
        console.error("Failed to reset layout:", err);
        setLayoutError(err instanceof Error ? err.message : "Failed to reset layout");
      });
  };

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

  const navigate = useNavigate();

  const actions = (
    <>
      {/* Open chat — channel-scoped only. Paired with the Minimize button in
          ChannelHeader so the user can ping-pong between dashboard + chat in
          the same screen region. `?from=dock` cues the chat screen to play an
          entrance animation (reverse of the dock collapse motion). */}
      {isChannelScoped && channelScopedId && !isMobile && (
        <button
          type="button"
          onClick={() => navigate(`/channels/${channelScopedId}?from=dock`)}
          className="inline-flex items-center justify-center w-8 h-8 rounded-md border border-surface-border text-text-muted hover:bg-surface-overlay transition-colors"
          aria-label="Open chat view"
          title="Open chat"
        >
          <MessageSquare size={13} />
        </button>
      )}
      {/* Edit layout — hidden on mobile where the grid is read-only anyway
          (the in-page banner explains why). */}
      {pins.length > 0 && !isMobile && (
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
      {/* Reset layout — only surfaced in edit mode. Two-click confirm so a
          misclick can't accidentally repack a carefully-tuned grid. Uses
          the same `defaultLayoutForIndex` helper as fresh pins, so "reset"
          equals "pretend everything was just pinned". */}
      {editMode && pins.length > 0 && !isMobile && (
        <button
          type="button"
          onClick={handleResetLayout}
          className={
            "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12px] font-medium transition-colors "
            + (resetArmed
              ? "border-danger/60 bg-danger/10 text-danger"
              : "border-surface-border text-text-muted hover:bg-surface-overlay")
          }
          aria-pressed={resetArmed}
          aria-label={resetArmed ? "Confirm reset layout" : "Reset layout"}
          title={
            resetArmed
              ? "Click again to repack every pin. Undo coming in P11-b."
              : "Auto-pack every pin into default positions"
          }
        >
          <RotateCcw size={13} />
          <span className="hidden md:inline">
            {resetArmed ? "Confirm reset?" : "Reset layout"}
          </span>
        </button>
      )}
      {/* Kiosk — presentation mode. Desktop-only (fullscreen API is flaky
          on touch) and hidden while editing so we can't accidentally kiosk
          mid-drag. */}
      {pins.length > 0 && !isMobile && !editMode && (
        <button
          type="button"
          onClick={kiosk ? exitKiosk : enterKiosk}
          className="inline-flex items-center justify-center w-8 h-8 rounded-md border border-surface-border text-text-muted hover:bg-surface-overlay transition-colors"
          aria-label={kiosk ? "Exit kiosk mode" : "Enter kiosk mode"}
          title={kiosk ? "Exit kiosk (Esc)" : "Kiosk (fullscreen presentation)"}
        >
          {kiosk ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
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
      {/* Developer panel — global tool, reached from the sidebar rail. Hidden
          on channel-scoped dashboards to keep the top bar focused on the
          channel's own controls; still rendered on global dashboards where
          it's the fastest path to pin-testing a new widget.
          Carry the active dashboard slug via ?from= so the dev-panel's Pin
          target picker can seed to the board the user came from. */}
      {!isChannelScoped && (
        <Link
          to={`/widgets/dev?from=${encodeURIComponent(slug)}`}
          className="hidden sm:inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2 py-1 text-[12px] font-medium text-text-muted hover:bg-surface-overlay transition-colors"
          aria-label="Developer panel"
          title="Developer panel"
        >
          <Wrench size={13} />
          <span className="hidden lg:inline">Developer panel</span>
        </Link>
      )}
    </>
  );

  return (
    <div
      className={
        "flex-1 flex flex-col bg-surface overflow-hidden "
        + (kiosk && kioskIdle ? "cursor-none" : "")
      }
    >
      {/* Chrome-bars suppressed in kiosk — the page should feel like a
          presentation surface, not a configurable admin tool. */}
      {!kiosk && (isChannelScoped && channelScopedId ? (
        <ChannelDashboardBreadcrumb
          channelId={channelScopedId}
          channelName={channelRow?.name}
          railCount={railCount}
          pinCount={pins.length}
          onOpenManage={() => setManageSlug(slug)}
          right={actions}
        />
      ) : (
        <DashboardTabs
          activeSlug={slug}
          onOpenCreate={() => setCreateOpen(true)}
          onOpenManage={() => setManageSlug(slug)}
          right={actions}
        />
      ))}

      {/* Floating exit chip only visible in kiosk. Consumers outside the
          dashboard route will never see this — the hook's `kiosk` flag is
          URL-scoped. */}
      {kiosk && <KioskExitChip idle={kioskIdle} onExit={exitKiosk} />}

      <div
        className={
          "relative flex-1 p-2 sm:p-4 md:p-6 "
          // Panel mode: the panel pin owns scrolling internally — the
          // wrapper stays clipped so the iframe / interactive component
          // can fill the viewport edge to edge. Grid mode keeps the
          // long-page scroll behavior so tall layouts can be paged
          // through normally.
          + (inPanelMode ? "overflow-hidden flex flex-col min-h-0 " : "overflow-auto ")
          + (layoutEditable && !inPanelMode ? "pb-[40vh]" : "")
        }
      >
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
        {!isLoading && !error && pins.length > 0 && inPanelMode && panelPin && (
          <PanelModeView
            pins={pins}
            panelPin={panelPin}
            preset={preset}
            chrome={chrome}
            highlightPinId={highlightPinId}
            layoutEditable={layoutEditable}
            onUnpin={handleUnpin}
            onEnvelopeUpdate={handleEnvelopeUpdate}
            onEditPin={(id) => setEditingPinId(id)}
          />
        )}
        {!isLoading && !error && pins.length > 0 && !inPanelMode && isChannelScoped && (
          <ChannelDashboardMultiCanvas
            pins={pins}
            preset={preset}
            chrome={chrome}
            editMode={layoutEditable}
            onUnpin={handleUnpin}
            onEnvelopeUpdate={handleEnvelopeUpdate}
            onEditPin={(id) => setEditingPinId(id)}
          />
        )}
        {!isLoading && !error && pins.length > 0 && !inPanelMode && !isChannelScoped && (
          <div className="relative">
            {layoutEditable && breakpoint === "lg" && (
              <EditModeGridGuides
                cols={preset.cols.lg}
                rowHeight={preset.rowHeight}
                rowGap={GRID_MARGIN[1]}
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
              onDragStart={() => setDragging(true)}
              onDragStop={() => setDragging(false)}
              onBreakpointChange={(bp) => setBreakpoint(bp)}
              onLayoutChange={(current) => {
                if (layoutEditable && breakpoint === "lg") scheduleCommit(current);
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
                    borderless={chrome.borderless}
                    hoverScrollbars={chrome.hoverScrollbars}
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
        scopeChannelId={channelScopedId}
      />
      <EditPinDrawer
        pinId={editingPinId}
        onClose={() => setEditingPinId(null)}
        preset={preset}
      />
      <CreateDashboardSheet
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
      <EditDashboardDrawer
        slug={manageSlug}
        onClose={() => setManageSlug(null)}
      />

      {/* ChatSession dock — channel-scoped dashboards only. Streams the same
          chat as the channel's full screen; maximize navigates there. Kiosk +
          mobile omit the dock to keep the presentation / small-screen layouts
          unchanged. */}
      {isChannelScoped && channelScopedId && !kiosk && !isMobile && (
        <ChatSession
          source={{ kind: "channel", channelId: channelScopedId }}
          shape="dock"
          open
          onClose={chatDockNoop}
          title={channelRow?.name ? `#${channelRow.name}` : "Channel chat"}
          initiallyExpanded={initialDockExpanded}
        />
      )}
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

interface PanelModeViewProps {
  pins: WidgetDashboardPin[];
  panelPin: WidgetDashboardPin;
  preset: GridPreset;
  chrome: DashboardChrome;
  highlightPinId: string | null;
  layoutEditable: boolean;
  onUnpin: (pinId: string) => void;
  onEnvelopeUpdate: (pinId: string, envelope: ToolResultEnvelope) => void;
  onEditPin: (pinId: string) => void;
}

/** Two-column layout used when `grid_config.layout_mode === 'panel'`.
 *
 *  - Left: rail-zone pins stacked vertically (no RGL — simple flex column;
 *    drag/resize is meaningful only against a multi-column grid, which we no
 *    longer have here. Reordering moves to the EditPinDrawer if needed
 *    later.)
 *  - Right: the single panel pin, filling the remaining area.
 *
 *  Mobile collapses to a single column with the panel above the rail strip
 *  so the headline content stays first-paint visible. */
function PanelModeView({
  pins,
  panelPin,
  chrome,
  highlightPinId,
  layoutEditable,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
}: PanelModeViewProps) {
  const railPins = useMemo(
    () => pins.filter((p) => p.id !== panelPin.id),
    [pins, panelPin.id],
  );
  return (
    <div className="flex flex-col-reverse lg:flex-row gap-3 h-full">
      {railPins.length > 0 && (
        <div className="lg:w-[320px] lg:shrink-0 flex flex-col gap-3 lg:overflow-y-auto">
          {railPins.map((p) => (
            <div
              key={p.id}
              data-pin-id={p.id}
              className={
                "min-w-0 " + (highlightPinId === p.id ? "pin-flash" : "")
              }
            >
              <PinnedToolWidget
                widget={asPinnedWidget(p)}
                scope={{ kind: "dashboard" }}
                onUnpin={onUnpin}
                onEnvelopeUpdate={onEnvelopeUpdate}
                editMode={layoutEditable}
                onEdit={onEditPin}
                borderless={chrome.borderless}
                hoverScrollbars={chrome.hoverScrollbars}
              />
            </div>
          ))}
        </div>
      )}
      <div
        key={panelPin.id}
        data-pin-id={panelPin.id}
        className={
          "flex-1 min-w-0 min-h-[60vh] lg:min-h-0 flex flex-col "
          + (highlightPinId === panelPin.id ? "pin-flash" : "")
        }
      >
        <PinnedToolWidget
          widget={asPinnedWidget(panelPin)}
          scope={{ kind: "dashboard" }}
          onUnpin={onUnpin}
          onEnvelopeUpdate={onEnvelopeUpdate}
          editMode={layoutEditable}
          onEdit={onEditPin}
          borderless={chrome.borderless}
          hoverScrollbars={chrome.hoverScrollbars}
        />
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
