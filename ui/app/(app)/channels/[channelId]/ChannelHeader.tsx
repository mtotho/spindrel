import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Settings, Menu, ArrowLeft, Hash, Lock, LayoutDashboard,
  Cog, PanelRight, Plug, StickyNote,
  MessageSquare, Code2, Mail, Camera, Tv, Terminal, MessageCircle,
  User as UserIcon, History, RotateCcw, MoreHorizontal,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useUIStore } from "@/src/stores/ui";
import { useActivatableIntegrations, useChannel } from "@/src/api/hooks/useChannels";
import { useIntegrationIcons } from "@/src/api/hooks/useIntegrations";
import { useAdminUsers } from "@/src/api/hooks/useAdminUsers";
import { useIsAdmin } from "@/src/hooks/useScope";
import { useAuthStore } from "@/src/stores/auth";
import { prettyIntegrationName } from "@/src/utils/format";

const INTEGRATION_ICON_MAP: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  MessageSquare, Code2, Mail, Camera, LayoutDashboard, Tv, Terminal, MessageCircle, Plug,
};

export interface ChannelHeaderProps {
  channelId: string;
  displayName: string;
  bot: { id?: string; name?: string; model?: string } | undefined;
  channelModelOverride: string | undefined;
  columns: "single" | "double" | "triple";
  goBack: () => void;
  /** Resolved workspace id from the channel (null when bot has no shared workspace). */
  workspaceId: string | null | undefined;
  explorerOpen: boolean;
  toggleExplorer: () => void;
  onBrowseWorkspace: () => void;
  isMobile: boolean;
  /** Context budget from last SSE stream */
  contextBudget?: { utilization: number; consumed: number; total: number } | null;
  /** Called when user clicks the context budget indicator */
  onContextBudgetClick?: () => void;
  /** Orchestrator / system-control channel — renders SYSTEM pill next to title. */
  isSystemChannel?: boolean;
  /** Findings panel state (awaiting-user-input pipelines). Inline icon shows
   *  only when there's active signal (panel open or count > 0). */
  findingsPanelOpen?: boolean;
  toggleFindingsPanel?: () => void;
  findingsCount?: number;
  /** Open the scratch-chat dock. Button is rendered on every viewport. */
  scratchOpen?: boolean;
  onOpenScratch?: () => void;
  /** When the current URL is the scratch full-page route, the header
   *  grows History + Reset icon buttons so the user can manage the
   *  scratch session from chrome that sits outside the chat column. */
  scratchFullpageMode?: {
    onOpenHistory: () => void;
    onReset: () => void;
    resetArmed: boolean;
    archive?: boolean;
  };
}

