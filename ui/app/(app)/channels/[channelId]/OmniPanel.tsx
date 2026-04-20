/**
 * OmniPanel — dual-section left side panel for a channel.
 *
 *   Top:    File explorer (collapsible, only when a workspace exists)
 *   Divider
 *   Bottom: Widgets — a scaled view onto the leftmost half ("rail zone")
 *           of the channel's full dashboard. Pins keep their dashboard grid
 *           coordinates; we render them in a CSS-Grid templated to
 *           `railZoneCols` columns so relative position and size round-trip
 *           between the dashboard and the sidebar.
 *
 * Editing happens on the full dashboard page (`/widgets/channel/:id`).
 * The OmniPanel is read-only; one source of truth.
 */
import { useCallback, useEffect, useMemo, useRef } from "react";
import { Link } from "react-router-dom";
import {
  Layers,
  LayoutDashboard,
  Plus,
  Search,
} from "lucide-react";
import { CommandPaletteContent } from "@/src/components/layout/CommandPalette";
import {
  Responsive,
  WidthProvider,
  type Layout,
  type LayoutItem,
} from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
import { useThemeTokens } from "@/src/theme/tokens";
import { FilesTabPanel } from "./FilesTabPanel";
import { PinnedToolWidget } from "./PinnedToolWidget";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useDashboards, channelSlug } from "@/src/stores/dashboards";
import { useUIStore } from "@/src/stores/ui";
import { resolveChrome, resolvePreset, type DashboardChrome, type GridPreset } from "@/src/lib/dashboardGrid";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import type {
  GridLayoutItem,
  PinnedWidget,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";

const ResponsiveGridLayout = WidthProvider(Responsive);
const RAIL_BREAKPOINTS = { lg: 0 } as const;
const RAIL_MARGIN: [number, number] = [0, 12];

interface OmniPanelProps {
  channelId: string;
  workspaceId: string | undefined;
  /** Channel's bot id — threaded into FilesTabPanel so the Memory scope
   *  target resolves to the right bot's memory directory. */
  botId: string | undefined;
  /** Channel display name — fuels the Breadcrumb humanizer. */
  channelDisplayName?: string | null;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onClose: () => void;
  width?: number;
  fullWidth?: boolean;
  /** Mobile bottom-sheet mode: swap stacked layout for Files/Widgets tabs. */
  mobileTabs?: boolean;
}

/** Adapt a dashboard pin row to the PinnedWidget shape `PinnedToolWidget`
 *  accepts. Using dashboard scope inside OmniPanel means the widget shares
 *  storage + broadcast pipeline with the full channel dashboard page. */
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

/** Top-to-bottom, then left-to-right — matches the visual scan order of the
 *  dashboard's left half so the mini-grid reads the same way. */
function sortByGridYX(a: WidgetDashboardPin, b: WidgetDashboardPin): number {
  const al = a.grid_layout as GridLayoutItem | undefined;
  const bl = b.grid_layout as GridLayoutItem | undefined;
  const ay = al?.y ?? a.position;
  const by = bl?.y ?? b.position;
  if (ay !== by) return ay - by;
  const ax = al?.x ?? 0;
  const bx = bl?.x ?? 0;
  if (ax !== bx) return ax - bx;
  return a.position - b.position;
}

export function OmniPanel({
  channelId,
  workspaceId,
  botId,
  channelDisplayName,
  activeFile,
  onSelectFile,
  onClose: _onClose,
  width = 300,
  fullWidth = false,
  mobileTabs: _mobileTabs = false,
}: OmniPanelProps) {
  const t = useThemeTokens();

  const slug = channelSlug(channelId);
  // Hydration trigger — useChannelChatZones re-uses the same store, but we
  // also rely on the loading/error UX that `useDashboardPins` drives for this
  // panel's mount lifecycle elsewhere.
  useDashboardPins(slug);
  const unpinDashboardPin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateDashboardEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const dashboardCurrentSlug = useDashboardPinsStore((s) => s.currentSlug);

  // Resolve the grid preset so the mini-grid uses the same column count and
  // proportions as whatever the user picked on the dashboard page. Channel
  // dashboards are excluded from the tab-bar `list` slice, so use
  // `allDashboards` (unfiltered) for this lookup.
  const { allDashboards } = useDashboards();
  const dashboardRow = allDashboards.find((d) => d.slug === slug);
  const preset = useMemo(
    () => resolvePreset(dashboardRow?.grid_config ?? null),
    [dashboardRow?.grid_config],
  );
  // Chrome (borderless / hover-scrollbars) is a per-dashboard preference,
  // so the rail mirrors whatever the channel dashboard is configured for.
  const chrome = useMemo(
    () => resolveChrome(dashboardRow?.grid_config ?? null),
    [dashboardRow?.grid_config],
  );

  // The rail subset: any pin whose left edge sits in the leftmost
  // `railZoneCols` columns. Resolved via the shared zone classifier so OmniPanel
  // shares one source of truth with WidgetDockRight + ChannelHeaderChip.
  const { rail: railBucket } = useChannelChatZones(channelId);
  const railPins = useMemo(
    () => [...railBucket].sort(sortByGridYX),
    [railBucket],
  );

  // Auto-hydrate when the slug we want differs from the one the store is
  // currently showing (e.g. after user bounced through /widgets/default).
  useEffect(() => {
    if (dashboardCurrentSlug !== slug) {
      void useDashboardPinsStore.getState().hydrate(slug);
    }
  }, [dashboardCurrentSlug, slug]);

  const handleUnpin = useCallback(
    async (pinId: string) => {
      try {
        await unpinDashboardPin(pinId);
      } catch (err) {
        console.error("Failed to unpin channel widget:", err);
      }
    },
    [unpinDashboardPin],
  );

  const handleEnvelopeUpdate = useCallback(
    (pinId: string, envelope: ToolResultEnvelope) =>
      updateDashboardEnvelope(pinId, envelope),
    [updateDashboardEnvelope],
  );

  const hasWorkspace = !!workspaceId;
  const hasWidgets = railPins.length > 0;
  const dashboardHref = `/widgets/channel/${encodeURIComponent(channelId)}`;

  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  const widgetsSection = (
    <WidgetsSection
      railPins={railPins}
      hasWidgets={hasWidgets}
      preset={preset}
      chrome={chrome}
      handleUnpin={handleUnpin}
      handleEnvelopeUpdate={handleEnvelopeUpdate}
      applyLayout={applyLayout}
      dashboardHref={dashboardHref}
      t={t}
    />
  );

  const filesSection = hasWorkspace ? (
    <FilesTabPanel
      channelId={channelId}
      botId={botId}
      workspaceId={workspaceId}
      channelDisplayName={channelDisplayName}
      activeFile={activeFile}
      onSelectFile={onSelectFile}
      focusSearchOnMount={false}
    />
  ) : null;

  // Single unified tabbed layout (desktop + mobile bottom sheet both use it).
  // Widgets/Files segmented, one section visible at a time. Default tab =
  // Widgets — primary reason to open this panel. Persisted via the UIStore
  // so the last-used tab sticks + external actions (⌘⇧B, header browse
  // button) can flip the tab via `setOmniPanelTab`/`requestFilesFocus`.
  const tab = useUIStore((s) => s.omniPanelTab);
  const setTab = useUIStore((s) => s.setOmniPanelTab);
  useEffect(() => {
    if (!hasWorkspace && tab === "files") setTab("widgets");
  }, [hasWorkspace, tab, setTab]);

  const activeTab = hasWorkspace ? tab : tab === "files" ? "widgets" : tab;

  return (
    <div
      className={
        "flex flex-col h-full overflow-hidden" +
        (fullWidth ? "" : " rounded-lg border border-surface-border/50")
      }
      style={{
        ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
        backgroundColor: t.surfaceRaised,
      }}
    >
      <div
        className="flex items-center gap-0.5 px-1.5 pt-1.5 pb-1.5"
        style={{ borderBottom: `1px solid ${t.surfaceBorder}55` }}
      >
        <TabButton
          label="Widgets"
          active={activeTab === "widgets"}
          onClick={() => setTab("widgets")}
          count={railPins.length}
          compact
          t={t}
        />
        {hasWorkspace && (
          <TabButton
            label="Files"
            active={activeTab === "files"}
            onClick={() => setTab("files")}
            compact
            t={t}
          />
        )}
        <TabButton
          label="Jump"
          icon={<Search size={11} />}
          active={activeTab === "jump"}
          onClick={() => setTab("jump")}
          compact
          t={t}
        />
        {activeTab === "widgets" && (
          <Link
            to={dashboardHref}
            aria-label="Open channel dashboard"
            title="Open channel dashboard"
            className="ml-auto flex items-center justify-center w-6 h-6 rounded-md transition-colors"
            style={{
              color: t.textDim,
              opacity: 0.55,
            }}
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
            <LayoutDashboard size={12} />
          </Link>
        )}
      </div>

      {activeTab === "files" && hasWorkspace ? (
        <div className="flex-1 min-h-0 overflow-hidden">{filesSection}</div>
      ) : activeTab === "jump" ? (
        <div className="flex-1 min-h-0 overflow-hidden">
          <CommandPaletteContent variant="inline" />
        </div>
      ) : (
        <div className="flex flex-col flex-1 min-h-0 overflow-y-auto px-2 pb-2 pt-2">
          {hasWidgets ? widgetsSection : <EmptyWidgets dashboardHref={dashboardHref} t={t} />}
        </div>
      )}
    </div>
  );
}

interface WidgetsSectionProps {
  railPins: WidgetDashboardPin[];
  hasWidgets: boolean;
  preset: GridPreset;
  chrome: DashboardChrome;
  handleUnpin: (id: string) => void;
  handleEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  applyLayout: (
    items: Array<{ id: string; x: number; y: number; w: number; h: number }>,
  ) => Promise<void>;
  dashboardHref: string;
  t: ReturnType<typeof useThemeTokens>;
}

function WidgetsSection({
  railPins,
  hasWidgets,
  preset,
  chrome,
  handleUnpin,
  handleEnvelopeUpdate,
  applyLayout,
  dashboardHref,
  t,
}: WidgetsSectionProps) {
  // Debounced commit — reused for both resize (height change) and reorder
  // (y-order change). Uses the pin's stored dashboard x/w so the dashboard's
  // multi-column layout is preserved when the rail writes back. y comes from
  // RGL's compacted layout — in a single-column grid with compactType:vertical,
  // y is already the sequential stacking coordinate, so writing it straight
  // through as the dashboard y is correct.
  const pendingTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
    },
    [],
  );
  const railPinsRef = useRef(railPins);
  railPinsRef.current = railPins;

  const scheduleCommit = useCallback(
    (layout: Layout) => {
      if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
      pendingTimer.current = window.setTimeout(() => {
        const byId = new Map(railPinsRef.current.map((p) => [p.id, p]));
        const updates: Array<{ id: string; x: number; y: number; w: number; h: number }> = [];
        for (const item of layout) {
          const pin = byId.get(item.i);
          if (!pin) continue;
          const gl = pin.grid_layout as GridLayoutItem | undefined;
          const origX = gl?.x ?? 0;
          const origW = Math.max(1, gl?.w ?? 1);
          updates.push({
            id: item.i,
            x: origX,
            y: item.y,
            w: origW,
            h: item.h,
          });
        }
        if (updates.length === 0) return;
        void applyLayout(updates).catch((err) => {
          console.error("Failed to persist rail layout:", err);
        });
      }, 400);
    },
    [applyLayout],
  );

  const layout: LayoutItem[] = useMemo(() => {
    let y = 0;
    return railPins.map((pin) => {
      const gl = pin.grid_layout as GridLayoutItem | undefined;
      const h = Math.max(2, gl?.h ?? preset.defaultTile.h);
      const item: LayoutItem = {
        i: pin.id,
        x: 0,
        y,
        w: 1,
        h,
        minW: 1,
        maxW: 1,
        minH: 2,
      };
      y += h;
      return item;
    });
  }, [railPins, preset]);

  if (!hasWidgets) {
    return <EmptyWidgets dashboardHref={dashboardHref} t={t} />;
  }

  // Single-column RGL grid. Drag via hover-revealed `.widget-drag-handle`
  // (supplied by PinnedToolWidget's railMode), resize via the bottom-right
  // SE handle. Width is locked (minW=maxW=1) — size on the dashboard grid
  // is the source of truth for horizontal span; here we only tweak h + y.
  // Commit is gated on explicit drag/resize stop so the initial mount's
  // layout callback doesn't overwrite the dashboard's saved y values.
  return (
    <div className="w-full omni-panel-grid">
      <ResponsiveGridLayout
        layouts={{ lg: layout }}
        breakpoints={RAIL_BREAKPOINTS}
        cols={{ lg: 1 }}
        rowHeight={preset.rowHeight}
        margin={RAIL_MARGIN}
        isDraggable={true}
        isResizable={true}
        draggableHandle=".widget-drag-handle"
        resizeHandles={["s"]}
        compactType="vertical"
        preventCollision={false}
        onDragStop={(current) => scheduleCommit(current)}
        onResizeStop={(current) => scheduleCommit(current)}
      >
        {railPins.map((pin) => (
          <div key={pin.id} data-pin-id={pin.id} className="min-w-0">
            <PinnedToolWidget
              widget={asPinnedWidget(pin)}
              scope={{ kind: "dashboard" }}
              onUnpin={handleUnpin}
              onEnvelopeUpdate={handleEnvelopeUpdate}
              borderless={chrome.borderless}
              hoverScrollbars={chrome.hoverScrollbars}
              railMode
            />
          </div>
        ))}
      </ResponsiveGridLayout>
    </div>
  );
}

