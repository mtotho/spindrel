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
import { useCallback, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  ChevronLeft,
  Layers,
  LayoutDashboard,
  Plus,
  Search,
} from "lucide-react";
import { CommandPaletteContent } from "@/src/components/layout/CommandPalette";
import { useThemeTokens } from "@/src/theme/tokens";
import { FilesTabPanel } from "./FilesTabPanel";
import { WidgetRailSection } from "./WidgetRailSection";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useDashboards, channelSlug } from "@/src/stores/dashboards";
import { useUIStore } from "@/src/stores/ui";
import type { OmniPanelTab } from "@/src/stores/ui";
import { resolveChrome, resolvePreset } from "@/src/lib/dashboardGrid";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import type {
  GridLayoutItem,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";

interface OmniPanelProps {
  channelId: string;
  dashboardHref?: string;
  workspaceId: string | undefined;
  fileRootPath?: string | null;
  fileRootLabel?: string;
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
  activeTab?: OmniPanelTab;
  onTabChange?: (tab: OmniPanelTab) => void;
  onCollapse?: () => void;
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
  dashboardHref,
  workspaceId,
  fileRootPath,
  fileRootLabel,
  botId,
  channelDisplayName,
  activeFile,
  onSelectFile,
  onClose: _onClose,
  width = 300,
  fullWidth = false,
  mobileTabs: _mobileTabs = false,
  activeTab: controlledTab,
  onTabChange,
  onCollapse,
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
  const resolvedDashboardHref = dashboardHref ?? `/widgets/channel/${encodeURIComponent(channelId)}`;

  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  // Chat-mode rails override the dashboard's saved hover_scrollbars default —
  // the rails are persistent chrome; persistent scrollbars read as admin
  // clutter. The standalone dashboard view still honors the author's choice.
  const railChrome = useMemo(
    () => ({ ...chrome, hoverScrollbars: true }),
    [chrome],
  );
  const widgetsSection = (
    <WidgetRailSection
      channelId={channelId}
      pins={railPins}
      preset={preset}
      chrome={railChrome}
      onUnpin={handleUnpin}
      onEnvelopeUpdate={handleEnvelopeUpdate}
      applyLayout={applyLayout}
      widgetLayout="rail"
    />
  );

  const filesSection = hasWorkspace ? (
    <FilesTabPanel
      channelId={channelId}
      botId={botId}
      workspaceId={workspaceId}
      rootPath={fileRootPath}
      rootLabel={fileRootLabel}
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
  const setStoreTab = useUIStore((s) => s.setOmniPanelTab);
  const setFileExplorerOpen = useUIStore((s) => s.setFileExplorerOpen);
  const selectedTab = controlledTab ?? tab;
  const setTab = useCallback(
    (next: OmniPanelTab) => {
      if (onTabChange) onTabChange(next);
      else setStoreTab(next);
    },
    [onTabChange, setStoreTab],
  );
  useEffect(() => {
    if (!hasWorkspace && selectedTab === "files") setTab("widgets");
  }, [hasWorkspace, selectedTab, setTab]);

  const activeTab = hasWorkspace ? selectedTab : selectedTab === "files" ? "widgets" : selectedTab;

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={fullWidth ? { flex: 1 } : { width, flexShrink: 0 }}
    >
      {/* Tab strip sits bare on the chat surface — no card bg, no bottom
          border. The floating pill buttons provide their own active-state
          contrast. */}
      <div className="flex items-center gap-0.5 px-1.5 pt-1.5 pb-1.5">
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
        {/* Collapse chevron — tucks the panel away; a peek-tab at the
            viewport's left edge brings it back. The dashboard link that
            used to live here is redundant now that the channel header has a
            dedicated Switch-to-Dashboard toggle. */}
        <button
          type="button"
          onClick={() => {
            if (onCollapse) onCollapse();
            else setFileExplorerOpen(false);
          }}
          aria-label="Collapse widgets panel"
          title="Collapse panel"
          className="ml-auto flex items-center justify-center w-6 h-6 rounded-md transition-colors"
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
          <ChevronLeft size={14} />
        </button>
      </div>

      {activeTab === "files" && hasWorkspace ? (
        <div className="flex-1 min-h-0 overflow-hidden">{filesSection}</div>
      ) : activeTab === "jump" ? (
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
          <CommandPaletteContent variant="inline" />
        </div>
      ) : (
        <div className="flex flex-col flex-1 min-h-0 overflow-y-auto scroll-subtle px-2 pb-2 pt-2">
          {hasWidgets ? widgetsSection : <EmptyWidgets dashboardHref={resolvedDashboardHref} t={t} />}
        </div>
      )}
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
