import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Settings, Menu, ArrowLeft, Hash, Lock, LayoutDashboard,
  Cog, PanelRight, StickyNote,
  Minimize2,
  User as UserIcon, MoreHorizontal,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useUIStore } from "@/src/stores/ui";
import { useChannel } from "@/src/api/hooks/useChannels";
import { useAdminUsers } from "@/src/api/hooks/useAdminUsers";
import { useScratchHistory, useScratchSession } from "@/src/api/hooks/useEphemeralSession";
import { useIsAdmin } from "@/src/hooks/useScope";
import { useAuthStore } from "@/src/stores/auth";
import { ScratchSessionMenu } from "@/src/components/chat/ScratchSessionMenu";
import { MachineTargetChip } from "./MachineTargetChip";

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
  contextBudget?: {
    utilization: number;
    consumed: number;
    total: number;
    gross?: number;
    current?: number;
    cached?: number;
    contextProfile?: string;
  } | null;
  /** Called when user clicks the context budget indicator */
  onContextBudgetClick?: () => void;
  sessionHeaderStats?: {
    grossPromptTokens: number | null;
    currentPromptTokens: number | null;
    cachedPromptTokens: number | null;
    completionTokens: number | null;
    contextProfile: string | null;
    turnsInContext: number | null;
    turnsUntilCompaction: number | null;
  } | null;
  sessionId?: string | null;
  /** Orchestrator / system-control channel — renders SYSTEM pill next to title. */
  isSystemChannel?: boolean;
  /** Findings panel state (awaiting-user-input pipelines). Inline icon shows
   *  only when there's active signal (panel open or count > 0). */
  findingsPanelOpen?: boolean;
  toggleFindingsPanel?: () => void;
  findingsCount?: number;
  /** Open the scratch-chat dock. Button is rendered on every viewport. */
  scratchOpen?: boolean;
  onOpenScratch?: (sessionId?: string | null) => void;
  scratchSessionId?: string | null;
  onOpenMainChat?: () => void;
  onStartNewScratchSession?: () => void;
  /** Optional explicit dashboard target. Scratch full-page uses this to
   *  carry the exact scratch session into the channel dashboard URL. */
  dashboardHref?: string;
  /** When the current URL is the scratch full-page route, the header
   *  switches into scratch-session chrome so the route reads clearly as a
   *  parallel session rather than the main channel chat. */
  scratchFullpageMode?: {
  };
}

