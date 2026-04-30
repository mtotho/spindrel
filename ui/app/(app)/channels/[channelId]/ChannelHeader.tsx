import React from "react";
import { useMatch, useNavigate } from "react-router-dom";
import { createPortal } from "react-dom";
import {
  Settings, Menu, ArrowLeft, Hash, Lock, LayoutDashboard,
  Cog, PanelRight, Sparkles, StickyNote,
  X as CloseIcon,
  User as UserIcon, MoreHorizontal,
  AlertTriangle,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useUIStore } from "@/src/stores/ui";
import { useChannel } from "@/src/api/hooks/useChannels";
import { useAdminUsers } from "@/src/api/hooks/useAdminUsers";
import { useScratchHistory, useScratchSession } from "@/src/api/hooks/useChannelSessions";
import {
  useSessionHarnessSettings,
  useSessionHarnessStatus,
  useSetSessionHarnessSettings,
} from "@/src/api/hooks/useApprovals";
import { useRuntimeCapabilities } from "@/src/api/hooks/useRuntimes";
import { useWorkspaceAttention } from "@/src/api/hooks/useWorkspaceAttention";
import { useIsAdmin } from "@/src/hooks/useScope";
import { useAuthStore } from "@/src/stores/auth";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import { attentionDeckHref } from "@/src/lib/hubRoutes";
import { resolveHeaderMetrics, resolveRouteSessionChrome } from "./sessionHeaderChrome";

