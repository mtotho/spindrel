/**
 * MobileChannelDrawer — channel-scoped full-height mobile drawer.
 *
 * Replaces the old `MobileOmniSheet` bottom sheet. Opened by the channel
 * header's hamburger, the drawer exposes three tabs:
 *
 *   [Widgets (N)] [Files] [Jump]
 *
 * Widgets: every channel-dashboard pin grouped by zone (Header / Rail /
 *          Dock / Grid), so mobile users see the full dashboard contents
 *          regardless of the zone each pin lives in on desktop.
 *
 * Files:   passes through to `FilesTabPanel`. Tapping a file hands the path
 *          back to the page; the parent owns closing the drawer and opening
 *          the mobile file viewer so dirty-file guards stay coherent.
 *
 * Jump:    the existing `CommandPaletteContent` rendered inline. Default
 *          tab on open so the drawer's default behavior matches today's
 *          hamburger = palette, with zero muscle-memory regression for
 *          users who only use it for navigation.
 *
 * Desktop never mounts this drawer. Non-channel routes keep hamburger =
 * plain `CommandPalette`.
 */
import { useCallback, useEffect, useMemo } from "react";
import ReactDOM from "react-dom";
import { Layers, Search, Files, X, LayoutDashboard } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useUIStore } from "@/src/stores/ui";
import type { OmniPanelTab } from "@/src/stores/ui";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { channelSlug } from "@/src/stores/dashboards";
import { CommandPaletteContent } from "@/src/components/layout/CommandPalette";
import type { PaletteItem } from "@/src/components/palette/types";
import { FilesTabPanel } from "./FilesTabPanel";
import { PinnedToolWidget } from "./PinnedToolWidget";
import type {
  PinnedWidget,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";

interface MobileChannelDrawerProps {
  open: boolean;
  onClose: () => void;
  channelId: string;
  dashboardHref?: string;
  workspaceId: string | undefined;
  fileRootPath?: string | null;
  fileRootLabel?: string;
  botId: string | undefined;
  channelDisplayName?: string | null;
  activeFile: string | null;
  onSelectFile: (workspaceRelativePath: string) => void;
  onOpenTerminal?: (workspaceRelativePath: string) => void;
  activeTab?: OmniPanelTab;
  onTabChange?: (tab: OmniPanelTab) => void;
  expandedWidgetId?: string | null;
  onExpandedWidgetChange?: (widgetId: string | null) => void;
}

function asPinnedWidget(pin: WidgetDashboardPin): PinnedWidget {
  return {
    id: pin.id,
    tool_name: pin.tool_name,
    display_name: pin.display_label ?? pin.tool_name,
    bot_id: pin.source_bot_id ?? "",
    widget_instance_id: pin.widget_instance_id ?? null,
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
    config: pin.widget_config ?? {},
  };
}

function parseChannelIdFromPaletteItem(item: PaletteItem): string | null {
  if (!item.href) return null;
  const match = item.href.match(/^\/channels\/([^/?#]+)/);
  return match?.[1] ?? null;
}

export function MobileChannelDrawer({
  open,
  onClose,
  channelId,
  dashboardHref,
  workspaceId,
  fileRootPath,
  fileRootLabel,
  botId,
  channelDisplayName,
  activeFile,
  onSelectFile,
  onOpenTerminal,
  activeTab: controlledTab,
  onTabChange,
  expandedWidgetId,
  onExpandedWidgetChange,
}: MobileChannelDrawerProps) {
  const t = useThemeTokens();
  const storeTab = useUIStore((s) => s.omniPanelTab);
  const setStoreTab = useUIStore((s) => s.setOmniPanelTab);
  const patchChannelPanelPrefs = useUIStore((s) => s.patchChannelPanelPrefs);
  const tab = controlledTab ?? storeTab;
  const setTab = useCallback(
    (next: OmniPanelTab) => {
      if (onTabChange) onTabChange(next);
      else setStoreTab(next);
    },
    [onTabChange, setStoreTab],
  );

  const slug = channelSlug(channelId);
  // Hydrate the dashboard pins store for this channel — needed by the
  // Widgets tab and by useChannelChatZones (shared store).
  useDashboardPins(slug);
  const { rail, header, dock } = useChannelChatZones(channelId);
  const allPins = useDashboardPinsStore((s) => s.pins);
  const unpin = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);

  // Grid pins aren't in the chat-zone buckets — pull directly from the store.
  const gridPins = useMemo(
    () => allPins.filter((p) => p.zone === "grid"),
    [allPins],
  );

  const totalWidgets = rail.length + header.length + dock.length + gridPins.length;
  const hasWorkspace = !!workspaceId;

  // Lock body scroll while the drawer is open so iOS doesn't leak overscroll
  // bounce into the chat underneath.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  const handleUnpin = useCallback(
    async (pinId: string) => {
      try {
        await unpin(pinId);
      } catch (err) {
        console.error("Failed to unpin from mobile drawer:", err);
      }
    },
    [unpin],
  );

  const handleEnvelopeUpdate = useCallback(
    (pinId: string, envelope: ToolResultEnvelope) => updateEnvelope(pinId, envelope),
    [updateEnvelope],
  );

  const handleSelectFile = useCallback(
    (path: string) => {
      onSelectFile(path);
    },
    [onSelectFile],
  );

  const handleAfterJumpSelect = useCallback(
    (item: PaletteItem) => {
      const targetChannelId = parseChannelIdFromPaletteItem(item);
      if (targetChannelId) {
        patchChannelPanelPrefs(targetChannelId, {
          mobileDrawerOpen: false,
          mobileExpandedWidgetId: null,
        });
      }
      onClose();
    },
    [onClose, patchChannelPanelPrefs],
  );

  // If the user lost file-tab access (no workspace), bounce them off it.
  useEffect(() => {
    if (!hasWorkspace && tab === "files") setTab("jump");
  }, [hasWorkspace, tab, setTab]);

  if (!open || typeof document === "undefined") return null;

  const activeTabWithoutWorkspace = hasWorkspace ? tab : tab === "files" ? "jump" : tab;
  const activeTab = activeTabWithoutWorkspace === "widgets" && totalWidgets === 0
    ? "jump"
    : activeTabWithoutWorkspace;

  return ReactDOM.createPortal(
    <div
      role="dialog"
      aria-label="Channel menu"
      className="fixed inset-0 flex flex-col"
      style={{
        backgroundColor: t.surface,
        zIndex: 10030,
        paddingTop: "env(safe-area-inset-top)",
      }}
    >
      {/* Tab strip — three segmented pills. `Jump` is the default on first
          open so the drawer's ambient behavior = today's palette. */}
      <div
        className="flex items-center gap-1 px-2 py-1.5 border-b"
        style={{ borderColor: t.surfaceBorder }}
      >
        <DrawerTab
          label="Widgets"
          icon={<Layers size={13} />}
          count={totalWidgets}
          active={activeTab === "widgets"}
          onClick={() => setTab("widgets")}
          t={t}
        />
        {hasWorkspace && (
          <DrawerTab
            label="Files"
            icon={<Files size={13} />}
            active={activeTab === "files"}
            onClick={() => setTab("files")}
            t={t}
          />
        )}
        <DrawerTab
          label="Jump"
          icon={<Search size={13} />}
          active={activeTab === "jump"}
          onClick={() => setTab("jump")}
          t={t}
        />
        <button
          type="button"
          onClick={onClose}
          aria-label="Close menu"
          className="ml-auto flex items-center justify-center w-9 h-9 rounded-md"
          style={{ color: t.textDim }}
        >
          <X size={18} />
        </button>
      </div>

      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        {activeTab === "widgets" && (
          <WidgetsTab
            channelId={channelId}
            dashboardHref={dashboardHref}
            rail={rail}
            header={header}
            dock={dock}
            grid={gridPins}
            onUnpin={handleUnpin}
            onEnvelopeUpdate={handleEnvelopeUpdate}
            onClose={onClose}
            expandedWidgetId={expandedWidgetId ?? null}
            onExpandedWidgetChange={onExpandedWidgetChange}
          />
        )}
        {activeTab === "files" && hasWorkspace && (
          <FilesTabPanel
            channelId={channelId}
            botId={botId}
            workspaceId={workspaceId}
            rootPath={fileRootPath}
            rootLabel={fileRootLabel}
            channelDisplayName={channelDisplayName}
            activeFile={activeFile}
            onSelectFile={handleSelectFile}
            onOpenTerminal={onOpenTerminal}
            focusSearchOnMount={false}
          />
        )}
        {activeTab === "jump" && (
          <CommandPaletteContent
            variant="modal"
            autoFocus
            onAfterSelect={handleAfterJumpSelect}
            onEscape={onClose}
            showInlineClose={false}
          />
        )}
      </div>
    </div>,
    document.body,
  );
}

interface WidgetsTabProps {
  channelId: string;
  dashboardHref?: string;
  rail: WidgetDashboardPin[];
  header: WidgetDashboardPin[];
  dock: WidgetDashboardPin[];
  grid: WidgetDashboardPin[];
  onUnpin: (id: string) => void;
  onEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  onClose: () => void;
  expandedWidgetId: string | null;
  onExpandedWidgetChange?: (widgetId: string | null) => void;
}

function WidgetsTab({
  channelId,
  dashboardHref,
  rail,
  header,
  dock,
  grid,
  onUnpin,
  onEnvelopeUpdate,
  onClose,
  expandedWidgetId,
  onExpandedWidgetChange,
}: WidgetsTabProps) {
  const t = useThemeTokens();
  const total = rail.length + header.length + dock.length + grid.length;
  if (total === 0) {
    return <EmptyWidgetsMessage channelId={channelId} dashboardHref={dashboardHref} />;
  }
  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 flex flex-col gap-4">
      {/* Render header pins as chips (matching their desktop form). Full-tile
          rendering inflated them into big empty blocks with only the inner
          chip's content centered inside — the subtitle reads "Chips shown
          above the chat", so the mobile form should look like a chip too. */}
      <ZoneSection
        title="Header"
        subtitle="Chips shown above the chat"
        pins={header}
        channelId={channelId}
        chipMode
        onUnpin={onUnpin}
        onEnvelopeUpdate={onEnvelopeUpdate}
        expandedWidgetId={expandedWidgetId}
        onExpandedWidgetChange={onExpandedWidgetChange}
      />
      <ZoneSection
        title="Rail"
        subtitle="Left sidebar widgets"
        pins={rail}
        channelId={channelId}
        onUnpin={onUnpin}
        onEnvelopeUpdate={onEnvelopeUpdate}
        expandedWidgetId={expandedWidgetId}
        onExpandedWidgetChange={onExpandedWidgetChange}
      />
      <ZoneSection
        title="Dock"
        subtitle="Right-side widgets"
        pins={dock}
        channelId={channelId}
        onUnpin={onUnpin}
        onEnvelopeUpdate={onEnvelopeUpdate}
        expandedWidgetId={expandedWidgetId}
        onExpandedWidgetChange={onExpandedWidgetChange}
      />
      <ZoneSection
        title="Grid"
        subtitle="Full channel dashboard"
        pins={grid}
        channelId={channelId}
        onUnpin={onUnpin}
        onEnvelopeUpdate={onEnvelopeUpdate}
        expandedWidgetId={expandedWidgetId}
        onExpandedWidgetChange={onExpandedWidgetChange}
      />
      <a
        href={dashboardHref ?? `/widgets/channel/${encodeURIComponent(channelId)}`}
        onClick={onClose}
        className="mt-1 mb-2 flex items-center justify-center gap-2 rounded-md px-3 py-2.5 text-[12px] font-medium border"
        style={{
          color: t.textMuted,
          borderColor: t.surfaceBorder,
          backgroundColor: t.surfaceRaised,
        }}
      >
        <LayoutDashboard size={14} />
        Open in dashboard
      </a>
    </div>
  );
}

interface ZoneSectionProps {
  title: string;
  subtitle: string;
  pins: WidgetDashboardPin[];
  channelId: string;
  chipMode?: boolean;
  onUnpin: (id: string) => void;
  onEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  expandedWidgetId: string | null;
  onExpandedWidgetChange?: (widgetId: string | null) => void;
}

function ZoneSection({
  title,
  subtitle,
  pins,
  channelId,
  chipMode = false,
  onUnpin,
  onEnvelopeUpdate,
  expandedWidgetId,
  onExpandedWidgetChange,
}: ZoneSectionProps) {
  const t = useThemeTokens();
  if (pins.length === 0) return null;
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <h3
          className="text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: t.textDim }}
        >
          {title}
        </h3>
        <span
          className="text-[10px]"
          style={{ color: t.textMuted, opacity: 0.55 }}
        >
          {subtitle}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        {pins.map((p) => {
          const expanded = expandedWidgetId === p.id;
          return (
            <div
              key={p.id}
              className="rounded-lg border overflow-hidden"
              style={{
                borderColor: expanded ? `${t.accent}66` : t.surfaceBorder,
                background: expanded ? t.surfaceRaised : "transparent",
              }}
            >
              <button
                type="button"
                onClick={() => onExpandedWidgetChange?.(expanded ? null : p.id)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
                style={{ color: expanded ? t.text : t.textMuted }}
              >
                <span className="min-w-0 truncate text-[12px] font-medium">
                  {p.display_label ?? p.envelope?.display_label ?? p.tool_name}
                </span>
                <span
                  className="shrink-0 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider"
                  style={{
                    color: expanded ? t.accent : t.textDim,
                    background: expanded ? `${t.accent}1f` : t.surfaceOverlay,
                  }}
                >
                  {expanded ? "Open" : title}
                </span>
              </button>
              {expanded && (
                <div className={chipMode ? "px-3 pb-3" : "px-2 pb-2"}>
                  <PinnedToolWidget
                    widget={asPinnedWidget(p)}
                    scope={
                      chipMode
                        ? { kind: "channel", channelId, compact: "chip" }
                        : { kind: "dashboard", channelId }
                    }
                    onUnpin={onUnpin}
                    onEnvelopeUpdate={onEnvelopeUpdate}
                    panelSurface={!chipMode}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function EmptyWidgetsMessage({
  channelId,
  dashboardHref,
}: {
  channelId: string;
  dashboardHref?: string;
}) {
  const t = useThemeTokens();
  return (
    <div
      className="flex-1 flex flex-col items-center justify-center gap-3 px-8 text-center"
      style={{ color: t.textDim }}
    >
      <Layers size={22} className="opacity-40" />
      <p className="text-[12px] leading-relaxed opacity-70">
        No widgets pinned yet. Open this channel on desktop and use the
        dashboard editor to add widgets.
      </p>
      <a
        href={dashboardHref ?? `/widgets/channel/${encodeURIComponent(channelId)}`}
        className="text-[12px] underline opacity-80"
        style={{ color: t.accent }}
      >
        Open channel dashboard
      </a>
    </div>
  );
}

function DrawerTab({
  label,
  icon,
  count,
  active,
  onClick,
  t,
}: {
  label: string;
  icon: React.ReactNode;
  count?: number;
  active: boolean;
  onClick: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-md transition-colors duration-150"
      style={{
        color: active ? t.text : t.textMuted,
        backgroundColor: active ? t.surfaceOverlay : "transparent",
        fontSize: 13,
        fontWeight: 600,
        letterSpacing: 0.2,
        minHeight: 36,
        padding: "0 12px",
      }}
      aria-pressed={active}
    >
      <span className="shrink-0 flex items-center">{icon}</span>
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
