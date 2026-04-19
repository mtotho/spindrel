/**
 * OmniPanel — dual-section left side panel for a channel.
 *
 *   Top:    File explorer (collapsible, only when a workspace exists)
 *   Divider
 *   Bottom: Widgets rail — a compact vertical strip of the channel's
 *           dashboard pins anchored to the leftmost grid column. Users
 *           curate which pins appear here by placing them in the "sidebar
 *           rail" band on the full channel dashboard (`/widgets/channel/:id`).
 *
 * The full dashboard page is the single source of truth for channel
 * widgets; the OmniPanel is a view onto its rail subset. No separate
 * storage.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  FolderOpen,
  LayoutDashboard,
  Layers,
  Pin,
  Plus,
} from "lucide-react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useThemeTokens } from "@/src/theme/tokens";
import { ChannelFileExplorer } from "./ChannelFileExplorer";
import { PinnedToolWidget } from "./PinnedToolWidget";
import { usePinnedWidgetsStore } from "@/src/stores/pinnedWidgets";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useDashboards, channelSlug } from "@/src/stores/dashboards";
import { resolvePreset } from "@/src/lib/dashboardGrid";
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
 *  storage + broadcast pipeline with the full channel dashboard page.
 */
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

/** Compare-by-grid sort: top-to-bottom on the dashboard → top-to-bottom in
 *  the rail. Falls back to `position` for pins that haven't been placed on
 *  the grid yet. */
function sortByGridY(a: WidgetDashboardPin, b: WidgetDashboardPin): number {
  const ay = (a.grid_layout as GridLayoutItem | undefined)?.y ?? a.position;
  const by = (b.grid_layout as GridLayoutItem | undefined)?.y ?? b.position;
  if (ay !== by) return ay - by;
  return a.position - b.position;
}

