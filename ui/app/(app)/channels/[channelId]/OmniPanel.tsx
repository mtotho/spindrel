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
  ChevronLeft,
  Layers,
  MessageCircle,
  NotebookText,
  Plus,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { FilesTabPanel } from "./FilesTabPanel";
import { NotesTabPanel } from "./NotesTabPanel";
import { SessionsTabPanel } from "./SessionsTabPanel";
import {
  useChannelSessionCatalog,
  useResetScratchSession,
} from "@/src/api/hooks/useChannelSessions";
import {
  getChannelSessionMeta,
  type ChannelSessionCatalogItem,
} from "@/src/lib/channelSessionSurfaces";
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
  onCollapse?: () => void;
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
  onCollapse,
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

  const showSessionPulse = activeTab !== "sessions" && !mobileTabs;

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={fullWidth ? { flex: 1 } : { width, flexShrink: 0 }}
    >
      <div className="flex items-center gap-1.5 px-2 py-2">
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
            priority="primary"
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
            active={activeTab === "files"}
            onClick={() => setTab("files")}
            priority="secondary"
          />
        )}
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

      {showSessionPulse && (
        <SessionPulse
          channelId={channelId}
          botId={botId}
          channelLabel={channelDisplayName ?? null}
          onActivateSurface={activateSessionSurface}
          onOpenSessions={() => setTab("sessions")}
        />
      )}

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
      className={[
        "relative inline-flex h-8 items-center gap-1.5 rounded-md border-0 bg-transparent px-2.5 text-[12px] font-semibold transition-colors",
        active
          ? "bg-accent/[0.08] text-text before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[3px] before:-translate-y-1/2 before:rounded-full before:bg-accent"
          : isPrimary
            ? "text-text-muted hover:bg-surface-overlay/60 hover:text-text"
            : "text-text-dim hover:bg-surface-overlay/45 hover:text-text-muted",
        isPrimary ? "min-w-[78px]" : "px-2",
      ].join(" ")}
      aria-pressed={active}
    >
      {icon && <span className="shrink-0 flex items-center">{icon}</span>}
      <span>{label}</span>
      {typeof count === "number" && count > 0 && (
        <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] tabular-nums text-text-dim">
          {count}
        </span>
      )}
    </button>
  );
}

function SessionPulse({
  channelId,
  botId,
  channelLabel,
  onActivateSurface,
  onOpenSessions,
}: {
  channelId: string;
  botId?: string;
  channelLabel?: string | null;
  onActivateSurface: (surface: ChannelSessionSurface) => void;
  onOpenSessions: () => void;
}) {
  const { data: catalog } = useChannelSessionCatalog(channelId);
  const resetScratch = useResetScratchSession();
  const rows = useMemo(() => {
    const items = catalog ?? [];
    const current = items.find((row) => row.is_current) ?? null;
    const rest = items.filter((row) => row !== current);
    return [current, ...rest].filter(Boolean).slice(0, 3) as ChannelSessionCatalogItem[];
  }, [catalog]);

  const createSession = useCallback(async () => {
    if (!botId) return;
    const next = await resetScratch.mutateAsync({
      parent_channel_id: channelId,
      bot_id: botId,
    });
    onActivateSurface({ kind: "scratch", sessionId: next.session_id });
  }, [botId, channelId, onActivateSurface, resetScratch]);

  if (rows.length === 0) return null;

  return (
    <div className="mx-2 mb-1 rounded-md bg-surface-raised/55 px-2.5 py-2">
      <div className="mb-1.5 flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
            Active sessions
          </div>
          <div className="truncate text-[11px] text-text-dim">
            {channelLabel ? `#${channelLabel}` : "This channel"}
          </div>
        </div>
        <button
          type="button"
          onClick={createSession}
          disabled={!botId || resetScratch.isPending}
          className="rounded-md px-2 py-1 text-[11px] font-medium text-accent transition-colors hover:bg-accent/[0.08] disabled:opacity-40"
        >
          New
        </button>
        <button
          type="button"
          onClick={onOpenSessions}
          className="rounded-md px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-surface-overlay/60 hover:text-text"
        >
          All
        </button>
      </div>
      <div className="flex flex-col gap-1">
        {rows.map((row) => {
          const isPrimary = row.surface_kind === "channel" && row.is_active;
          const title = row.label?.trim() || (isPrimary ? "Main chat" : "Untitled session");
          const surface: ChannelSessionSurface = isPrimary
            ? { kind: "primary" }
            : {
                kind: row.surface_kind === "scratch" ? "scratch" : "channel",
                sessionId: row.session_id,
              };
          return (
            <button
              key={row.session_id}
              type="button"
              onClick={() => onActivateSurface(surface)}
              className={[
                "relative flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                row.is_current
                  ? "bg-accent/[0.08] text-text before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[3px] before:-translate-y-1/2 before:rounded-full before:bg-accent"
                  : "text-text-muted hover:bg-surface-overlay/55 hover:text-text",
              ].join(" ")}
            >
              <span className="min-w-0 flex-1 truncate text-[12px] font-medium">
                {title}
              </span>
              <span className="shrink-0 text-[10px] text-text-dim">
                {getChannelSessionMeta(row)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