function formatScratchHeaderTimestamp(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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
  sessionHeaderStats,
  sessionId,
  isSystemChannel,
  findingsPanelOpen,
  toggleFindingsPanel,
  findingsCount = 0,
  scratchOpen,
  onOpenScratch,
  scratchSessionId,
  onOpenMainChat,
  onStartNewScratchSession,
  dashboardHref,
  scratchFullpageMode,
}: ChannelHeaderProps) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const [mobileOverflowOpen, setMobileOverflowOpen] = React.useState(false);
  const [scratchMenuOpen, setScratchMenuOpen] = React.useState(false);
  const mobileOverflowRef = React.useRef<HTMLDivElement | null>(null);
  const scratchMenuRef = React.useRef<HTMLDivElement | null>(null);
  // Mobile hamburger opens the channel drawer (Widgets/Files/Jump) rather
  // than the plain command palette — drawer's Jump tab wraps the palette
  // content inline, so channel-route mobile users get one surface with nav
  // + widgets + files all reachable from a single tap.
  const setMobileDrawerOpen = useUIStore((s) => s.setMobileDrawerOpen);
  // Mobile-only: the top-right widget button toggles the same drawer but
  // force-pins it to the Widgets tab. Hamburger still opens wherever the
  // user last explicitly navigated (persisted `omniPanelTab`), so the two
  // buttons don't clobber each other.
  const toggleDrawerToWidgets = useUIStore((s) => s.toggleMobileDrawerToWidgets);
  const drawerPrefs = useUIStore((s) => s.channelPanelPrefs[channelId]);
  const drawerOpen = drawerPrefs?.mobileDrawerOpen ?? false;
  const drawerTab = drawerPrefs?.leftTab ?? "widgets";
  const widgetsDrawerActive = isMobile && drawerOpen && drawerTab === "widgets";

  const { data: channelData } = useChannel(channelId);
  const { data: scratchHistory } = useScratchHistory(scratchFullpageMode ? channelId : null);
  const { data: currentScratchSession } = useScratchSession(
    scratchFullpageMode && bot?.id ? channelId : null,
    scratchFullpageMode && bot?.id ? bot.id : null,
  );

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

  const fmtTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
    if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
    return String(n);
  };

  void columns;

  const iconSize = isMobile ? 44 : 36;
  const showDashboardButton = !!channelId && !isSystemChannel;
  const showFindingsButton =
    !!toggleFindingsPanel && (findingsCount > 0 || !!findingsPanelOpen);
  const showScratchState = !!scratchFullpageMode;
  const scratchBadgeLabel = "Scratch";
  const sessionButtonLabel = "Sessions";
  const scratchTone = {
    bg: t.surfaceOverlay,
    border: t.surfaceBorder,
    text: t.textMuted,
    icon: t.textDim,
  };
  const showFindingsInline = !isMobile && showFindingsButton;
  const showSettingsInline = !isMobile;
  const showDashboardInline = !isMobile;
  const headerMetaBits = [
    contextBudget && contextBudget.total > 0 ? (
      (() => {
        const gross = contextBudget.gross ?? sessionHeaderStats?.grossPromptTokens ?? contextBudget.consumed;
        const current = contextBudget.current ?? sessionHeaderStats?.currentPromptTokens;
        const cached = contextBudget.cached ?? sessionHeaderStats?.cachedPromptTokens;
        const profile = contextBudget.contextProfile ?? sessionHeaderStats?.contextProfile;
        const completion = sessionHeaderStats?.completionTokens;
        const titleParts = [
          `Prompt: ${fmtTokens(gross)} / ${fmtTokens(contextBudget.total)} tokens (${Math.round(contextBudget.utilization * 100)}%)`,
          current != null ? `Current: ${fmtTokens(current)}` : null,
          cached != null ? `Cached: ${fmtTokens(cached)}` : null,
          completion != null ? `Completion: ${fmtTokens(completion)}` : null,
          profile ? `Profile: ${profile}` : null,
        ].filter(Boolean);
        return (
      <span
        key="tokens"
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
        title={titleParts.join("\n")}
      >
        {fmtTokens(gross)}/{fmtTokens(contextBudget.total)}
      </span>
        );
      })()
    ) : null,
    typeof sessionHeaderStats?.turnsInContext === "number" ? (
      <span key="turns-in-context" className="shrink-0" style={{ fontSize: 10, color: t.textDim }}>
        {sessionHeaderStats.turnsInContext} turn{sessionHeaderStats.turnsInContext === 1 ? "" : "s"} in ctx
      </span>
    ) : null,
    typeof sessionHeaderStats?.turnsUntilCompaction === "number" ? (
      <span key="turns-until-compaction" className="shrink-0" style={{ fontSize: 10, color: t.textDim }}>
        {sessionHeaderStats.turnsUntilCompaction} until compact
      </span>
    ) : null,
  ].filter(Boolean);
  const scratchSessionMeta = React.useMemo(() => {
    if (!showScratchState || !scratchSessionId) return null;
    const matchedHistory = scratchHistory?.find((row) => row.session_id === scratchSessionId) ?? null;
    const matchedCurrent = currentScratchSession?.session_id === scratchSessionId ? currentScratchSession : null;
    const label =
      matchedHistory?.title?.trim()
      || matchedCurrent?.title?.trim()
      || null;
    const bits = [
      formatScratchHeaderTimestamp(matchedHistory?.last_active ?? matchedCurrent?.created_at ?? null),
      typeof matchedHistory?.message_count === "number"
        ? `${matchedHistory.message_count} msg${matchedHistory.message_count === 1 ? "" : "s"}`
        : typeof matchedCurrent?.message_count === "number"
          ? `${matchedCurrent.message_count} msg${matchedCurrent.message_count === 1 ? "" : "s"}`
          : null,
      typeof matchedHistory?.section_count === "number"
        ? `${matchedHistory.section_count} section${matchedHistory.section_count === 1 ? "" : "s"}`
        : typeof matchedCurrent?.section_count === "number"
          ? `${matchedCurrent.section_count} section${matchedCurrent.section_count === 1 ? "" : "s"}`
          : null,
    ].filter(Boolean);
    return {
      label,
      stats: bits.join(" · ") || null,
    };
  }, [currentScratchSession, scratchHistory, scratchSessionId, showScratchState]);
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
    channelId && onOpenScratch
      ? {
          key: "scratch",
          label: sessionButtonLabel,
          icon: StickyNote,
          onClick: () => setScratchMenuOpen((open) => !open),
          active: !!scratchOpen,
          danger: false,
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
          onClick: isMobile
            ? () => toggleDrawerToWidgets(channelId)
            : () => navigate(dashboardHref ?? `/widgets/channel/${channelId}`),
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

  React.useEffect(() => {
    if (!scratchMenuOpen || isMobile) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (scratchMenuRef.current && target && !scratchMenuRef.current.contains(target)) {
        setScratchMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isMobile, scratchMenuOpen]);

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
          onClick={() => setMobileDrawerOpen(channelId, true)}
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
              className="inline-flex items-center gap-1 px-0 py-0 text-[10px] font-semibold shrink-0"
              style={{
                color: scratchTone.text,
              }}
              title={
                [
                  "Scratch session",
                  scratchSessionMeta?.label ?? null,
                  scratchSessionMeta?.stats ?? null,
                ].filter(Boolean).join("\n") || "Scratch session"
              }
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
        {!isSystemChannel && bot && (
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginTop: 1, minWidth: 0 }}>
            {scratchFullpageMode ? (
              <>
                <a
                  className="header-bot-link"
                  onClick={(e) => { e.preventDefault(); navigate(`/admin/bots/${bot.id}`); }}
                  href={`/admin/bots/${bot.id}`}
                  style={{ fontSize: 11, color: t.textMuted, textDecoration: "none", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  title={bot.name}
                >
                  {bot.name}
                </a>
                <span
                  className="shrink-0 text-[11px]"
                  style={{ color: t.textDim }}
                  title={
                    [
                      scratchSessionMeta?.label ?? null,
                      scratchSessionMeta?.stats ?? null,
                    ].filter(Boolean).join("\n") || "Private scratch session for this channel"
                  }
                >
                  scratch session
                </span>
                {headerMetaBits.length > 0 ? (
                  headerMetaBits.map((bit, idx) => <React.Fragment key={idx}>{bit}</React.Fragment>)
                ) : scratchSessionMeta?.stats ? (
                  <span className="truncate text-[11px]" style={{ color: t.textDim }}>
                    {scratchSessionMeta.stats}
                  </span>
                ) : null}
              </>
            ) : (
            <a
              className="header-bot-link"
              onClick={(e) => { e.preventDefault(); navigate(`/admin/bots/${bot.id}`); }}
              href={`/admin/bots/${bot.id}`}
              style={{ fontSize: 11, color: t.textMuted, textDecoration: "none", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            >
              {bot.name}
            </a>
            )}
            {!scratchFullpageMode && headerMetaBits.map((bit, idx) => (
              <React.Fragment key={idx}>{bit}</React.Fragment>
            ))}
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
      {scratchFullpageMode && onOpenMainChat && (
        <button
          type="button"
          className="header-icon-btn"
          style={{ width: iconSize, height: iconSize }}
          onClick={onOpenMainChat}
          title="Minimize session back to channel chat"
          aria-label="Minimize session back to channel chat"
        >
          <Minimize2 size={16} color={t.textDim} />
        </button>
      )}
      {!isMobile && channelId && onOpenScratch && (
        <div ref={scratchMenuRef} className="relative shrink-0">
          <button
            type="button"
            className={
              isMobile
                ? "header-icon-btn"
                : "inline-flex h-9 items-center gap-2 rounded-full px-3 text-[12px] font-medium transition-colors"
            }
            style={
              isMobile
                ? {
                    width: iconSize,
                    height: iconSize,
                    backgroundColor: scratchOpen ? t.surfaceOverlay : undefined,
                  }
                : {
                    border: "none",
                    backgroundColor: scratchOpen ? t.surfaceOverlay : "transparent",
                    color: scratchOpen ? t.text : t.textMuted,
                  }
            }
            onClick={() => setScratchMenuOpen((open) => !open)}
            title={sessionButtonLabel}
            aria-label={sessionButtonLabel}
            aria-expanded={scratchMenuOpen}
            aria-haspopup="dialog"
            aria-pressed={!!scratchOpen}
          >
            <StickyNote size={16} color={scratchOpen ? t.text : t.textDim} />
            {!isMobile && (
              <>
                <span>{sessionButtonLabel}</span>
              </>
            )}
          </button>
          <ScratchSessionMenu
            open={scratchMenuOpen}
            onClose={() => setScratchMenuOpen(false)}
            channelId={channelId}
            botId={bot?.id}
            currentSessionId={scratchSessionId}
            mobile={isMobile}
            onOpenSidePane={onOpenScratch}
            onOpenMainChat={onOpenMainChat}
            onStartNewSession={onStartNewScratchSession}
            onNavigateSession={(sessionId) => {
              setScratchMenuOpen(false);
              navigate(`/channels/${channelId}/session/${sessionId}?scratch=true`);
            }}
          />
        </div>
      )}

      {!isMobile && sessionId && isAdmin && !scratchFullpageMode && (
        <MachineTargetChip sessionId={sessionId} />
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
              ? () => toggleDrawerToWidgets(channelId)
              : () => navigate(dashboardHref ?? `/widgets/channel/${channelId}`)
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
              className="absolute right-0 top-full mt-1 min-w-[190px] overflow-hidden shadow-[0_8px_32px_rgba(0,0,0,0.4)]"
              style={{
                background: t.surfaceRaised,
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
      {isMobile && channelId && onOpenScratch && (
        <ScratchSessionMenu
          open={scratchMenuOpen}
          onClose={() => setScratchMenuOpen(false)}
          channelId={channelId}
          botId={bot?.id}
          currentSessionId={scratchSessionId}
          mobile
          onOpenSidePane={onOpenScratch}
          onOpenMainChat={onOpenMainChat}
          onStartNewSession={onStartNewScratchSession}
          onNavigateSession={(sessionId) => {
            setScratchMenuOpen(false);
            navigate(`/channels/${channelId}/session/${sessionId}?scratch=true`);
          }}
        />
      )}
    </header>
  );
}
