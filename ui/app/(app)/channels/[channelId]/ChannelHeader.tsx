import React from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { Link, useRouter } from "expo-router";
import { Settings, Menu, ArrowLeft, Hash, FolderOpen, Code, PanelLeft, Users } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

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
  /** Context budget from last SSE stream */
  contextBudget?: { utilization: number; consumed: number; total: number } | null;
  /** Called when user clicks the context budget indicator */
  onContextBudgetClick?: () => void;
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
  contextBudget,
  onContextBudgetClick,
}: ChannelHeaderProps) {
  const t = useThemeTokens();
  const router = useRouter();

  const fmtTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
    if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
    return String(n);
  };

  // ── Web path ──
  if (Platform.OS === "web") {
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
        {columns === "single" && (
          <button className="header-icon-btn" style={{ width: isMobile ? 36 : 44, height: isMobile ? 36 : 44 }} onClick={goBack} title="Back">
            <ArrowLeft size={isMobile ? 18 : 20} color={t.textMuted} />
          </button>
        )}
        {showHamburger && columns !== "single" && (
          <button className="header-icon-btn" style={{ width: 44, height: 44 }} onClick={toggleSidebar} title="Toggle sidebar">
            <Menu size={20} color={t.textMuted} />
          </button>
        )}
        <Hash size={18} color={t.textDim} style={{ marginLeft: 2, flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0, padding: "8px 0" }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {displayName}
          </div>
          {bot && (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2, minWidth: 0 }}>
              <a
                className="header-bot-link"
                onClick={(e) => { e.preventDefault(); router.push(`/admin/bots/${bot.id}` as any); }}
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
        {/* Explorer toggle: available whenever the channel resolves to a workspace
            (even if channel-level workspace is disabled — the explorer can still
            show bot memory and other workspace files). */}
        {workspaceId && !isMobile && (
          <button
            className="header-icon-btn"
            style={{ width: 36, height: 36, backgroundColor: explorerOpen ? t.surfaceOverlay : "transparent" }}
            onClick={toggleExplorer}
            title={explorerOpen ? "Hide file explorer" : "Show file explorer"}
          >
            <PanelLeft size={16} color={explorerOpen ? t.accent : t.textDim} />
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
              onClick={() => { onBrowseWorkspace(); router.push(`/admin/workspaces/${workspaceId}/files` as any); }}
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
            onClick={() => router.push(`/channels/${channelId}/settings` as any)}
            title="Channel settings"
          >
            <Settings size={isMobile ? 16 : 18} color={t.textDim} />
          </button>
        )}
      </header>
    );
  }

  // ── Native path ──
  return (
    <View
      className={`flex-row items-center ${isMobile ? "gap-2 px-3" : "gap-3 px-4"} bg-surface`}
      style={{
        flexShrink: 0,
        zIndex: 10,
        minHeight: 52,
      }}
    >
      {columns === "single" && (
        <Pressable
          onPress={goBack}
          className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
        >
          <ArrowLeft size={20} color={t.textMuted} />
        </Pressable>
      )}
      {showHamburger && columns !== "single" && (
        <Pressable
          onPress={toggleSidebar}
          className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
        >
          <Menu size={20} color={t.textMuted} />
        </Pressable>
      )}
      <Hash size={18} color={t.textDim} style={{ marginLeft: 2 }} />
      <View className="flex-1 min-w-0 py-2">
        <Text style={{ fontSize: 16, fontWeight: "700", color: t.text }} numberOfLines={1}>
          {displayName}
        </Text>
        {bot && (
          <View className="flex-row items-center gap-1.5 mt-0.5 min-w-0">
            <Link href={`/admin/bots/${bot.id}` as any}>
              <Text style={{ fontSize: 12, color: t.textMuted }} numberOfLines={1}>{bot.name}</Text>
            </Link>
            <Text style={{ fontSize: 11, color: t.textDim, flexShrink: 1 }} numberOfLines={1}>
              {(channelModelOverride || bot?.model || "").split("/").pop()}
            </Text>
            {contextBudget && contextBudget.total > 0 && (
              <Text style={{
                fontSize: 10,
                fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
                color: contextBudget.utilization > 0.8 ? "#f87171" : contextBudget.utilization > 0.5 ? "#fbbf24" : t.textDim,
              }}>
                {fmtTokens(contextBudget.consumed)}/{fmtTokens(contextBudget.total)}
              </Text>
            )}
          </View>
        )}
      </View>
      {/* Explorer toggle: available whenever the channel resolves to a workspace
          (mirrors the web path — even if channel-level workspace is disabled,
          the explorer can still show bot memory and other workspace files). */}
      {workspaceId && (
        <Pressable
          onPress={toggleExplorer}
          className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
          style={{
            width: 36,
            height: 36,
            backgroundColor: explorerOpen ? t.surfaceOverlay : "transparent",
            borderRadius: 6,
          }}
        >
          <PanelLeft size={16} color={explorerOpen ? t.accent : t.textDim} />
        </Pressable>
      )}
      {workspaceEnabled && workspaceId && !isMobile && (
        <Link href={`/admin/workspaces/${workspaceId}/files` as any} asChild>
          <Pressable
            onPress={onBrowseWorkspace}
            className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 36, height: 36 }}
          >
            <FolderOpen size={16} color={t.textDim} />
          </Pressable>
        </Link>
      )}
      {channelId && (
        <Link href={`/channels/${channelId}/settings` as any} asChild>
          <Pressable
            className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 44, height: 44 }}
          >
            <Settings size={18} color={t.textDim} />
          </Pressable>
        </Link>
      )}
    </View>
  );
}
