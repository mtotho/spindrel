/**
 * BotInfoPanel — portal modal showing a bot's resolved tools/capabilities/skills
 * for a given channel. Triggered by clicking a bot avatar/name in chat.
 */

import { useEffect, useMemo } from "react";
import { Platform } from "react-native";
import { X, Bot, Wrench, Puzzle, Server, Shield, ExternalLink } from "lucide-react";
import { useRouter } from "expo-router";
import { useThemeTokens } from "../../theme/tokens";
import { useBot } from "../../api/hooks/useBots";
import { useChannel, useChannelEffectiveTools } from "../../api/hooks/useChannels";

interface Props {
  botId: string;
  channelId: string;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Grouped tool display (read-only)
// ---------------------------------------------------------------------------

function ToolGroupSection({
  label,
  tools,
  accent,
}: {
  label: string;
  tools: string[];
  accent?: string;
}) {
  const t = useThemeTokens();
  if (tools.length === 0) return null;
  return (
    <div>
      <div style={{
        fontSize: 9, fontWeight: 700, color: accent || t.textDim,
        textTransform: "uppercase", letterSpacing: "0.05em",
        marginBottom: 4,
      }}>
        {label} ({tools.length})
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
        {tools.map((name) => (
          <span key={name} style={{
            fontSize: 10, fontFamily: "monospace",
            padding: "1px 6px", borderRadius: 3,
            background: t.surfaceOverlay, color: t.textMuted,
          }}>
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel content
// ---------------------------------------------------------------------------

function BotInfoPanelContent({ botId, channelId, onClose }: Props) {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: bot } = useBot(botId);
  const { data: channel } = useChannel(channelId);
  const isMemberBot = !!channel && channel.bot_id !== botId;

  // effective-tools is resolved for the channel's primary bot — only show for primary
  const { data: effective } = useChannelEffectiveTools(isMemberBot ? undefined : channelId);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  // For member bots, show their bot-level config instead of channel effective tools
  const displayTools = isMemberBot
    ? { local_tools: bot?.local_tools || [], pinned_tools: bot?.pinned_tools || [], mcp_servers: bot?.mcp_servers || [], client_tools: bot?.client_tools || [], skills: (bot?.skills || []).map((s) => ({ id: s.id, mode: s.mode || "on-demand", name: s.id })), carapaces: bot?.carapaces || [], carapace_sources: {} as Record<string, string> }
    : effective;

  // Split tools into pinned vs other
  const pinnedSet = useMemo(() => new Set(displayTools?.pinned_tools || []), [displayTools]);

  // Summary counts
  const toolCount = displayTools?.local_tools.length ?? 0;
  const skillCount = displayTools?.skills.length ?? 0;
  const mcpCount = displayTools?.mcp_servers.length ?? 0;
  const carapaceCount = displayTools?.carapaces.length ?? 0;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 10000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: t.surface,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 10,
          width: "90%",
          maxWidth: 420,
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
        }}
      >
        {/* Header */}
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "12px 16px",
          borderBottom: `1px solid ${t.surfaceBorder}`,
        }}>
          <Bot size={18} color={t.accent} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>
                {bot?.display_name || bot?.name || botId}
              </span>
              <button
                onClick={() => { onClose(); router.push(`/admin/bots/${botId}` as any); }}
                title="Edit bot settings"
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  padding: 2, display: "flex", alignItems: "center",
                  opacity: 0.4, color: t.textDim,
                }}
                onMouseEnter={(e) => { e.currentTarget.style.opacity = "0.9"; }}
                onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.4"; }}
              >
                <ExternalLink size={12} />
              </button>
            </div>
            {bot?.model && (
              <div style={{ fontSize: 11, color: t.textDim, marginTop: 1 }}>
                {bot.model.split("/").pop()}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: t.textDim }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: 16, overflow: "auto", flex: 1, display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Member bot caveat */}
          {isMemberBot && (
            <div style={{
              fontSize: 10, color: t.warningMuted, padding: "4px 8px",
              background: t.warningSubtle, borderRadius: 4,
              lineHeight: "15px",
            }}>
              Member bot &mdash; showing bot-level config. Channel overrides from the primary bot's channel may apply.
            </div>
          )}

          {/* Summary badges */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {toolCount > 0 && <CountBadge icon={<Wrench size={10} />} label={`${toolCount} tools`} />}
            {carapaceCount > 0 && <CountBadge icon={<Shield size={10} />} label={`${carapaceCount} capabilities`} />}
            {skillCount > 0 && <CountBadge icon={<Puzzle size={10} />} label={`${skillCount} skills`} />}
            {mcpCount > 0 && <CountBadge icon={<Server size={10} />} label={`${mcpCount} MCP`} />}
          </div>

          {/* Capabilities (carapaces) */}
          {displayTools && displayTools.carapaces.length > 0 && (
            <CaparacesSection carapaces={displayTools.carapaces} sources={displayTools.carapace_sources} />
          )}

          {/* Pinned tools */}
          {displayTools && displayTools.pinned_tools.length > 0 && (
            <ToolGroupSection label="Pinned tools" tools={displayTools.pinned_tools} accent="#eab308" />
          )}

          {/* Other tools (non-pinned) */}
          {displayTools && (
            <ToolGroupSection
              label="Available tools"
              tools={displayTools.local_tools.filter((n) => !pinnedSet.has(n))}
            />
          )}

          {/* Skills */}
          {displayTools && displayTools.skills.length > 0 && (
            <div>
              <div style={{
                fontSize: 9, fontWeight: 700, color: t.textDim,
                textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4,
              }}>
                Skills ({displayTools.skills.length})
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                {displayTools.skills.map((s) => (
                  <span key={s.id} style={{
                    fontSize: 10, padding: "1px 6px", borderRadius: 3,
                    background: `${t.accent}12`, color: t.accent,
                    border: `1px solid ${t.accent}25`,
                  }}>
                    {s.name || s.id}
                    {s.mode === "pinned" && (
                      <span style={{ marginLeft: 3, fontSize: 8, opacity: 0.7 }}>pinned</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* MCP servers */}
          {displayTools && displayTools.mcp_servers.length > 0 && (
            <ToolGroupSection label="MCP servers" tools={displayTools.mcp_servers} />
          )}

          {/* Client tools */}
          {displayTools && displayTools.client_tools.length > 0 && (
            <ToolGroupSection label="Client tools" tools={displayTools.client_tools} />
          )}

          {!displayTools && (
            <span style={{ fontSize: 11, color: t.textDim }}>Loading...</span>
          )}
          {displayTools && toolCount === 0 && skillCount === 0 && carapaceCount === 0 && mcpCount === 0 && (
            <span style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
              No tools or capabilities configured for this bot.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CountBadge({ icon, label }: { icon: React.ReactNode; label: string }) {
  const t = useThemeTokens();
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      fontSize: 10, fontWeight: 600, color: t.textMuted,
      background: t.surfaceOverlay, borderRadius: 4,
      padding: "2px 8px",
    }}>
      {icon}
      {label}
    </span>
  );
}

function CaparacesSection({ carapaces, sources }: { carapaces: string[]; sources: Record<string, string> }) {
  const t = useThemeTokens();
  return (
    <div>
      <div style={{
        fontSize: 9, fontWeight: 700, color: t.textDim,
        textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4,
      }}>
        Capabilities ({carapaces.length})
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {carapaces.map((id) => (
          <div key={id} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "3px 8px", borderRadius: 4,
            background: `${t.purple || "#8b5cf6"}10`,
            border: `1px solid ${t.purple || "#8b5cf6"}20`,
          }}>
            <Shield size={10} color={t.purple || "#8b5cf6"} />
            <span style={{ fontSize: 11, color: t.text, flex: 1 }}>{id}</span>
            {sources[id] && (
              <span style={{ fontSize: 9, color: t.textDim }}>{sources[id]}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Portal wrapper (web only)
// ---------------------------------------------------------------------------

export function BotInfoPanel(props: Props) {
  if (Platform.OS !== "web") return null;
  const ReactDOM = require("react-dom");
  return ReactDOM.createPortal(
    <BotInfoPanelContent {...props} />,
    document.body,
  );
}