function EmptyWidgets({
  dashboardHref,
  t: _t,
}: {
  dashboardHref: string;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-4 py-8 gap-3">
      <Layers size={22} className="text-text-muted opacity-30" />
      <span className="text-center text-xs leading-relaxed text-text-muted/70">
        Drop widgets into the left half of the channel dashboard to surface them here.
      </span>
      <Link
        to={dashboardHref}
        className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1 text-[11px] font-medium text-text-muted hover:bg-surface-overlay transition-colors"
      >
        <Plus size={11} />
        Open channel dashboard
      </Link>
    </div>
  );
}

function TabButton({
  label,
  icon,
  active,
  onClick,
  count,
  compact = false,
  t,
}: {
  label: string;
  icon?: React.ReactNode;
  active: boolean;
  onClick: () => void;
  count?: number;
  compact?: boolean;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-md transition-colors duration-150 bg-transparent border-0 cursor-pointer"
      style={{
        color: active ? t.text : t.textMuted,
        backgroundColor: active ? t.surfaceOverlay : "transparent",
        fontSize: compact ? 12 : 14,
        fontWeight: 600,
        letterSpacing: 0.2,
        minHeight: compact ? 30 : 40,
        padding: compact ? "0 10px" : "0 12px",
      }}
      aria-pressed={active}
    >
      {icon && <span className="shrink-0 flex items-center">{icon}</span>}
      <span>{label}</span>
      {typeof count === "number" && count > 0 && (
        <span
          className="text-[10px] tabular-nums rounded-full px-1.5 py-0.5"
          style={{
            color: active ? t.accent : t.textMuted,
            backgroundColor: active ? `${t.accent}22` : `${t.textMuted}18`,
          }}
        >
          {count}
        </span>
      )}
    </button>
  );
}
