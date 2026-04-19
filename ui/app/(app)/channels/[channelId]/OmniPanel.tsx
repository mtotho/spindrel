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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  LayoutDashboard,
  Layers,
  Plus,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { ChannelFileExplorer } from "./ChannelFileExplorer";
import { PinnedToolWidget } from "./PinnedToolWidget";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useDashboards, channelSlug } from "@/src/stores/dashboards";
import { resolvePreset, type GridPreset } from "@/src/lib/dashboardGrid";
import { isRailPin } from "@/app/(app)/widgets/index";
import type {
  GridLayoutItem,
  PinnedWidget,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";

interface OmniPanelProps {
  channelId: string;
  workspaceId: string | undefined;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onBrowseFiles: () => void;
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

/** Translate a pin's dashboard coords into CSS-Grid placement within the
 *  rail-zone mini-grid. Pins that overhang past the zone right edge are
 *  clipped (loose inclusion rule per the design spec). */
function gridPlacement(
  pin: WidgetDashboardPin,
  railZoneCols: number,
): { gridColumn: string; gridRow: string } {
  const gl = pin.grid_layout as GridLayoutItem | undefined;
  const x = Math.max(0, gl?.x ?? 0);
  const y = Math.max(0, gl?.y ?? 0);
  const w = Math.max(1, gl?.w ?? 1);
  const h = Math.max(1, gl?.h ?? 1);
  const span = Math.max(1, Math.min(w, railZoneCols - x));
  return {
    gridColumn: `${x + 1} / span ${span}`,
    gridRow: `${y + 1} / span ${h}`,
  };
}

export function OmniPanel({
  channelId,
  workspaceId,
  activeFile,
  onSelectFile,
  onBrowseFiles,
  onClose: _onClose,
  width = 300,
  fullWidth = false,
  mobileTabs = false,
}: OmniPanelProps) {
  const t = useThemeTokens();

  const slug = channelSlug(channelId);
  const { pins } = useDashboardPins(slug);
  const unpinDashboardPin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateDashboardEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const dashboardCurrentSlug = useDashboardPinsStore((s) => s.currentSlug);

  // Resolve the grid preset so the mini-grid uses the same column count and
  // proportions as whatever the user picked on the dashboard page.
  const { list: dashboards } = useDashboards();
  const dashboardRow = dashboards.find((d) => d.slug === slug);
  const preset = useMemo(
    () => resolvePreset(dashboardRow?.grid_config ?? null),
    [dashboardRow?.grid_config],
  );

  // The rail subset: any pin whose left edge sits in the leftmost
  // `railZoneCols` columns. Pins overhanging past the zone get visually
  // clipped on render (loose inclusion).
  const railPins = useMemo(
    () =>
      pins
        .filter((p) => isRailPin(p, preset.railZoneCols))
        .sort(sortByGridYX),
    [pins, preset.railZoneCols],
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

  const widgetsSection = (
    <WidgetsSection
      railPins={railPins}
      hasWidgets={hasWidgets}
      preset={preset}
      handleUnpin={handleUnpin}
      handleEnvelopeUpdate={handleEnvelopeUpdate}
      dashboardHref={dashboardHref}
      t={t}
    />
  );

  const filesSection = hasWorkspace ? (
    <ChannelFileExplorer
      channelId={channelId}
      activeFile={activeFile}
      onSelectFile={onSelectFile}
      onBrowseFiles={onBrowseFiles}
    />
  ) : null;

  // Single unified tabbed layout (desktop + mobile bottom sheet both use it).
  // Widgets/Files segmented, one section visible at a time. Default tab =
  // Widgets — it's the primary reason to open this panel. Last selection
  // persisted in localStorage so opens remember the user's choice globally.
  const [tab, setTabState] = useState<"widgets" | "files">(() => {
    if (typeof window === "undefined") return "widgets";
    const stored = window.localStorage.getItem("spindrel:omniSheetTab");
    return stored === "files" ? "files" : "widgets";
  });
  const setTab = useCallback((next: "widgets" | "files") => {
    setTabState(next);
    try {
      window.localStorage.setItem("spindrel:omniSheetTab", next);
    } catch {
      // Private-browsing / quota exceeded — not actionable, drop silently.
    }
  }, []);
  useEffect(() => {
    if (!hasWorkspace && tab === "files") setTab("widgets");
  }, [hasWorkspace, tab, setTab]);

  const activeTab = hasWorkspace ? tab : "widgets";
  const showWidgetsHeaderLink = activeTab === "widgets";

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={{
        ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
        backgroundColor: t.surfaceRaised,
      }}
    >
      <div
        className="flex items-center gap-1 px-2 pt-2 pb-2"
        style={{ borderBottom: `1px solid ${t.surfaceBorder}55` }}
      >
        <TabButton
          label="Widgets"
          active={activeTab === "widgets"}
          onClick={() => setTab("widgets")}
          count={railPins.length}
          t={t}
        />
        {hasWorkspace && (
          <TabButton
            label="Files"
            active={activeTab === "files"}
            onClick={() => setTab("files")}
            t={t}
          />
        )}
        {showWidgetsHeaderLink && (
          <Link
            to={dashboardHref}
            className="ml-auto inline-flex items-center justify-center w-6 h-6 rounded-md transition-colors duration-150 hover:bg-white/[0.06]"
            aria-label="Edit channel dashboard"
            title="Edit channel dashboard"
          >
            <LayoutDashboard size={12} color={t.textMuted} />
          </Link>
        )}
      </div>

      {activeTab === "files" && hasWorkspace ? (
        <div className="flex-1 min-h-0 overflow-hidden">{filesSection}</div>
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
  handleUnpin: (id: string) => void;
  handleEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  dashboardHref: string;
  t: ReturnType<typeof useThemeTokens>;
}

function WidgetsSection({
  railPins,
  hasWidgets,
  preset,
  handleUnpin,
  handleEnvelopeUpdate,
  dashboardHref,
  t,
}: WidgetsSectionProps) {
  if (!hasWidgets) {
    return <EmptyWidgets dashboardHref={dashboardHref} t={t} />;
  }
  // Mini-grid: columns flex to fill the sidebar width; row height matches
  // the dashboard's `rowHeight` 1:1 so widget content renders at its normal
  // CSS size (text legible, buttons tappable). The layout still honors each
  // pin's `grid_layout.x/y/w/h` — only the column width adapts.
  return (
    <div
      className="grid w-full"
      style={{
        gridTemplateColumns: `repeat(${preset.railZoneCols}, minmax(0, 1fr))`,
        gridAutoRows: `${preset.rowHeight}px`,
        gap: 12,
      }}
    >
      {railPins.map((pin) => (
        <div
          key={pin.id}
          style={gridPlacement(pin, preset.railZoneCols)}
          className="min-w-0 min-h-0"
        >
          <PinnedToolWidget
            widget={asPinnedWidget(pin)}
            scope={{ kind: "dashboard" }}
            onUnpin={handleUnpin}
            onEnvelopeUpdate={handleEnvelopeUpdate}
          />
        </div>
      ))}
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
  active,
  onClick,
  count,
  t,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  count?: number;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 px-3 rounded-md transition-colors duration-150 bg-transparent border-0 cursor-pointer"
      style={{
        color: active ? t.text : t.textMuted,
        backgroundColor: active ? t.surfaceOverlay : "transparent",
        fontSize: 14,
        fontWeight: 600,
        letterSpacing: 0.2,
        minHeight: 40,
      }}
      aria-pressed={active}
    >
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