export interface ChannelHeaderProps {
  channelId: string;
  displayName: string;
  bot: { id?: string; name?: string; model?: string; harness_runtime?: string | null } | undefined;
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
  isMobile: routeIsMobile,
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
  const detectedMobile = useIsMobile();
  const isMobile = routeIsMobile || detectedMobile;
  const navigate = useNavigate();
  const routeSessionMatch = useMatch("/channels/:channelId/session/:sessionId");
  const routeSessionId = routeSessionMatch?.params.sessionId ?? null;
  const effectiveSessionId = sessionId ?? routeSessionId;
  const [mobileOverflowOpen, setMobileOverflowOpen] = React.useState(false);
  const mobileOverflowRef = React.useRef<HTMLDivElement | null>(null);
  const mobileOverflowMenuRef = React.useRef<HTMLDivElement | null>(null);
  const [mobileOverflowPos, setMobileOverflowPos] = React.useState({ top: 0, left: 0, width: 190 });
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
  const { data: attentionItems } = useWorkspaceAttention(channelId);
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
  const attentionCount = (attentionItems ?? []).filter((item) => item.status !== "resolved").length;
  const canvasTitle = showCanvasState && typeof canvasSessionCount === "number"
    ? `${canvasSessionCount} session${canvasSessionCount === 1 ? "" : "s"}`
    : null;
  const tokenUsageBit = resolvedMetrics.hasAnyTokenUsage && !bot?.harness_runtime ? (
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
    // Spindrel-side context stats describe OUR RAG loop's window. Harness
    // bots delegate context management to the external runtime — these
    // numbers don't apply, so suppress them.
    !bot?.harness_runtime && typeof resolvedMetrics.turnsInContext === "number" ? (
      <span key="turns-in-context" className="shrink-0" style={{ fontSize: 10, color: t.textDim }}>
        {resolvedMetrics.turnsInContext} turn{resolvedMetrics.turnsInContext === 1 ? "" : "s"} in ctx
      </span>
    ) : null,
    !bot?.harness_runtime && typeof resolvedMetrics.turnsUntilCompaction === "number" ? (
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
  const titleOpensContext = !isMobile && !isSystemChannel && !!bot && !bot.harness_runtime && !!onContextBudgetClick;

  const updateMobileOverflowPosition = React.useCallback(() => {
    const rect = mobileOverflowRef.current?.getBoundingClientRect();
    if (!rect || typeof window === "undefined") return;
    const width = Math.min(224, Math.max(184, window.innerWidth - 16));
    setMobileOverflowPos({
      top: rect.bottom + 5,
      left: Math.max(8, Math.min(window.innerWidth - width - 8, rect.right - width)),
      width,
    });
  }, []);

  React.useEffect(() => {
    if (!mobileOverflowOpen) return;
    updateMobileOverflowPosition();
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      const inTrigger = !!(mobileOverflowRef.current && target && mobileOverflowRef.current.contains(target));
      const inMenu = !!(mobileOverflowMenuRef.current && target && mobileOverflowMenuRef.current.contains(target));
      if (!inTrigger && !inMenu) {
        setMobileOverflowOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOverflowOpen(false);
    };
    const handleDismiss = () => setMobileOverflowOpen(false);
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("resize", handleDismiss);
    window.addEventListener("scroll", handleDismiss, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("resize", handleDismiss);
      window.removeEventListener("scroll", handleDismiss, true);
    };
  }, [mobileOverflowOpen, updateMobileOverflowPosition]);

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
        data-testid="channel-header-title-region"
        style={{ flex: 1, minWidth: 0, padding: isMobile ? "6px 0" : "6px 0", cursor: titleOpensContext ? "pointer" : undefined }}
        onClick={titleOpensContext ? onContextBudgetClick : undefined}
        title={titleOpensContext ? bot.name : undefined}
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
          {attentionCount > 0 && (
            <button
              type="button"
              className="inline-flex shrink-0 items-center gap-1 rounded-full bg-warning/10 px-1.5 py-0.5 text-[10px] text-warning hover:bg-warning/15"
              title={`${attentionCount} active Attention Beacon${attentionCount === 1 ? "" : "s"}`}
              onClick={() => navigate(attentionDeckHref({ channelId, mode: "inbox" }))}
            >
              <AlertTriangle size={10} />
              {attentionCount}
            </button>
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
            {isMobile ? (
              <span
                className="header-bot-label"
                style={{ fontSize: 11, color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={bot.name}
              >
                {bot.name}
              </span>
            ) : (
              <a
                className="header-bot-link"
                onClick={(e) => { e.preventDefault(); navigate(`/admin/bots/${bot.id}`); }}
                href={`/admin/bots/${bot.id}`}
                style={{ fontSize: 11, color: t.textMuted, textDecoration: "none", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={bot.name}
              >
                {bot.name}
              </a>
            )}
            {bot.harness_runtime && (
              <HarnessHeaderChrome
                runtime={bot.harness_runtime}
                sessionId={effectiveSessionId}
                compact={isMobile}
                t={t}
              />
            )}
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
            onClick={() => {
              updateMobileOverflowPosition();
              setMobileOverflowOpen((open) => !open);
            }}
            aria-label="More actions"
            aria-haspopup="menu"
            aria-expanded={mobileOverflowOpen}
            title="More actions"
          >
            <MoreHorizontal size={18} color={mobileOverflowOpen ? t.text : t.textDim} />
          </button>
        </div>
      )}
      {mobileOverflowOpen && typeof document !== "undefined" && createPortal(
        <div
          data-testid="channel-header-mobile-overflow-menu"
          ref={mobileOverflowMenuRef}
          role="menu"
          className="fixed max-h-[calc(100dvh-72px)] overflow-auto rounded-md bg-surface-raised p-1 text-text shadow-xl ring-1 ring-surface-border"
          style={{
            top: mobileOverflowPos.top,
            left: mobileOverflowPos.left,
            width: mobileOverflowPos.width,
            zIndex: 50001,
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
                className="flex w-full items-center gap-3 rounded px-3 py-2.5 text-left text-sm transition-colors"
                style={{
                  background: action.active ? t.accentSubtle : "transparent",
                  color,
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
        </div>,
        document.body,
      )}
    </header>
  );
}

/**
 * Harness chrome — runtime/model/context badges, scoped to a single
 * session. Per-session: each chat surface (primary, scratch split, thread)
 * passes its own `sessionId`, so the pill always controls THIS surface's
 * approval mode and not the channel's "active" session.
 */
function HarnessHeaderChrome({
  runtime,
  sessionId,
  compact = false,
  t,
}: {
  runtime: string;
  sessionId: string | null;
  compact?: boolean;
  t: ReturnType<typeof useThemeTokens>;
}) {
  const { data: caps } = useRuntimeCapabilities(runtime);
  const displayName = caps?.display_name ?? runtime;
  if (compact) {
    return sessionId ? <HarnessStatusPill sessionId={sessionId} t={t} compact /> : null;
  }
  return (
    <>
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider shrink-0"
        style={{
          backgroundColor: t.surfaceOverlay,
          color: t.textMuted,
        }}
        title={`Harness runtime: ${displayName}`}
      >
        🤖 {displayName}
      </span>
      {sessionId && caps && (
        <>
          <HarnessModelPill
            sessionId={sessionId}
            caps={caps}
            t={t}
          />
          <HarnessStatusPill sessionId={sessionId} t={t} />
        </>
      )}
    </>
  );
}

function HarnessStatusPill({
  sessionId,
  t,
  compact = false,
}: {
  sessionId: string;
  t: ReturnType<typeof useThemeTokens>;
  compact?: boolean;
}) {
  const { data } = useSessionHarnessStatus(sessionId);
  const [open, setOpen] = React.useState(false);
  const buttonRef = React.useRef<HTMLButtonElement | null>(null);
  const [panelStyle, setPanelStyle] = React.useState<React.CSSProperties>({});
  const updatePanelPosition = React.useCallback(() => {
    if (compact || typeof window === "undefined") {
      setPanelStyle({});
      return;
    }
    const margin = 8;
    const rect = buttonRef.current?.getBoundingClientRect();
    const width = Math.min(320, Math.max(0, window.innerWidth - margin * 2));
    const anchorRight = rect?.right ?? window.innerWidth - margin;
    const left = Math.max(
      margin,
      Math.min(anchorRight - width, window.innerWidth - margin - width),
    );
    const top = Math.max(margin, (rect?.bottom ?? 48) + margin);
    setPanelStyle({
      left,
      top,
      width,
      maxHeight: Math.max(160, window.innerHeight - top - margin),
      zIndex: 50002,
    });
  }, [compact]);
  React.useLayoutEffect(() => {
    if (!open) return;
    updatePanelPosition();
    if (compact || typeof window === "undefined") return;
    window.addEventListener("resize", updatePanelPosition);
    window.addEventListener("scroll", updatePanelPosition, true);
    return () => {
      window.removeEventListener("resize", updatePanelPosition);
      window.removeEventListener("scroll", updatePanelPosition, true);
    };
  }, [compact, open, updatePanelPosition]);
  const panelClassName = compact
    ? "fixed left-2 right-2 top-14 z-[50002] max-h-[calc(100dvh-72px)] overflow-auto rounded-md bg-surface-raised p-3 text-xs text-text-muted shadow-xl ring-1 ring-surface-border"
    : "fixed left-2 right-2 top-14 z-[50002] max-h-[calc(100dvh-72px)] overflow-auto rounded-md bg-surface-raised p-3 text-xs text-text-muted shadow-xl ring-1 ring-surface-border";
  const mergedPanelStyle = compact
    ? { fontFamily: "system-ui, sans-serif" }
    : {
        fontFamily: "system-ui, sans-serif",
        ...(typeof panelStyle.width === "number" ? { right: "auto" } : {}),
        ...panelStyle,
      };
  if (!data) {
    const loadingLabel = compact ? "ctx" : "ctx loading";
    return (
      <span className="relative inline-flex shrink-0">
        <button
          ref={buttonRef}
          type="button"
          data-testid={compact ? "harness-context-chip-mobile" : "harness-context-chip"}
          onClick={() => setOpen((v) => !v)}
          className={
            compact
              ? "inline-flex h-5 min-w-5 items-center justify-center rounded bg-surface-overlay px-1 text-[10px] text-text-muted hover:text-text"
              : "inline-flex max-w-[14rem] items-center gap-1 truncate rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-text-muted hover:text-text"
          }
          style={{ color: t.textMuted, fontFamily: "'Menlo', monospace" }}
          title="Harness context is loading."
        >
          {loadingLabel}
        </button>
        {open && (
          <div
            data-testid={compact ? "harness-context-panel-mobile" : "harness-context-panel"}
            className={panelClassName}
            style={mergedPanelStyle}
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="font-medium text-text">Harness context</div>
              <button type="button" onClick={() => setOpen(false)} className="rounded bg-transparent p-1 text-text-dim hover:bg-surface-overlay hover:text-text" aria-label="Close context details">
                <CloseIcon size={12} />
              </button>
            </div>
            <div className="grid gap-1">
              <div><span className="text-text-dim">Context</span> loading</div>
              <div><span className="text-text-dim">CWD</span> loading</div>
            </div>
          </div>
        )}
      </span>
    );
  }
  const resume = data.harness_session_id
    ? data.harness_session_id.slice(0, 8)
    : "new";
  const usageLabel = formatHarnessUsage(data.usage);
  const remainingLabel = typeof data.context_remaining_pct === "number"
    ? `${Math.round(data.context_remaining_pct)}% left`
    : null;
  const remainingSource = data.context_remaining_source === "native_compaction"
    ? "after native compact"
    : data.context_remaining_source === "last_turn"
      ? "last turn"
      : null;
  const diagnostics = (data.context_diagnostics ?? null) as Record<string, unknown> | null;
  const confidence = typeof diagnostics?.confidence === "string" ? diagnostics.confidence : null;
  const contextReason = typeof diagnostics?.reason === "string" ? diagnostics.reason : null;
  const sourceFields = Array.isArray(diagnostics?.source_fields) ? diagnostics.source_fields.map(String) : [];
  const contextTokens = typeof diagnostics?.context_tokens === "number" ? diagnostics.context_tokens : null;
  const hints = data.pending_hint_count > 0 ? ` · ${data.pending_hint_count} hint${data.pending_hint_count === 1 ? "" : "s"}` : "";
  const bridge = (data.bridge_status ?? {}) as Record<string, unknown>;
  const bridgeErrors = [
    typeof bridge.error === "string" && bridge.error ? bridge.error : null,
    ...(Array.isArray(bridge.inventory_errors) ? bridge.inventory_errors.map(String) : []),
  ].filter(Boolean);
  const nativeCompact = (data.native_compaction ?? null) as Record<string, unknown> | null;
  const compactBefore = (nativeCompact?.context_before ?? null) as Record<string, unknown> | null;
  const compactAfter = (nativeCompact?.context_after ?? null) as Record<string, unknown> | null;
  const compactTraceId = typeof nativeCompact?.trace_correlation_id === "string" ? nativeCompact.trace_correlation_id : null;
  const compactSource = typeof nativeCompact?.source === "string" ? nativeCompact.source : null;
  const compactBeforePct = typeof compactBefore?.remaining_pct === "number" ? `${Math.round(compactBefore.remaining_pct)}%` : null;
  const compactAfterPct = typeof compactAfter?.remaining_pct === "number" ? `${Math.round(compactAfter.remaining_pct)}%` : null;
  const exportedTools = Array.isArray(bridge.exported_tools) ? bridge.exported_tools.map(String) : [];
  const ignoredClientTools = Array.isArray(bridge.ignored_client_tools) ? bridge.ignored_client_tools.map(String) : [];
  const explicitTools = Array.isArray(bridge.explicit_tool_names) ? bridge.explicit_tool_names.map(String) : [];
  const taggedSkills = Array.isArray(bridge.tagged_skill_ids) ? bridge.tagged_skill_ids.map(String) : [];
  const hintRows = Array.isArray(data.hints) ? data.hints : [];
  const computedHintRows = Array.isArray(data.next_turn_computed_hints) ? data.next_turn_computed_hints : [];
  const lastHintRows = Array.isArray(data.last_hints_sent) ? data.last_hints_sent : [];
  const projectDir = (data.project_dir ?? {}) as Record<string, unknown>;
  const projectPathLabel = typeof projectDir.path === "string" ? projectDir.path : null;
  const compactLabel = data.pending_hint_count > 0
    ? `${data.pending_hint_count}`
    : typeof data.context_remaining_pct === "number" && data.context_remaining_pct < 60
      ? `${Math.round(data.context_remaining_pct)}%`
      : "ctx";
  return (
    <span className="relative inline-flex shrink-0">
      <button
        ref={buttonRef}
        type="button"
        data-testid={compact ? "harness-context-chip-mobile" : "harness-context-chip"}
        onClick={() => setOpen((v) => !v)}
        className={
          compact
            ? "inline-flex h-5 min-w-5 items-center justify-center rounded bg-surface-overlay px-1 text-[10px] text-text-muted hover:text-text"
            : "inline-flex max-w-[14rem] items-center gap-1 truncate rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-text-muted hover:text-text"
        }
        style={{
          color: bridgeErrors.length > 0
            ? t.warningMuted
            : data.pending_hint_count > 0
              ? t.warningMuted
              : typeof data.context_remaining_pct === "number" && data.context_remaining_pct < 60
                ? t.warningMuted
                : t.textMuted,
          fontFamily: "'Menlo', monospace",
        }}
        title={`${data.context_note} Resume: ${data.harness_session_id || "none"}. Last turn: ${data.last_turn_at || "none"}. Usage: ${usageLabel || "unknown"}. Remaining: ${remainingLabel || "unknown"}${remainingSource ? ` (${remainingSource})` : ""}${confidence ? `, confidence ${confidence}` : ""}.`}
      >
        {compact
          ? compactLabel
          : <>ctx {remainingLabel ?? usageLabel ?? resume}{remainingLabel && remainingSource ? ` · ${remainingSource}` : ""}{confidence && confidence !== "high" ? ` · ${confidence}` : ""}{hints}</>}
      </button>
      {open && (
        <div
          data-testid={compact ? "harness-context-panel-mobile" : "harness-context-panel"}
          className={panelClassName}
          style={mergedPanelStyle}
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="font-medium text-text">Harness context</div>
            <button type="button" onClick={() => setOpen(false)} className="rounded bg-transparent p-1 text-text-dim hover:bg-surface-overlay hover:text-text" aria-label="Close context details">
              <CloseIcon size={12} />
            </button>
          </div>
          <div className="grid gap-1">
            <div className="min-w-0 break-words"><span className="text-text-dim">Resume</span> {data.harness_session_id || "new"}</div>
            <div className="min-w-0 break-words"><span className="text-text-dim">Context</span> {remainingLabel || "unknown"}{remainingSource ? ` · ${remainingSource}` : ""}{data.context_window_tokens ? ` · ${data.context_window_tokens.toLocaleString()} window` : ""}</div>
            <div><span className="text-text-dim">Estimate</span> {confidence || "none"}{contextTokens ? ` · ${contextTokens.toLocaleString()} tokens` : ""}</div>
            {contextReason && (
              <div className="min-w-0 break-words"><span className="text-text-dim">Reason</span> {contextReason}</div>
            )}
            {sourceFields.length > 0 && (
              <div className="min-w-0 break-words"><span className="text-text-dim">Usage fields</span> <span className="font-mono text-[10px] break-all">{sourceFields.join(", ")}</span></div>
            )}
            <div>
              <span className="text-text-dim">Native compact</span>{" "}
              {nativeCompact
                ? `${String(nativeCompact.status || "unknown")} · ${String(nativeCompact.created_at || "")}${compactSource ? ` · ${compactSource}` : ""}`
                : "none observed"}
            </div>
            {nativeCompact && (compactBeforePct || compactAfterPct) && (
              <div>
                <span className="text-text-dim">Compact estimate</span>{" "}
                {compactBeforePct || "unknown"} → {compactAfterPct || "unknown"}
              </div>
            )}
            {compactTraceId && (
              <div>
                <span className="text-text-dim">Compact trace</span>{" "}
                <a
                  href={`/admin/logs/${compactTraceId}`}
                  className="font-mono text-[10px] text-accent hover:underline"
                >
                  {compactTraceId.slice(0, 8)}
                </a>
              </div>
            )}
            <div className="min-w-0 break-words"><span className="text-text-dim">CWD</span> <span className="font-mono text-[10px] break-all">{data.effective_cwd || "unknown"}</span>{data.effective_cwd_source ? ` · ${data.effective_cwd_source}` : ""}</div>
            {projectPathLabel && <div className="min-w-0 break-words"><span className="text-text-dim">Project</span> <span className="font-mono text-[10px] break-all">/{projectPathLabel}</span></div>}
            {data.bot_workspace_dir && <div className="min-w-0 break-words"><span className="text-text-dim">Bot memory root</span> <span className="font-mono text-[10px] break-all">{data.bot_workspace_dir}</span></div>}
            <div><span className="text-text-dim">Bridge</span> {String(bridge.status || "unknown")} · {exportedTools.length} tool{exportedTools.length === 1 ? "" : "s"}</div>
            {bridgeErrors.length > 0 && (
              <div className="min-w-0 break-words text-warning-muted">{bridgeErrors.join("; ")}</div>
            )}
            {explicitTools.length > 0 && <div className="min-w-0 break-words"><span className="text-text-dim">One-turn tools</span> {explicitTools.join(", ")}</div>}
            {taggedSkills.length > 0 && <div className="min-w-0 break-words"><span className="text-text-dim">Tagged skills</span> {taggedSkills.join(", ")}</div>}
            {ignoredClientTools.length > 0 && <div className="min-w-0 break-words"><span className="text-text-dim">Not bridgeable</span> {ignoredClientTools.join(", ")}</div>}
          </div>
          <div className="mt-3 border-t border-surface-border pt-2">
            <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-text-dim">Pending hints</div>
            {hintRows.length === 0 ? (
              <div className="text-text-dim">None</div>
            ) : hintRows.map((hint, idx) => (
              <div key={idx} className="mb-2 last:mb-0">
                <div className="font-mono text-[10px] text-text">{String(hint.kind || "hint")} {hint.source ? `from ${String(hint.source)}` : ""}</div>
                <div className="line-clamp-3 text-[11px] leading-snug">{String(hint.preview || "")}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 border-t border-surface-border pt-2">
            <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-text-dim">Computed next-turn hints</div>
            {computedHintRows.length === 0 ? (
              <div className="text-text-dim">None</div>
            ) : computedHintRows.map((hint, idx) => (
              <div key={idx} className="mb-2 last:mb-0">
                <div className="font-mono text-[10px] text-text">{String(hint.kind || "hint")} {hint.source ? `from ${String(hint.source)}` : ""}</div>
                <div className="line-clamp-3 text-[11px] leading-snug">{String(hint.preview || "")}</div>
              </div>
            ))}
          </div>
          {lastHintRows.length > 0 && (
            <div className="mt-3 border-t border-surface-border pt-2">
              <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-text-dim">Last hints sent</div>
              <div className="max-h-24 overflow-auto">
                {lastHintRows.map((hint, idx) => (
                  <div key={idx} className="mb-2 last:mb-0">
                    <div className="font-mono text-[10px] text-text">{String(hint.kind || "hint")} {hint.source ? `from ${String(hint.source)}` : ""}</div>
                    <div className="line-clamp-3 text-[11px] leading-snug">{String(hint.preview || "")}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {exportedTools.length > 0 && (
            <div className="mt-3 border-t border-surface-border pt-2">
              <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-text-dim">Exported tools</div>
              <div className="max-h-24 overflow-auto break-words font-mono text-[10px] leading-4">{exportedTools.join(", ")}</div>
            </div>
          )}
        </div>
      )}
    </span>
  );
}

function formatHarnessUsage(usage: Record<string, unknown> | null): string | null {
  if (!usage) return null;
  const keys = [
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "cached_tokens",
    "reasoning_output_tokens",
  ];
  let total = 0;
  for (const key of keys) {
    const value = usage[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      total += value;
    }
  }
  if (total <= 0) return null;
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(1)}M tok`;
  if (total >= 1_000) return `${Math.round(total / 100) / 10}k tok`;
  return `${total} tok`;
}

function HarnessModelPill({
  sessionId,
  caps,
  t,
}: {
  sessionId: string;
  caps: { supported_models: string[]; available_models?: string[]; model_options?: Array<{ id: string; label?: string | null }>; model_is_freeform: boolean; display_name: string };
  t: ReturnType<typeof useThemeTokens>;
}) {
  const { data, isLoading } = useSessionHarnessSettings(sessionId);
  const setSettings = useSetSessionHarnessSettings();
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const current = data?.model ?? null;
  const label = current ?? "model";

  const commit = (raw: string | null) => {
    setSettings.mutate(
      { sessionId, patch: { model: raw } },
      { onSettled: () => setEditing(false) },
    );
  };

  if (editing && caps.model_is_freeform) {
    return (
      <span className="inline-flex items-center gap-1 shrink-0">
        <input
          autoFocus
          value={draft}
          placeholder="model id (blank = clear)"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            const trimmed = draft.trim();
            commit(trimmed === "" ? null : trimmed);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              const trimmed = draft.trim();
              commit(trimmed === "" ? null : trimmed);
            } else if (e.key === "Escape") {
              setEditing(false);
            }
          }}
          className="px-1.5 py-0.5 rounded text-[10px] outline-none shrink-0"
          style={{
            backgroundColor: t.surfaceOverlay,
            color: t.text,
            border: `1px solid ${t.surfaceBorder}`,
            minWidth: "12rem",
          }}
        />
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        if (caps.model_is_freeform) {
          setDraft(current ?? "");
          setEditing(true);
        } else if ((caps.model_options?.length ?? 0) > 0 || caps.supported_models.length > 0) {
          // Cycle through supported models + a "clear" slot at the end.
          const models = (caps.model_options?.length ? caps.model_options.map((m) => m.id) : caps.supported_models);
          const idx = current ? models.indexOf(current) : -1;
          const cycle = [...models, null];
          const next = cycle[(idx + 1) % cycle.length];
          commit(next);
        }
      }}
      disabled={setSettings.isPending || isLoading}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] shrink-0 max-w-[14rem] truncate"
      style={{
        backgroundColor: t.surfaceOverlay,
        color: current ? t.text : t.textMuted,
        border: "none",
        cursor: setSettings.isPending ? "default" : "pointer",
        opacity: setSettings.isPending ? 0.6 : 1,
        fontFamily: "'Menlo', monospace",
      }}
      title={
        current
          ? `${caps.display_name} model: ${current}. Click to change.`
          : `${caps.display_name} default model. Click to override.`
      }
    >
      🧠 {label}
    </button>
  );
}

function HarnessEffortPill({
  sessionId,
  caps,
  t,
}: {
  sessionId: string;
  caps: { effort_values: string[]; model_options: Array<{ id: string; effort_values: string[] }> };
  t: ReturnType<typeof useThemeTokens>;
}) {
  const { data, isLoading } = useSessionHarnessSettings(sessionId);
  const setSettings = useSetSessionHarnessSettings();
  const current = data?.effort ?? null;
  const selectedModel = data?.model ?? null;
  const effortValues = (
    caps.model_options.find((m) => m.id === selectedModel)?.effort_values
    ?? caps.effort_values
  );
  const handleCycle = () => {
    if (setSettings.isPending) return;
    // Cycle through declared effort values + a "clear" slot at the end.
    const cycle = [...effortValues, null];
    const idx = current ? effortValues.indexOf(current) : effortValues.length;
    const next = cycle[(idx + 1) % cycle.length];
    setSettings.mutate({ sessionId, patch: { effort: next } });
  };
  return (
    <button
      type="button"
      onClick={handleCycle}
      disabled={setSettings.isPending || isLoading}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider shrink-0"
      style={{
        backgroundColor: current ? t.warningSubtle : t.surfaceOverlay,
        color: current ? t.warningMuted : t.textMuted,
        border: "none",
        cursor: setSettings.isPending ? "default" : "pointer",
        opacity: setSettings.isPending ? 0.6 : 1,
      }}
      title={
        current
          ? `Effort: ${current}. Click to cycle.`
          : `Effort: default. Click to set.`
      }
    >
      ⚡ {current ?? "effort"}
    </button>
  );
}
