import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Settings, Menu, ArrowLeft, Hash, FolderOpen, Code, PanelLeft, Columns2, Users, Wrench, Cog, PanelRight } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useToolResultCompact } from "@/src/stores/toolResultPref";
import { useUIStore } from "@/src/stores/ui";

export interface ChannelHeaderProps {
  channelId: string;
  displayName: string;
  bot: { id?: string; name?: string; model?: string } | undefined;
  channelModelOverride: string | undefined;
  columns: "single" | "double" | "triple";
  showHamburger: boolean;
  goBack: () => void;
  toggleSidebar: () => void;
  /** Workspace feature flags */
  workspaceEnabled: boolean | undefined;
  workspaceId: string | null | undefined;
  explorerOpen: boolean;
  toggleExplorer: () => void;
  onBrowseWorkspace: () => void;
  onOpenEditor: () => void;
  isMobile: boolean;
  /** Multi-bot channel support */
  memberBotCount?: number;
  participantsPanelOpen?: boolean;
  toggleParticipantsPanel?: () => void;
  /** Split mode (chat + file side by side) */
  activeFile?: string | null;
  splitMode?: boolean;
  onToggleSplit?: () => void;
  /** Context budget from last SSE stream */
  contextBudget?: { utilization: number; consumed: number; total: number } | null;
  /** Called when user clicks the context budget indicator */
  onContextBudgetClick?: () => void;
  /** Orchestrator / system-control channel — renders SYSTEM pill next to title
      and a subtitle clarifying its role. Replaces the legacy yellow admin banner. */
  isSystemChannel?: boolean;
  /** Findings panel state (awaiting-user-input pipelines) — present on system
      channels. When defined, renders a PanelRight toggle with a badge count. */
  findingsPanelOpen?: boolean;
  toggleFindingsPanel?: () => void;
  findingsCount?: number;
}

