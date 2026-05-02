/**
 * OmniPanel — channel workbench side panel.
 *
 *   Notes:   rich Markdown notes over the active knowledge base.
 *   Widgets: artifacts explicitly marked for the chat shelf.
 *   Files:   workspace/project file browser.
 *
 * Editing happens on the full workbench page (`/widgets/channel/:id`). Chat
 * intentionally has one widget surface: the chat shelf.
 */
import { useCallback, useEffect, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  FolderOpen,
  Layers,
  MessageCircle,
  NotebookText,
  Plus,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { FilesTabPanel } from "./FilesTabPanel";
import { NotesTabPanel } from "./NotesTabPanel";
import { SessionsTabPanel } from "./SessionsTabPanel";
import type { ChannelSessionSurface } from "@/src/lib/channelSessionSurfaces";
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
  ProjectSummary,
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
  onSelectFile: (path: string, options?: { split?: boolean }) => void;
  onOpenTerminal?: (workspaceRelativePath: string) => void;
  onClose: () => void;
  width?: number;
  fullWidth?: boolean;
  /** Mobile bottom-sheet mode: swap stacked layout for Files/Widgets tabs. */
  mobileTabs?: boolean;
  activeTab?: OmniPanelTab;
  onTabChange?: (tab: OmniPanelTab) => void;
  /** When the channel belongs to a Project, the Sessions tab also surfaces
   *  sibling channels as quick links. */
  project?: ProjectSummary | null;
  /** Activate a session surface from the Sessions tab. When omitted the
   *  panel falls back to direct route navigation. */
  onActivateSessionSurface?: (surface: ChannelSessionSurface) => void;
}

/** Top-to-bottom, then left-to-right — matches the dashboard scan order so
 *  the workbench reads predictably even when it flattens dashboard zones. */
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

function uniquePins(pins: WidgetDashboardPin[]): WidgetDashboardPin[] {
  const seen = new Set<string>();
  const out: WidgetDashboardPin[] = [];
  for (const pin of pins) {
    if (seen.has(pin.id)) continue;
    seen.add(pin.id);
    out.push(pin);
  }
  return out;
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
  onOpenTerminal,
  onClose: _onClose,
  width = 300,
  fullWidth = false,
  mobileTabs = false,
  activeTab: controlledTab,
  onTabChange,
  project = null,
  onActivateSessionSurface,
}: OmniPanelProps) {
  const t = useThemeTokens();
  const navigate = useNavigate();

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
  // Chrome (borderless / hover-scrollbars) is a per-workbench preference,
  // so shelf artifacts mirror the channel workbench's render settings.
  const chrome = useMemo(
    () => resolveChrome(dashboardRow?.grid_config ?? null),
    [dashboardRow?.grid_config],
  );

  // Chat has one widget surface: explicit chat-shelf artifacts. Legacy
  // rail/header/dock pins are folded into the rail bucket by the hook.
  const { rail: railBucket } = useChannelChatZones(channelId);
  const railPins = useMemo(
    () => uniquePins(railBucket).sort(sortByGridYX),
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
      onOpenTerminal={onOpenTerminal}
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
    if (mobileTabs && selectedTab === "notes") setTab("sessions");
  }, [hasWorkspace, mobileTabs, selectedTab, setTab]);

  const activeTab: OmniPanelTab = hasWorkspace
    ? mobileTabs && selectedTab === "notes"
      ? "sessions"
      : selectedTab
    : selectedTab === "files" || selectedTab === "notes"
      ? "widgets"
      : selectedTab;

  const activateSessionSurface = useCallback(
    (surface: ChannelSessionSurface) => {
      if (onActivateSessionSurface) {
        onActivateSessionSurface(surface);
        return;
      }
      if (surface.kind === "primary") {
        navigate(`/channels/${encodeURIComponent(channelId)}`);
        return;
      }
      navigate(
        `/channels/${encodeURIComponent(channelId)}/session/${encodeURIComponent(surface.sessionId)}` +
          (surface.kind === "scratch" ? "?scratch=true" : ""),
      );
    },
    [channelId, navigate, onActivateSessionSurface],
  );

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={fullWidth ? { flex: 1 } : { width, flexShrink: 0 }}
    >
      <div className="flex min-w-0 items-center gap-1.5 px-2 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto overflow-y-hidden scroll-subtle">
          <WorkbenchNavButton
            label="Sessions"
            icon={<MessageCircle size={13} />}
            active={activeTab === "sessions"}
            onClick={() => setTab("sessions")}
            priority="primary"
          />
          {hasWorkspace && !mobileTabs && (
            <WorkbenchNavButton
              label="Notes"
              icon={<NotebookText size={13} />}
              active={activeTab === "notes"}
              onClick={() => setTab("notes")}
              priority="secondary"
            />
          )}
          <WorkbenchNavButton
            label="Widgets"
            icon={<Layers size={13} />}
            active={activeTab === "widgets"}
            onClick={() => setTab("widgets")}
            count={railPins.length}
            priority="secondary"
          />
          {hasWorkspace && (
            <WorkbenchNavButton
              label="Files"
              icon={<FolderOpen size={13} />}
              active={activeTab === "files"}
              onClick={() => setTab("files")}
              priority="secondary"
            />
          )}
        </div>
      </div>

      {activeTab === "sessions" ? (
        <div className="flex-1 min-h-0 overflow-hidden">
          <SessionsTabPanel
            channelId={channelId}
            botId={botId}
            channelLabel={channelDisplayName ?? null}
            project={project}
            onActivateSurface={activateSessionSurface}
          />
        </div>
      ) : activeTab === "notes" && hasWorkspace ? (
        <div className="flex-1 min-h-0 overflow-hidden">
          <NotesTabPanel channelId={channelId} botId={botId} onSelectFile={onSelectFile} />
        </div>
      ) : activeTab === "files" && hasWorkspace ? (
        <div className="flex-1 min-h-0 overflow-hidden">{filesSection}</div>
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
        Mark an artifact as shown in chat shelf to keep it beside this conversation.
      </span>
      <Link
        to={dashboardHref}
        className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1 text-[11px] font-medium text-text-muted hover:bg-surface-overlay transition-colors"
      >
        <Plus size={11} />
        Open channel workbench
      </Link>
    </div>
  );
}

function WorkbenchNavButton({
  label,
  icon,
  active,
  onClick,
  count,
  priority,
}: {
  label: string;
  icon?: React.ReactNode;
  active: boolean;
  onClick: () => void;
  count?: number;
  priority: "primary" | "secondary";
}) {
  const isPrimary = priority === "primary";
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={[
        "relative inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-md border-0 bg-transparent text-[12px] font-semibold transition-colors",
        active
          ? "bg-surface-overlay/80 text-text"
          : isPrimary
            ? "text-text-muted hover:bg-surface-overlay/60 hover:text-text"
            : "text-text-dim hover:bg-surface-overlay/45 hover:text-text-muted",
        isPrimary ? "min-w-[78px] px-2.5" : "min-w-8 px-2",
      ].join(" ")}
      aria-pressed={active}
    >
      {icon && <span className="shrink-0 flex items-center">{icon}</span>}
      <span className={isPrimary ? "" : "sr-only"}>{label}</span>
      {typeof count === "number" && count > 0 && (
        <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] tabular-nums text-text-dim">
          {count}
        </span>
      )}
    </button>
  );
}