export function OmniPanel({
  channelId,
  workspaceId,
  activeFile,
  onSelectFile,
  onBrowseFiles,
  onClose: _onClose,
  width = 260,
  fullWidth = false,
  mobileTabs = false,
}: OmniPanelProps) {
  const t = useThemeTokens();
  const filesSectionCollapsed = usePinnedWidgetsStore((s) => s.filesSectionCollapsed);
  const widgetsSectionCollapsed = usePinnedWidgetsStore((s) => s.widgetsSectionCollapsed);
  const toggleFilesCollapsed = usePinnedWidgetsStore((s) => s.toggleFilesSectionCollapsed);
  const toggleWidgetsCollapsed = usePinnedWidgetsStore((s) => s.toggleWidgetsSectionCollapsed);

  const slug = channelSlug(channelId);
  const { pins } = useDashboardPins(slug);
  const unpinDashboardPin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateDashboardEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const dashboardCurrentSlug = useDashboardPinsStore((s) => s.currentSlug);

  // Resolve the grid preset so the rail width cutoff matches whatever the
  // user picked on the dashboard page.
  const { list: dashboards } = useDashboards();
  const dashboardRow = dashboards.find((d) => d.slug === slug);
  const preset = useMemo(
    () => resolvePreset(dashboardRow?.grid_config ?? null),
    [dashboardRow?.grid_config],
  );

  // The rail subset: pins anchored to column 0 within the preset's width cap.
  // Sorted top-to-bottom so the OmniPanel reads like a vertical scan of the
  // dashboard's left edge.
  const railPins = useMemo(
    () =>
      pins
        .filter((p) => isRailPin(p, preset.railMaxWidth))
        .sort(sortByGridY),
    [pins, preset.railMaxWidth],
  );
  const railIds = useMemo(() => railPins.map((p) => p.id), [railPins]);

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

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  );

  // Rail drag-reorder is informational only — the dashboard grid's y-order
  // is authoritative (the rail reads sorted-by-y). We keep drag-and-drop
  // for discoverability, but it's a no-op today. Future: rewrite the grid
  // layout to swap y coords.
  const handleDragEnd = useCallback(
    (_event: DragEndEvent) => {
      // No-op: see comment above.
    },
    [],
  );

  const hasWorkspace = !!workspaceId;
  const hasWidgets = railPins.length > 0;
  const dashboardHref = `/widgets/channel/${encodeURIComponent(channelId)}`;

  const widgetsSection = (
    <WidgetsSection
      railPins={railPins}
      railIds={railIds}
      hasWidgets={hasWidgets}
      sensors={sensors}
      handleDragEnd={handleDragEnd}
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
      onCollapseFiles={toggleFilesCollapsed}
    />
  ) : null;

  // ── Mobile tabs layout: Widgets/Files segmented, one section visible. ──
  // Default tab = Widgets (not Files) — the sidebar is the reason people
  // swipe this sheet up. Last selection persisted in localStorage so
  // subsequent opens remember the user's choice globally.
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

  if (mobileTabs) {
    const activeTab = hasWorkspace ? tab : "widgets";
    return (
      <div
        className="flex flex-col h-full overflow-hidden"
        style={{
          ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
          backgroundColor: t.surfaceRaised,
        }}
      >
        {hasWorkspace && (
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
            <TabButton
              label="Files"
              active={activeTab === "files"}
              onClick={() => setTab("files")}
              t={t}
            />
          </div>
        )}

        {activeTab === "files" && hasWorkspace ? (
          <div className="flex-1 min-h-0 overflow-hidden">{filesSection}</div>
        ) : (
          <div className="flex flex-col flex-1 min-h-0">{widgetsSection}</div>
        )}
      </div>
    );
  }

  // ── Desktop stacked layout ──
  const showFilesSection = hasWorkspace && !filesSectionCollapsed;
  const showWidgetsSection = !widgetsSectionCollapsed;

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={{
        ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
        backgroundColor: t.surfaceRaised,
      }}
    >
      {/* ── Files Section ── */}
      {hasWorkspace && (
        <>
          {showFilesSection ? (
            <div className="flex-1 min-h-0 overflow-hidden">{filesSection}</div>
          ) : (
            <CollapsedSectionHeader
              icon={<FolderOpen size={11} color={t.textMuted} />}
              label="Files"
              onClick={toggleFilesCollapsed}
              t={t}
            />
          )}
          <div className="h-px mx-2" style={{ backgroundColor: `${t.surfaceBorder}55` }} />
        </>
      )}

      {/* ── Widgets Section ── */}
      <div
        className="flex flex-col min-h-0"
        style={{ flex: hasWorkspace && showFilesSection ? "none" : 1 }}
      >
        <div className="flex items-center gap-1 px-2.5 h-8">
          <button
            type="button"
            onClick={toggleWidgetsCollapsed}
            className="flex items-center gap-1 flex-1 text-left transition-colors duration-150 hover:text-text"
            aria-expanded={showWidgetsSection}
            aria-controls="omni-widgets-body"
          >
            {showWidgetsSection ? (
              <ChevronDown size={11} color={t.textMuted} />
            ) : (
              <ChevronRight size={11} color={t.textMuted} />
            )}
            <Pin size={11} color={t.textMuted} />
            <span
              className="uppercase tracking-wider"
              style={{ color: t.textMuted, fontSize: 11, fontWeight: 600 }}
            >
              Widgets
            </span>
            {hasWidgets && (
              <span
                className="text-[10px] tabular-nums rounded-full px-1.5 py-0.5"
                style={{
                  color: t.textMuted,
                  backgroundColor: `${t.textMuted}18`,
                }}
              >
                {railPins.length}
              </span>
            )}
          </button>
          <Link
            to={dashboardHref}
            className="inline-flex items-center justify-center w-6 h-6 rounded-md transition-colors duration-150 hover:bg-white/[0.06]"
            aria-label="Open channel dashboard"
            title="Open channel dashboard"
          >
            <LayoutDashboard size={12} color={t.textMuted} />
          </Link>
        </div>

        {showWidgetsSection && (
          hasWidgets ? (
            <div id="omni-widgets-body" className="flex-1 overflow-y-auto px-2 pb-2 space-y-1.5">
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={handleDragEnd}
              >
                <SortableContext items={railIds} strategy={verticalListSortingStrategy}>
                  {railPins.map((pin) => (
                    <PinnedToolWidget
                      key={pin.id}
                      widget={asPinnedWidget(pin)}
                      scope={{ kind: "dashboard" }}
                      onUnpin={handleUnpin}
                      onEnvelopeUpdate={handleEnvelopeUpdate}
                    />
                  ))}
                </SortableContext>
              </DndContext>
            </div>
          ) : (
            <div
              id="omni-widgets-body"
              className="flex-1 flex flex-col items-center justify-center px-4 py-8 gap-3"
            >
              <Layers size={22} style={{ color: t.textMuted, opacity: 0.3 }} />
              <span
                className="text-center text-xs leading-relaxed"
                style={{ color: t.textMuted, opacity: 0.6 }}
              >
                Drop widgets into the left rail on the channel dashboard to surface them here.
              </span>
              <Link
                to={dashboardHref}
                className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1 text-[11px] font-medium text-text-muted hover:bg-surface-overlay transition-colors"
              >
                <Plus size={11} />
                Open channel dashboard
              </Link>
            </div>
          )
        )}
      </div>
    </div>
  );
}