export function ChannelHeader({
  channelId,
  displayName,
  bot,
  channelModelOverride,
  columns,
  showHamburger,
  goBack,
  toggleSidebar,
  workspaceEnabled,
  workspaceId,
  explorerOpen,
  toggleExplorer,
  onBrowseWorkspace,
  onOpenEditor,
  isMobile,
  memberBotCount = 0,
  participantsPanelOpen,
  toggleParticipantsPanel,
  activeFile,
  splitMode,
  onToggleSplit,
  contextBudget,
  onContextBudgetClick,
  isSystemChannel,
  findingsPanelOpen,
  toggleFindingsPanel,
  findingsCount = 0,
}: ChannelHeaderProps) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const openPalette = useUIStore((s) => s.openPalette);
  const [compact, setCompact] = useToolResultCompact(channelId);

  const fmtTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
    if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
    return String(n);
  };

  const modelShort = (channelModelOverride || bot?.model || "").split("/").pop();
  return (
      <header
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: isMobile ? 8 : 12,
          padding: isMobile ? "0 12px" : "0 16px",
          backgroundColor: "transparent",
          flexShrink: 0,
          zIndex: 10,
          minHeight: 52,
        }}
      >
        {isMobile ? (
          <button className="header-icon-btn" style={{ width: 36, height: 36 }} onClick={openPalette} title="Open menu">
            <Menu size={18} color={t.textMuted} />
          </button>
        ) : columns === "single" ? (
          <button className="header-icon-btn" style={{ width: 44, height: 44 }} onClick={goBack} title="Back">
            <ArrowLeft size={20} color={t.textMuted} />
          </button>
        ) : showHamburger ? (
          <button className="header-icon-btn" style={{ width: 44, height: 44 }} onClick={toggleSidebar} title="Toggle sidebar">
            <Menu size={20} color={t.textMuted} />
          </button>
        ) : null}
        {isSystemChannel ? (
          <Cog size={18} className="text-accent ml-0.5 shrink-0" />
        ) : (
          <Hash size={18} color={t.textDim} style={{ marginLeft: 2, flexShrink: 0 }} />
        )}
        <div style={{ flex: 1, minWidth: 0, padding: "8px 0" }}>
          <div className="flex flex-row items-center gap-2 min-w-0">
            <span style={{ fontSize: 16, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
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
          </div>
          {isSystemChannel && (
            <div className="text-[11px] text-text-dim mt-0.5 truncate">
              System configuration channel
            </div>
          )}
          {!isSystemChannel && bot && (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2, minWidth: 0 }}>
              <a
                className="header-bot-link"
                onClick={(e) => { e.preventDefault(); navigate(`/admin/bots/${bot.id}`); }}
                href={`/admin/bots/${bot.id}`}
                style={{ fontSize: 12, color: t.textMuted, textDecoration: "none", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              >
                {bot.name}
              </a>
              {modelShort && (
                <span style={{ fontSize: 11, color: t.textDim, flexShrink: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {modelShort}
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
        {/* Compact tool results toggle: when ON, rich tool result envelopes
            (markdown / diff / json / file-listing) collapse to badge mode and
            require an explicit click to expand. Default OFF — file ops show
            their rendered body inline so the user can see what the bot did. */}
        {!isMobile && (
          <button
            className="header-icon-btn"
            style={{ width: 36, height: 36, backgroundColor: compact ? t.surfaceOverlay : "transparent" }}
            onClick={() => setCompact(!compact)}
            title={compact ? "Show full tool output inline" : "Compact tool results to badges"}
          >
            <Wrench size={16} color={compact ? t.accent : t.textDim} />
          </button>
        )}
        {/* OmniPanel toggle: always available (pinned widgets work without a workspace).
            Hidden on system channels — no workspace files or pinned tool widgets apply. */}
        {!isSystemChannel && (
          <button
            className="header-icon-btn"
            style={{ width: 36, height: 36, backgroundColor: explorerOpen ? t.surfaceOverlay : "transparent" }}
            onClick={toggleExplorer}
            title={explorerOpen ? "Hide panel" : "Show panel"}
          >
            <PanelLeft size={16} color={explorerOpen ? t.accent : t.textDim} />
          </button>
        )}
        {/* Split view toggle — visible when a file is open */}
        {activeFile && onToggleSplit && !isMobile && (
          <button
            className="header-icon-btn"
            style={{ width: 36, height: 36, backgroundColor: splitMode ? t.surfaceOverlay : "transparent" }}
            onClick={onToggleSplit}
            title={splitMode ? "Exit split view (⌘\\)" : "Split view — chat + file (⌘\\)"}
          >
            <Columns2 size={16} color={splitMode ? t.accent : t.textDim} />
          </button>
        )}
        {/* Browse workspace + VS Code editor: still gated on channel workspace
            being enabled (those open the live editor session, which only makes
            sense when the channel actually owns workspace files). */}
        {workspaceEnabled && workspaceId && !isMobile && (
          <>
            <button
              className="header-icon-btn"
              style={{ width: 36, height: 36 }}
              onClick={() => { onBrowseWorkspace(); navigate(`/admin/workspaces/${workspaceId}/files`); }}
              title="Browse workspace"
            >
              <FolderOpen size={16} color={t.textDim} />
            </button>
            <button
              className="header-icon-btn"
              style={{ width: 36, height: 36 }}
              onClick={onOpenEditor}
              title="Open in VS Code"
            >
              <Code size={16} color={t.textDim} />
            </button>
          </>
        )}
        {toggleFindingsPanel && (
          <button
            className="header-icon-btn relative"
            style={{
              width: isMobile ? 36 : 36,
              height: isMobile ? 36 : 36,
              backgroundColor: findingsPanelOpen ? t.surfaceOverlay : "transparent",
            }}
            onClick={toggleFindingsPanel}
            title={findingsPanelOpen ? "Hide findings" : `Findings${findingsCount ? ` (${findingsCount} pending)` : ""}`}
          >
            <PanelRight size={16} color={findingsPanelOpen ? t.accent : t.textDim} />
            {findingsCount > 0 && (
              <span
                className="absolute top-1 right-1 min-w-[14px] h-[14px] px-1 rounded-full
                           bg-accent text-[9px] font-bold flex items-center justify-center
                           leading-none animate-pulse"
                style={{ color: t.surface }}
              >
                {findingsCount > 9 ? "9+" : findingsCount}
              </span>
            )}
          </button>
        )}
        {toggleParticipantsPanel && !isMobile && (
          <button
            className="header-icon-btn"
            style={{
              width: 36,
              height: 36,
              backgroundColor: participantsPanelOpen ? t.surfaceOverlay : "transparent",
              position: "relative",
            }}
            onClick={toggleParticipantsPanel}
            title={participantsPanelOpen ? "Hide participants" : "Manage participants"}
          >
            <Users size={16} color={participantsPanelOpen ? t.accent : t.textDim} />
            {memberBotCount > 0 && (
              <span style={{
                position: "absolute",
                top: 4,
                right: 4,
                fontSize: 9,
                fontWeight: 700,
                color: t.accent,
                background: `${t.accent}20`,
                borderRadius: 6,
                padding: "0 3px",
                minWidth: 12,
                textAlign: "center",
                lineHeight: "14px",
              }}>
                {1 + memberBotCount}
              </span>
            )}
          </button>
        )}
        {channelId && (
          <button
            className="header-icon-btn"
            style={{ width: isMobile ? 36 : 44, height: isMobile ? 36 : 44 }}
            onClick={() => navigate(`/channels/${channelId}/settings`)}
            title="Channel settings"
          >
            <Settings size={isMobile ? 16 : 18} color={t.textDim} />
          </button>
        )}
      </header>
    );
}
