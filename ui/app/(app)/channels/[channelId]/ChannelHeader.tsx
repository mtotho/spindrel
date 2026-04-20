import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Settings, Menu, ArrowLeft, Hash, Lock, LayoutDashboard,
  Cog, PanelRight, Plug,
  MessageSquare, Code2, Mail, Camera, Tv, Terminal, MessageCircle,
  User as UserIcon,
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
}: ChannelHeaderProps) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  // Mobile hamburger opens the channel drawer (Widgets/Files/Jump) rather
  // than the plain command palette — drawer's Jump tab wraps the palette
  // content inline, so channel-route mobile users get one surface with nav
  // + widgets + files all reachable from a single tap.
  const openChannelDrawer = useUIStore((s) => s.setFileExplorerOpen);

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
      {showFindingsButton && (
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

      {/* Settings — primary chrome. */}
      {channelId && (
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
          pixel on both views. `?dock=expanded` cues the dashboard's dock to
          open expanded with its entry animation. Shown on both mobile and
          desktop so users can pivot without hunting through menus. */}
      {showDashboardButton && (
        <button
          className="header-icon-btn"
          style={{ width: iconSize, height: iconSize }}
          onClick={() => navigate(`/widgets/channel/${channelId}?dock=expanded`)}
          title="Switch to dashboard view"
          aria-label="Switch to dashboard view"
        >
          <LayoutDashboard size={16} color={t.textDim} />
        </button>
      )}
    </header>
  );
}