export function ChannelHeader({
  channelId,
  displayName,
  bot,
  columns,
  goBack,
  isMobile,
  contextBudget,
  onContextBudgetClick,
  isSystemChannel,
  findingsPanelOpen,
  toggleFindingsPanel,
  findingsCount = 0,
  scratchOpen,
  onOpenScratch,
  scratchFullpageMode,
}: ChannelHeaderProps) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const [mobileOverflowOpen, setMobileOverflowOpen] = React.useState(false);
  const mobileOverflowRef = React.useRef<HTMLDivElement | null>(null);
  // Mobile hamburger opens the channel drawer (Widgets/Files/Jump) rather
  // than the plain command palette — drawer's Jump tab wraps the palette
  // content inline, so channel-route mobile users get one surface with nav
  // + widgets + files all reachable from a single tap.
  const openChannelDrawer = useUIStore((s) => s.setFileExplorerOpen);
  // Mobile-only: the top-right widget button toggles the same drawer but
  // force-pins it to the Widgets tab. Hamburger still opens wherever the
  // user last explicitly navigated (persisted `omniPanelTab`), so the two
  // buttons don't clobber each other.
  const toggleDrawerToWidgets = useUIStore((s) => s.toggleDrawerToWidgets);
  const drawerOpen = useUIStore((s) => s.fileExplorerOpen);
  const drawerTab = useUIStore((s) => s.omniPanelTab);
  const widgetsDrawerActive = isMobile && drawerOpen && drawerTab === "widgets";

  const { data: channelData } = useChannel(channelId);
  const { data: activatable } = useActivatableIntegrations(channelId);
  const { data: iconsData } = useIntegrationIcons();
  const integrationIconNames = iconsData?.icons ?? {};

  // Admin-only: resolve owner display name for the header chip. Non-admins
  // don't see the chip at all (no cross-user visibility signal).
  const isAdmin = useIsAdmin();
  const currentUserId = useAuthStore((s) => s.user?.id);
  const { data: adminUsers } = useAdminUsers(isAdmin);
  const ownerUserId = channelData?.user_id ?? null;
  const ownerName = ownerUserId
    ? adminUsers?.find((u) => u.id === ownerUserId)?.display_name ?? null
    : null;
  const showOwnerChip =
    isAdmin && !!ownerUserId && ownerUserId !== currentUserId && !isSystemChannel;

  const isPrivate = !!channelData?.private;

  const activeIntegrations = (activatable ?? []).filter((ig) => ig.activated);
  const activeTypes = new Set(activeIntegrations.map((ig) => ig.integration_type));
  const boundOnly = (channelData?.integrations ?? []).filter(
    (b) => !activeTypes.has(b.integration_type),
  );

  const fmtTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
    if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
    return String(n);
  };

  const resolveIntegrationIcon = (integrationType: string) => {
    const name = integrationIconNames[integrationType];
    return (name && INTEGRATION_ICON_MAP[name]) || Plug;
  };

  void columns;

  const iconSize = isMobile ? 44 : 36;
  const showDashboardButton = !!channelId && !isSystemChannel;
  const showFindingsButton =
    !!toggleFindingsPanel && (findingsCount > 0 || !!findingsPanelOpen);
  const isScratchArchive = !!scratchFullpageMode?.archive;
  const showScratchState = !!scratchFullpageMode;
  const scratchBadgeLabel = isScratchArchive ? "Archived scratch" : "Scratch pad";
  const scratchTone = isScratchArchive
    ? {
        bg: t.surfaceOverlay,
        border: t.surfaceBorder,
        text: t.textMuted,
        icon: t.textDim,
      }
    : {
        bg: t.warningSubtle,
        border: t.warningBorder,
        text: t.warningMuted,
        icon: t.warning,
      };
  const showFindingsInline = !isMobile && showFindingsButton;
  const showScratchExtrasInline = !isMobile && !!scratchFullpageMode;
  const showSettingsInline = !isMobile;
  const showDashboardInline = !isMobile;
  const mobileOverflowActions = [
    showFindingsButton
      ? {
          key: "findings",
          label: findingsCount > 0 ? `Findings (${findingsCount})` : "Findings",
          icon: PanelRight,
          onClick: () => toggleFindingsPanel?.(),
          active: !!findingsPanelOpen,
          danger: false,
        }
      : null,
    scratchFullpageMode
      ? {
          key: "history",
          label: "Scratch history",
          icon: History,
          onClick: scratchFullpageMode.onOpenHistory,
          active: false,
          danger: false,
        }
      : null,
    scratchFullpageMode && !scratchFullpageMode.archive
      ? {
          key: "reset",
          label: scratchFullpageMode.resetArmed ? "Confirm scratch reset" : "Reset scratch session",
          icon: RotateCcw,
          onClick: scratchFullpageMode.onReset,
          active: false,
          danger: true,
        }
      : null,
    channelId
      ? {
          key: "settings",
          label: "Channel settings",
          icon: Settings,
          onClick: () => navigate(`/channels/${channelId}/settings`),
          active: false,
          danger: false,
        }
      : null,
    showDashboardButton
      ? {
          key: "widgets",
          label: "Widgets",
          icon: LayoutDashboard,
          onClick: isMobile ? toggleDrawerToWidgets : () => navigate(`/widgets/channel/${channelId}`),
          active: !!widgetsDrawerActive,
          danger: false,
        }
      : null,
  ].filter(Boolean) as Array<{
    key: string;
    label: string;
    icon: React.ComponentType<{ size: number; color: string }>;
    onClick: () => void;
    active: boolean;
    danger: boolean;
  }>;
  const showMobileOverflow = isMobile && mobileOverflowActions.length > 0;

  React.useEffect(() => {
    if (!mobileOverflowOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (mobileOverflowRef.current && target && !mobileOverflowRef.current.contains(target)) {
        setMobileOverflowOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [mobileOverflowOpen]);

  return (
    <header
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: isMobile ? 4 : 8,
        padding: isMobile ? "0 8px" : "0 12px",
        backgroundColor: "transparent",
        flexShrink: 0,
        zIndex: 10,
        minHeight: isMobile ? 56 : 52,
      }}
    >
      {isMobile ? (
        <button
          className="header-icon-btn"
          style={{ width: 44, height: 44 }}
          onClick={() => openChannelDrawer(true)}
          title="Open menu"
        >
          <Menu size={18} color={t.textMuted} />
        </button>
      ) : columns === "single" ? (
        <button className="header-icon-btn" style={{ width: 36, height: 36 }} onClick={goBack} title="Back">
          <ArrowLeft size={18} color={t.textMuted} />
        </button>
      ) : null}

      {isSystemChannel ? (
        <Cog size={16} className="text-accent ml-0.5 shrink-0" />
      ) : isPrivate ? (
        <Lock size={16} color={t.textDim} style={{ marginLeft: 2, flexShrink: 0 }} />
      ) : (
        <Hash size={16} color={t.textDim} style={{ marginLeft: 2, flexShrink: 0 }} />
      )}

      <div
        style={{ flex: 1, minWidth: 0, padding: isMobile ? "6px 0" : "6px 0", cursor: isMobile && !isSystemChannel && bot ? "pointer" : undefined }}
        onClick={isMobile && !isSystemChannel && bot ? onContextBudgetClick : undefined}
        title={isMobile && !isSystemChannel && bot ? bot.name : undefined}
      >
        <div className="flex flex-row items-center gap-2 min-w-0">
          <span style={{ fontSize: 15, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {displayName}
          </span>
          {showScratchState && (
            <span
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold shrink-0"
              style={{
                background: scratchTone.bg,
                border: `1px solid ${scratchTone.border}`,
                color: scratchTone.text,
              }}
              title={scratchBadgeLabel}
            >
              <StickyNote size={10} color={scratchTone.icon} />
              {scratchBadgeLabel}
            </span>
          )}
          {isSystemChannel && (
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded
                         bg-accent/10 text-accent text-[10px] uppercase tracking-wider
                         border border-accent/30 shrink-0"
              title="System configuration channel — pipelines here can modify bots, skills, and tasks."
            >
              <Cog size={10} />
              SYSTEM
            </span>
          )}
          {showOwnerChip && (
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded
                         bg-surface-overlay text-text-muted text-[10px]
                         shrink-0"
              title={`Owner: ${ownerName ?? ownerUserId}`}
            >
              <UserIcon size={10} />
              {ownerName ?? "owner"}
            </span>
          )}
          {isMobile && !isSystemChannel && contextBudget && contextBudget.total > 0 && contextBudget.utilization > 0.5 && (
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                backgroundColor: contextBudget.utilization > 0.8 ? "#f87171" : "#fbbf24",
                flexShrink: 0,
              }}
              title={`Context: ${fmtTokens(contextBudget.consumed)} / ${fmtTokens(contextBudget.total)} (${Math.round(contextBudget.utilization * 100)}%)`}
            />
          )}
        </div>
        {isSystemChannel && !isMobile && (
          <div className="text-[11px] text-text-dim mt-0.5 truncate">
            System configuration channel
          </div>
        )}
        {!isSystemChannel && !isMobile && bot && (
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginTop: 1, minWidth: 0 }}>
            <a
              className="header-bot-link"
              onClick={(e) => { e.preventDefault(); navigate(`/admin/bots/${bot.id}`); }}
              href={`/admin/bots/${bot.id}`}
              style={{ fontSize: 11, color: t.textMuted, textDecoration: "none", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            >
              {bot.name}
            </a>

            {/* Inline integration dots — subtle; replaces the vertical ActiveBadgeBar.
                Activated integrations use the theme success dot; bound-only dim. */}
            {(activeIntegrations.length > 0 || boundOnly.length > 0) && (
              <span className="flex flex-row items-center gap-1 shrink-0">
                {activeIntegrations.map((ig) => {
                  const Icon = resolveIntegrationIcon(ig.integration_type);
                  return (
                    <button
                      key={`a-${ig.integration_type}`}
                      onClick={() => navigate(`/channels/${channelId}/settings#integrations`)}
                      title={`${prettyIntegrationName(ig.integration_type)} — active`}
                      className="flex flex-row items-center gap-0.5 bg-transparent border-none cursor-pointer p-0"
                    >
                      <Icon size={10} color={t.textDim} />
                      <span
                        style={{ width: 4, height: 4, borderRadius: 2, backgroundColor: t.success, display: "inline-block" }}
                      />
                    </button>
                  );
                })}
                {boundOnly.map((b) => {
                  const Icon = resolveIntegrationIcon(b.integration_type);
                  return (
                    <button
                      key={`b-${b.id}`}
                      onClick={() => navigate(`/channels/${channelId}/settings#integrations`)}
                      title={`${prettyIntegrationName(b.integration_type)} — bound`}
                      className="flex flex-row items-center bg-transparent border-none cursor-pointer p-0 opacity-50"
                    >
                      <Icon size={10} color={t.textDim} />
                    </button>
                  );
                })}
              </span>
            )}

            {contextBudget && contextBudget.total > 0 && (
              <span
                onClick={onContextBudgetClick}
                style={{
                  fontSize: 10,
                  fontFamily: "monospace",
                  color: contextBudget.utilization > 0.8 ? "#f87171" : contextBudget.utilization > 0.5 ? "#fbbf24" : t.textDim,
                  flexShrink: 0,
                  cursor: onContextBudgetClick ? "pointer" : undefined,
                  borderBottom: onContextBudgetClick ? "1px dotted transparent" : undefined,
                  transition: "border-color 0.15s",
                }}
                onMouseEnter={onContextBudgetClick ? (e) => { (e.currentTarget as HTMLSpanElement).style.borderBottomColor = t.textDim; } : undefined}
                onMouseLeave={onContextBudgetClick ? (e) => { (e.currentTarget as HTMLSpanElement).style.borderBottomColor = "transparent"; } : undefined}
                title={`Context: ${fmtTokens(contextBudget.consumed)} / ${fmtTokens(contextBudget.total)} tokens (${Math.round(contextBudget.utilization * 100)}%)`}
              >
                {fmtTokens(contextBudget.consumed)}/{fmtTokens(contextBudget.total)}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Findings — inline when there's active signal (count > 0 or panel
          currently open). Stays out of the way on channels with no pipeline
          activity. */}
      {showFindingsInline && (
        <button
          type="button"
          className="header-icon-btn relative"
          style={{
            width: iconSize,
            height: iconSize,
            backgroundColor: findingsPanelOpen ? t.surfaceOverlay : "transparent",
          }}
          onClick={() => toggleFindingsPanel?.()}
          aria-label="Findings"
          aria-pressed={!!findingsPanelOpen}
          title={findingsCount > 0 ? `${findingsCount} pending finding${findingsCount === 1 ? "" : "s"}` : "Findings"}
        >
          <PanelRight size={16} color={findingsPanelOpen ? t.accent : t.textDim} />
          {findingsCount > 0 && (
            <span
              className="absolute top-1 right-1 min-w-[14px] h-[14px] px-1 rounded-full text-[9px] font-bold flex items-center justify-center leading-none animate-pulse"
              style={{ backgroundColor: t.accent, color: t.surface }}
            >
              {findingsCount > 9 ? "9+" : findingsCount}
            </span>
          )}
        </button>
      )}

      {/* Scratch chat opener. Always visible; stays put when the dock is
          open (clicking again is a no-op — dock's own X closes). Active
          styling signals that the dock is currently up. When the URL is
          on the scratch full-page route, clicking navigates back to the
          main chat (canonical minimize) and the button shows pressed
          state so the user can see which context they're in. */}
      {channelId && onOpenScratch && (
        <button
          className="header-icon-btn"
          style={{
            width: iconSize,
            height: iconSize,
            backgroundColor: scratchOpen ? t.surfaceOverlay : undefined,
          }}
          onClick={onOpenScratch}
          title={scratchFullpageMode ? "Minimize scratch (back to channel chat)" : "Scratch chat"}
          aria-label={scratchFullpageMode ? "Minimize scratch and return to channel" : "Open scratch chat"}
          aria-pressed={!!scratchOpen}
        >
          <StickyNote size={16} color={scratchOpen ? t.accent : t.textDim} />
        </button>
      )}

      {/* Scratch-mode extras — History + Reset. Only surface while the URL
          is on the scratch full-page route (or archive deep-link) so the
          main-chat header stays uncluttered. Reset is hidden on archive
          reads — you can't reset an archived session in place. */}
      {showScratchExtrasInline && channelId && scratchFullpageMode && (
        <>
          <button
            className="header-icon-btn"
            style={{ width: iconSize, height: iconSize }}
            onClick={scratchFullpageMode.onOpenHistory}
            title="Scratch history"
            aria-label="Open scratch history"
          >
            <History size={16} color={t.textDim} />
          </button>
          {!scratchFullpageMode.archive && (
            <button
              className="header-icon-btn"
              style={{
                width: iconSize,
                height: iconSize,
                backgroundColor: scratchFullpageMode.resetArmed ? "rgba(239,68,68,0.1)" : undefined,
              }}
              onClick={scratchFullpageMode.onReset}
              title={scratchFullpageMode.resetArmed ? "Click again within 3 s to reset the session" : "Reset scratch session"}
              aria-label="Reset scratch session"
            >
              <RotateCcw size={16} color={scratchFullpageMode.resetArmed ? "#ef4444" : t.textDim} />
            </button>
          )}
        </>
      )}

      {/* Settings — primary chrome. */}
      {showSettingsInline && channelId && (
        <button
          className="header-icon-btn"
          style={{ width: iconSize, height: iconSize }}
          onClick={() => navigate(`/channels/${channelId}/settings`)}
          title="Channel settings"
        >
          <Settings size={16} color={t.textDim} />
        </button>
      )}

      {/* Switch to dashboard — rightmost button, mirrors the "Switch to chat"
          button at the same spatial slot on the dashboard's top bar. Same
          pixel on both views. Shown on both mobile and desktop so users can
          pivot without hunting through menus. */}
      {showDashboardInline && showDashboardButton && (
        <button
          className="header-icon-btn"
          style={{
            width: iconSize,
            height: iconSize,
            backgroundColor: widgetsDrawerActive ? t.surfaceOverlay : undefined,
          }}
          onClick={
            isMobile
              ? toggleDrawerToWidgets
              : () => navigate(`/widgets/channel/${channelId}`)
          }
          title={isMobile ? "Widgets" : "Switch to dashboard view"}
          aria-label={isMobile ? "Widgets" : "Switch to dashboard view"}
          aria-pressed={isMobile ? widgetsDrawerActive : undefined}
        >
          <LayoutDashboard size={16} color={widgetsDrawerActive ? t.accent : t.textDim} />
        </button>
      )}

      {showMobileOverflow && (
        <div
          ref={mobileOverflowRef}
          style={{ position: "relative", flexShrink: 0 }}
        >
          <button
            type="button"
            className="header-icon-btn"
            style={{
              width: iconSize,
              height: iconSize,
              backgroundColor: mobileOverflowOpen ? t.surfaceOverlay : undefined,
            }}
            onClick={() => setMobileOverflowOpen((open) => !open)}
            aria-label="More actions"
            aria-haspopup="menu"
            aria-expanded={mobileOverflowOpen}
            title="More actions"
          >
            <MoreHorizontal size={18} color={mobileOverflowOpen ? t.text : t.textDim} />
          </button>
          {mobileOverflowOpen && (
            <div
              role="menu"
              className="absolute right-0 top-full mt-2 min-w-[190px] rounded-xl border shadow-lg overflow-hidden"
              style={{
                background: t.surfaceRaised,
                borderColor: t.surfaceBorder,
                boxShadow: "0 16px 40px rgba(0,0,0,0.28)",
                zIndex: 40,
              }}
            >
              {mobileOverflowActions.map((action) => {
                const Icon = action.icon;
                const color = action.danger
                  ? t.danger
                  : action.active
                    ? t.accent
                    : t.text;
                return (
                  <button
                    key={action.key}
                    type="button"
                    role="menuitem"
                    className="flex w-full items-center gap-3 px-3 py-3 text-left text-sm transition-colors"
                    style={{
                      background: action.active ? t.accentSubtle : "transparent",
                      color,
                      borderBottom: `1px solid ${t.surfaceBorder}`,
                    }}
                    onClick={() => {
                      setMobileOverflowOpen(false);
                      action.onClick();
                    }}
                  >
                    <Icon size={16} color={color} />
                    <span>{action.label}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </header>
  );
}