interface WidgetsSectionProps {
  railPins: WidgetDashboardPin[];
  railIds: string[];
  hasWidgets: boolean;
  sensors: ReturnType<typeof useSensors>;
  handleDragEnd: (ev: DragEndEvent) => void;
  handleUnpin: (id: string) => void;
  handleEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  dashboardHref: string;
  t: ReturnType<typeof useThemeTokens>;
}

function WidgetsSection({
  railPins,
  railIds,
  hasWidgets,
  sensors,
  handleDragEnd,
  handleUnpin,
  handleEnvelopeUpdate,
  dashboardHref,
  t,
}: WidgetsSectionProps) {
  return (
    <>
      <div className="flex items-center gap-1 px-2.5 h-8 shrink-0">
        <Pin size={12} color={t.textMuted} />
        <span
          className="flex-1 uppercase tracking-wider"
          style={{ color: t.textMuted, fontSize: 11, fontWeight: 600 }}
        >
          Widgets
        </span>
        {hasWidgets && (
          <span
            className="text-[10px] tabular-nums rounded-full px-1.5 py-0.5"
            style={{
              color: t.textMuted,
              backgroundColor: `${t.textMuted}18`,
            }}
          >
            {railPins.length}
          </span>
        )}
        <Link
          to={dashboardHref}
          className="inline-flex items-center justify-center w-6 h-6 rounded-md transition-colors duration-150 hover:bg-white/[0.06]"
          aria-label="Open channel dashboard"
          title="Open channel dashboard"
        >
          <LayoutDashboard size={12} color={t.textMuted} />
        </Link>
      </div>
      {hasWidgets ? (
        <div className="flex-1 overflow-y-auto px-2 pb-3 space-y-1.5">
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext items={railIds} strategy={verticalListSortingStrategy}>
              {railPins.map((pin) => (
                <PinnedToolWidget
                  key={pin.id}
                  widget={asPinnedWidget(pin)}
                  scope={{ kind: "dashboard" }}
                  onUnpin={handleUnpin}
                  onEnvelopeUpdate={handleEnvelopeUpdate}
                />
              ))}
            </SortableContext>
          </DndContext>
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center px-4 py-8 gap-3">
          <Layers size={24} style={{ color: t.textMuted, opacity: 0.3 }} />
          <span
            className="text-center text-xs leading-relaxed"
            style={{ color: t.textMuted, opacity: 0.6 }}
          >
            Drop widgets into the left rail on the channel dashboard to surface them here.
          </span>
          <Link
            to={dashboardHref}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1 text-[12px] font-medium text-text-muted hover:bg-surface-overlay transition-colors"
          >
            <LayoutDashboard size={12} />
            Open channel dashboard
          </Link>
        </div>
      )}
    </>
  );
}

function CollapsedSectionHeader({
  icon,
  label,
  onClick,
  t,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1 px-2.5 h-7 hover:bg-white/[0.04] transition-colors duration-150"
    >
      <ChevronRight size={11} color={t.textMuted} />
      {icon}
      <span
        className="flex-1 text-left uppercase tracking-wider"
        style={{ color: t.textMuted, fontSize: 11, fontWeight: 600 }}
      >
        {label}
      </span>
    </button>
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
