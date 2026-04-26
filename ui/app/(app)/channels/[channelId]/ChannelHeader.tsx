import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Settings, Menu, ArrowLeft, Hash, Lock, LayoutDashboard,
  Cog, PanelRight, Sparkles, StickyNote,
  X as CloseIcon,
  User as UserIcon, MoreHorizontal,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useUIStore } from "@/src/stores/ui";
import { useChannel } from "@/src/api/hooks/useChannels";
import { useAdminUsers } from "@/src/api/hooks/useAdminUsers";
import { useScratchHistory, useScratchSession } from "@/src/api/hooks/useChannelSessions";
import { useIsAdmin } from "@/src/hooks/useScope";
import { useAuthStore } from "@/src/stores/auth";
import { resolveHeaderMetrics, resolveRouteSessionChrome } from "./sessionHeaderChrome";

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
    utilization: number | null;
    consumedTokens?: number | null;
    totalTokens: number | null;
    grossPromptTokens: number | null;
    currentPromptTokens: number | null;
    cachedPromptTokens: number | null;
    completionTokens: number | null;
    contextProfile: string | null;
    turnsInContext: number | null;
    turnsUntilCompaction: number | null;
  } | null;
  sessionId?: string | null;
  sessionChromeMode?: "primary" | "session" | "canvas";
  sessionChromeTitle?: string | null;
  sessionChromeMeta?: string | null;
  canvasSessionCount?: number;
  /** Orchestrator / system-control channel — renders SYSTEM pill next to title. */
  isSystemChannel?: boolean;
  /** Findings panel state (awaiting-user-input pipelines). Inline icon shows
   *  only when there's active signal (panel open or count > 0). */
  findingsPanelOpen?: boolean;
  toggleFindingsPanel?: () => void;
  findingsCount?: number;
  /** Whether a session surface is currently active. */
  scratchOpen?: boolean;
  /** Open the unified channel session picker. */
  onOpenSessions?: () => void;
  scratchSessionId?: string | null;
  onOpenMainChat?: () => void;
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
  sessionChromeMode,
  sessionChromeTitle,
  sessionChromeMeta,
  canvasSessionCount,
  isSystemChannel,
  findingsPanelOpen,
  toggleFindingsPanel,
  findingsCount = 0,
  scratchOpen,
  onOpenSessions,
  scratchSessionId,
  onOpenMainChat,
  dashboardHref,
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
  const resolvedChromeMode = sessionChromeMode ?? (scratchFullpageMode ? "session" : "primary");
  const showScratchState = resolvedChromeMode === "session";
  const showCanvasState = resolvedChromeMode === "canvas";
  const sessionButtonLabel = "Sessions";
  const showFindingsInline = !isMobile && showFindingsButton;
  const showSettingsInline = !isMobile;
  const showDashboardInline = !isMobile;
  const resolvedMetrics = resolveHeaderMetrics(contextBudget, sessionHeaderStats);
  const scratchSessionMeta = React.useMemo(() => {
    if (!showScratchState || !scratchSessionId) return null;
    const matchedHistory = scratchHistory?.find((row) => row.session_id === scratchSessionId) ?? null;
    const matchedCurrent = currentScratchSession?.session_id === scratchSessionId ? currentScratchSession : null;
    const lastActiveLabel = formatScratchHeaderTimestamp(
      matchedHistory?.last_active ?? matchedCurrent?.created_at ?? null,
    );
    const label =
      matchedHistory?.title?.trim()
      || matchedCurrent?.title?.trim()
      || null;
    const bits = [
      lastActiveLabel,
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
      lastActiveLabel,
      stats: bits.join(" · ") || null,
    };
  }, [currentScratchSession, scratchHistory, scratchSessionId, showScratchState]);
  const headerSessionChrome = resolveRouteSessionChrome(
    showScratchState,
    sessionChromeTitle ?? scratchSessionMeta?.label ?? null,
    sessionChromeMeta ?? scratchSessionMeta?.lastActiveLabel ?? null,
  );
  const modeLabel = showCanvasState ? "Canvas" : headerSessionChrome.modeLabel;
  const compactModeLabel = showCanvasState && typeof canvasSessionCount === "number"
    ? `${canvasSessionCount} session${canvasSessionCount === 1 ? "" : "s"}`
    : modeLabel;
  const showModeBadge = !isSystemChannel && (!isMobile || showScratchState || showCanvasState);
  const canvasTitle = showCanvasState && typeof canvasSessionCount === "number"
    ? `${canvasSessionCount} session${canvasSessionCount === 1 ? "" : "s"}`
    : null;
  const tokenUsageBit = resolvedMetrics.hasAnyTokenUsage ? (
    <span
      key="tokens"
      onClick={onContextBudgetClick}
      style={{
        fontSize: 10,
        fontFamily: "monospace",
        color: (resolvedMetrics.utilization ?? 0) > 0.8 ? "#f87171" : (resolvedMetrics.utilization ?? 0) > 0.5 ? "#fbbf24" : t.textDim,
        flexShrink: 0,
        cursor: onContextBudgetClick ? "pointer" : undefined,
        borderBottom: onContextBudgetClick ? "1px dotted transparent" : undefined,
        transition: "border-color 0.15s",
      }}
      onMouseEnter={onContextBudgetClick ? (e) => { (e.currentTarget as HTMLSpanElement).style.borderBottomColor = t.textDim; } : undefined}
      onMouseLeave={onContextBudgetClick ? (e) => { (e.currentTarget as HTMLSpanElement).style.borderBottomColor = "transparent"; } : undefined}
      title={[
        resolvedMetrics.hasTokenMetrics
          ? `Prompt: ${fmtTokens(resolvedMetrics.gross ?? 0)} / ${fmtTokens(resolvedMetrics.total ?? 0)} tokens (${Math.round((resolvedMetrics.utilization ?? 0) * 100)}%)`
          : `Prompt: ${fmtTokens(resolvedMetrics.gross ?? resolvedMetrics.current ?? 0)} tokens`,
        resolvedMetrics.current != null ? `Current: ${fmtTokens(resolvedMetrics.current)}` : null,
        resolvedMetrics.cached != null ? `Cached: ${fmtTokens(resolvedMetrics.cached)}` : null,
        resolvedMetrics.completion != null ? `Completion: ${fmtTokens(resolvedMetrics.completion)}` : null,
        resolvedMetrics.contextProfile ? `Profile: ${resolvedMetrics.contextProfile}` : null,
      ].filter(Boolean).join("\n")}
    >
      {resolvedMetrics.hasTokenMetrics
        ? `${fmtTokens(resolvedMetrics.gross ?? 0)}/${fmtTokens(resolvedMetrics.total ?? 0)}`
        : `${fmtTokens(resolvedMetrics.gross ?? resolvedMetrics.current ?? 0)} tok`}
    </span>
  ) : null;
  const headerMetaBits = [
    tokenUsageBit,
    !resolvedMetrics.hasTokenMetrics && showScratchState ? (
      <span key="session-kind" className="shrink-0" style={{ fontSize: 10, color: t.textDim }}>
        {headerSessionChrome.subtitleIdentity ?? "session"}
      </span>
    ) : null,
    typeof resolvedMetrics.turnsInContext === "number" ? (
      <span key="turns-in-context" className="shrink-0" style={{ fontSize: 10, color: t.textDim }}>
        {resolvedMetrics.turnsInContext} turn{resolvedMetrics.turnsInContext === 1 ? "" : "s"} in ctx
      </span>
    ) : null,
    typeof resolvedMetrics.turnsUntilCompaction === "number" ? (
      <span key="turns-until-compaction" className="shrink-0" style={{ fontSize: 10, color: t.textDim }}>
        {resolvedMetrics.turnsUntilCompaction} until compact
      </span>
    ) : null,
  ].filter(Boolean);
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
    channelId && onOpenSessions
      ? {
          key: "sessions",
          label: sessionButtonLabel,
          icon: StickyNote,
          onClick: onOpenSessions,
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
          <span
            style={{
              fontSize: isMobile ? 14 : 15,
              fontWeight: 700,
              color: t.text,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              minWidth: 0,
            }}
          >
            {displayName}
          </span>
          {showModeBadge && (
            <span
              className="inline-flex items-center gap-1 px-0 py-0 text-[10px] font-medium uppercase tracking-[0.16em] shrink-0"
              style={{
                color: t.textDim,
                maxWidth: isMobile ? 88 : undefined,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={
                [
                  showCanvasState ? "Channel canvas" : showScratchState ? "Session" : "Primary",
                  showCanvasState ? canvasTitle : (sessionChromeTitle ?? scratchSessionMeta?.label ?? null),
                  showCanvasState ? null : (sessionChromeMeta ?? scratchSessionMeta?.stats ?? null),
                ].filter(Boolean).join("\n") || modeLabel
              }
            >
              {showScratchState || showCanvasState ? <StickyNote size={10} color={t.textDim} /> : null}
              {isMobile ? compactModeLabel : modeLabel}
            </span>
          )}
          {!isMobile && (showCanvasState ? null : headerSessionChrome.inlineMeta) ? (
            <span
              className="shrink-0 text-[10px] uppercase tracking-[0.12em]"
              style={{ color: t.textDim }}
              title={headerSessionChrome.inlineMeta ?? undefined}
            >
              {headerSessionChrome.inlineMeta}
            </span>
          ) : null}
          {!isMobile && (showCanvasState ? canvasTitle : headerSessionChrome.inlineTitle) ? (
            <span
              className="truncate text-[11px] shrink max-w-[28rem]"
              style={{ color: t.textMuted }}
              title={showCanvasState ? canvasTitle ?? undefined : headerSessionChrome.inlineTitle ?? undefined}
            >
              {showCanvasState ? canvasTitle : headerSessionChrome.inlineTitle}
            </span>
          ) : null}
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
          {channelData?.config?.effort_override && channelData.config.effort_override !== "off" && (
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded
                         bg-surface-overlay text-text-muted text-[10px] uppercase tracking-wider
                         shrink-0"
              title={`Reasoning effort set to ${channelData.config.effort_override}. Use /effort off to clear.`}
            >
              effort: {channelData.config.effort_override}
            </span>
          )}
          {isMobile && !isSystemChannel && resolvedMetrics.hasTokenMetrics && (resolvedMetrics.utilization ?? 0) > 0.5 && (
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                backgroundColor: (resolvedMetrics.utilization ?? 0) > 0.8 ? "#f87171" : "#fbbf24",
                flexShrink: 0,
              }}
              title={`Context: ${fmtTokens(resolvedMetrics.gross ?? 0)} / ${fmtTokens(resolvedMetrics.total ?? 0)} (${Math.round((resolvedMetrics.utilization ?? 0) * 100)}%)`}
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
            <a
              className="header-bot-link"
              onClick={(e) => { e.preventDefault(); navigate(`/admin/bots/${bot.id}`); }}
              href={`/admin/bots/${bot.id}`}
              style={{ fontSize: 11, color: t.textMuted, textDecoration: "none", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              title={bot.name}
            >
              {bot.name}
            </a>
            {(isMobile ? [tokenUsageBit].filter(Boolean) : headerMetaBits).map((bit, idx) => (
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

      {/* Session route close. A single non-primary session is a page-level
          view; closing it returns to the channel primary route. */}
      {scratchFullpageMode && onOpenMainChat && (
        <button
          type="button"
          className="header-icon-btn"
          style={{ width: iconSize, height: iconSize }}
          onClick={onOpenMainChat}
          title="Close session view"
          aria-label="Close session view"
        >
          <CloseIcon size={16} color={t.textDim} />
        </button>
      )}
      {!isMobile && channelId && onOpenSessions && (
        <div className="relative shrink-0">
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
            onClick={onOpenSessions}
            title={sessionButtonLabel}
            aria-label={sessionButtonLabel}
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
        </div>
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

      {/* Beam to spatial canvas — sits to the LEFT of the dashboard switch
          so the dashboard button stays the rightmost slot (mirrors the
          chat button's position on the dashboard top bar). Sparkles glyph
          carries the "beam me up" transport vibe. Desktop-only for now.

          The sessionStorage handoff lets the canvas recenter on this channel's
          tile at a safe overview zoom on mount — without it, the camera state
          loaded from localStorage can re-trigger the push-through dive
          immediately and suck the user back into the channel they just left. */}
      {!isMobile && (
        <button
          className="header-icon-btn"
          style={{ width: iconSize, height: iconSize }}
          onClick={() => {
            if (channelId) {
              try {
                sessionStorage.setItem(
                  "spatial.beamFromChannel",
                  JSON.stringify({ channelId, ts: Date.now() }),
                );
              } catch {
                // sessionStorage unavailable (private mode, etc.) — swallow;
                // the mount-time dive cooldown still catches the loop.
              }
            }
            navigate("/");
          }}
          title="Beam to spatial canvas"
          aria-label="Beam to spatial canvas"
        >
          <Sparkles size={16} color={t.textDim} />
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
    </header>
  );
}
