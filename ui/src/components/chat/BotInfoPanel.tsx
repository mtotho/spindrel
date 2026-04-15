/**
 * BotInfoPanel — portal modal showing a bot's resolved tools/capabilities/skills
 * for a given channel. Triggered by clicking a bot avatar/name in chat.
 */

import { useEffect, useMemo } from "react";
import { X, Bot, Wrench, Puzzle, Server, Shield, ExternalLink } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useThemeTokens } from "../../theme/tokens";
import { useBot } from "../../api/hooks/useBots";
import { useChannel, useChannelEffectiveTools, useChannelConfigOverhead } from "../../api/hooks/useChannels";
import type { ContextEstimate } from "../../api/hooks/useChannels";
import { useCarapaces } from "../../api/hooks/useCarapaces";
import { buildToolCarapaceMap } from "../../utils/carapaceMapping";

interface Props {
  botId: string;
  channelId: string;
  onClose: () => void;
  contextBudget?: { utilization: number; consumed: number; total: number } | null;
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
        textTransform: "uppercase", letterSpacing: 1,
        marginBottom: 4,
      }}>
        {label} ({tools.length})
      </div>
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 3 }}>
        {tools.map((name) => (
          <span key={name} style={{
            fontSize: 10, fontFamily: "monospace",
            padding: "1px 6px", borderRadius: 4,
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

function BotInfoPanelContent({ botId, channelId, onClose, contextBudget }: Props) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: bot } = useBot(botId);
  const { data: channel } = useChannel(channelId);
  const isMemberBot = !!channel && channel.bot_id !== botId;

  // effective-tools is resolved for the channel's primary bot — only show for primary
  const { data: effective } = useChannelEffectiveTools(isMemberBot ? undefined : channelId);
  const { data: allCarapaces } = useCarapaces();
  const { data: configOverhead } = useChannelConfigOverhead(isMemberBot ? undefined : channelId);

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

  // Provenance maps
  const toolCapMap = useMemo(() => {
    if (!allCarapaces || !displayTools?.carapaces) return new Map();
    return buildToolCarapaceMap(allCarapaces, displayTools.carapaces);
  }, [allCarapaces, displayTools]);

  // Group tools by capability
  const toolGroups = useMemo(() => {
    if (!displayTools) return [];
    const allTools = displayTools.local_tools;
    const groups = new Map<string, { name: string; tools: string[] }>();
    const ungrouped: string[] = [];
    for (const tool of allTools) {
      const cap = toolCapMap.get(tool);
      if (cap) {
        const g = groups.get(cap.carapaceId);
        if (g) g.tools.push(tool);
        else groups.set(cap.carapaceId, { name: cap.carapaceName, tools: [tool] });
      } else {
        ungrouped.push(tool);
      }
    }
    const result: { label: string; tools: string[] }[] = [];
    for (const [, g] of groups) result.push({ label: g.name, tools: g.tools });
    if (ungrouped.length > 0) result.push({ label: "Other tools", tools: ungrouped });
    return result;
  }, [displayTools, toolCapMap]);

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
        display: "flex", flexDirection: "row",
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
          borderRadius: 8,
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
          display: "flex", flexDirection: "row", alignItems: "center", gap: 10,
          padding: "12px 16px",
          borderBottom: `1px solid ${t.surfaceBorder}`,
        }}>
          <Bot size={18} color={t.accent} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>
                {bot?.display_name || bot?.name || botId}
              </span>
              <button
                onClick={() => { onClose(); navigate(`/admin/bots/${botId}`); }}
                title="Edit bot settings"
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  padding: 2, display: "flex", flexDirection: "row", alignItems: "center",
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
            style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: t.textDim, borderRadius: 4, transition: "background 0.15s" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = t.surfaceOverlay; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
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
          <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
            {toolCount > 0 && <CountBadge icon={<Wrench size={10} />} label={`${toolCount} tools`} />}
            {carapaceCount > 0 && <CountBadge icon={<Shield size={10} />} label={`${carapaceCount} capabilities`} />}
            {skillCount > 0 && <CountBadge icon={<Puzzle size={10} />} label={`${skillCount} skills`} />}
            {mcpCount > 0 && <CountBadge icon={<Server size={10} />} label={`${mcpCount} MCP`} />}
          </div>

          {/* Live context budget */}
          {contextBudget && contextBudget.total > 0 && (
            <div>
              <div style={{
                fontSize: 9, fontWeight: 700, color: t.textDim,
                textTransform: "uppercase", letterSpacing: 1, marginBottom: 6,
              }}>
                Context Usage
              </div>
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <div style={{
                  flex: 1, height: 6, borderRadius: 3,
                  background: t.surfaceOverlay, overflow: "hidden",
                }}>
                  <div style={{
                    width: `${Math.min(Math.round(contextBudget.utilization * 100), 100)}%`,
                    height: "100%",
                    background: contextBudget.utilization > 0.8 ? "#ef4444" : contextBudget.utilization > 0.5 ? "#eab308" : "#22c55e",
                    borderRadius: 3,
                    transition: "width 0.3s, background-color 0.3s",
                  }} />
                </div>
                <span style={{
                  fontSize: 10, fontWeight: 600, fontFamily: "monospace",
                  color: contextBudget.utilization > 0.8 ? "#ef4444" : contextBudget.utilization > 0.5 ? "#eab308" : t.textMuted,
                  whiteSpace: "nowrap",
                }}>
                  {Math.round(contextBudget.utilization * 100)}% ({Math.round(contextBudget.consumed / 1000)}K / {Math.round(contextBudget.total / 1000)}K)
                </span>
              </div>
              <div style={{ fontSize: 9, color: t.textDim, fontStyle: "italic" }}>
                Live usage from last message. Includes conversation history + config.
              </div>
            </div>
          )}

          {/* Configuration overhead */}
          {configOverhead && <ConfigOverhead estimate={configOverhead} t={t} />}

          {/* Capabilities (carapaces) */}
          {displayTools && displayTools.carapaces.length > 0 && (
            <CaparacesSection carapaces={displayTools.carapaces} sources={displayTools.carapace_sources} />
          )}

          {/* Tools grouped by capability */}
          {displayTools && toolGroups.map((g) => (
            <ToolGroupSection key={g.label} label={g.label} tools={g.tools} />
          ))}

          {/* Skills with provenance */}
          {displayTools && displayTools.skills.length > 0 && (
            <div>
              <div style={{
                fontSize: 9, fontWeight: 700, color: t.textDim,
                textTransform: "uppercase", letterSpacing: 1, marginBottom: 4,
              }}>
                Skills ({displayTools.skills.length})
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {displayTools.skills.map((s) => (
                  <div key={s.id} style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "2px 6px", borderRadius: 4,
                    background: t.accentSubtle,
                  }}>
                    <span style={{ fontSize: 10, color: t.accent, fontWeight: 500 }}>
                      {s.name || s.id}
                    </span>
                  </div>
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

        {/* Footer — link to context tab */}
        <div style={{
          padding: "10px 16px",
          borderTop: `1px solid ${t.surfaceBorder}`,
          display: "flex", flexDirection: "row",
          justifyContent: "center",
        }}>
          <button
            onClick={() => { onClose(); navigate(`/channels/${channelId}/settings#context`); }}
            style={{
              background: "none", border: "none", cursor: "pointer",
              fontSize: 11, color: t.accent, fontWeight: 500,
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.textDecoration = "underline"; }}
            onMouseLeave={(e) => { e.currentTarget.style.textDecoration = "none"; }}
          >
            View full context details
            <ExternalLink size={10} />
          </button>
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

function ConfigOverhead({ estimate, t }: { estimate: ContextEstimate; t: any }) {
  const pct = estimate.overhead_pct != null ? Math.round(estimate.overhead_pct * 100) : null;
  const barColor = pct == null ? t.textDim : pct > 40 ? "#ef4444" : pct > 20 ? "#eab308" : "#22c55e";
  const tokensK = Math.round(estimate.approx_tokens / 1000);
  const windowK = Math.round(estimate.context_window / 1000);

  // Map raw labels to user-friendly names
  const labelMap: Record<string, string> = {
    "sys:global_base_prompt": "Global prompt",
    "sys:base_prompt": "Platform prompt",
    "sys:datetime": "Date/time",
    "sys:system_prompt": "System prompt",
    "sys:persona": "Persona",
    "sys:skill_index": "Skill index",
    "sys:tool_index": "Tool index",
    "sys:delegate_index": "Delegation",
    "sys:memory (typical)": "Memory",
    "sys:knowledge (typical)": "Knowledge",
    "sys:pinned_knowledge (typical)": "Pinned knowledge",
    "sys:fs_context (typical)": "File system",
    "sys:section_index (typical)": "Section index",
    "sys:audio": "Audio",
    "tools:param": "Tools",
    "tools:param (schemas)": "Tool schemas",
    "tools:param (all schemas)": "Tool schemas",
  };

  const displayLines = estimate.lines
    .filter((l) => l.chars > 0)
    .map((l) => ({
      label: labelMap[l.label] || l.label,
      tokens: Math.round(l.chars / 4),
      hint: l.hint,
    }))
    .sort((a, b) => b.tokens - a.tokens);

  return (
    <div>
      <div style={{
        fontSize: 9, fontWeight: 700, color: t.textDim,
        textTransform: "uppercase", letterSpacing: 1, marginBottom: 6,
      }}>
        Configuration Overhead
      </div>
      {/* Bar */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <div style={{
          flex: 1, height: 6, borderRadius: 3,
          background: t.surfaceOverlay, overflow: "hidden",
        }}>
          <div style={{
            width: `${Math.min(pct ?? 0, 100)}%`, height: "100%",
            background: barColor, borderRadius: 3,
            transition: "width 0.3s, background-color 0.3s",
          }} />
        </div>
        <span style={{ fontSize: 10, fontWeight: 600, color: barColor, whiteSpace: "nowrap" }}>
          {pct != null ? `${pct}%` : "?"} ({tokensK}K / {windowK}K)
        </span>
      </div>
      {/* Breakdown */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {displayLines.map((line, i) => (
          <div key={i} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "2px 0",
          }}
          title={line.hint || undefined}
          >
            <span style={{ fontSize: 10, color: t.text, flex: 1 }}>{line.label}</span>
            <span style={{ fontSize: 10, fontFamily: "monospace", color: t.textMuted }}>
              ~{line.tokens >= 1000 ? `${Math.round(line.tokens / 1000)}K` : line.tokens} tokens
            </span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 9, color: t.textDim, marginTop: 4, fontStyle: "italic" }}>
        {estimate.disclaimer}
      </div>
    </div>
  );
}

function CaparacesSection({ carapaces, sources }: { carapaces: string[]; sources: Record<string, string> }) {
  const t = useThemeTokens();
  return (
    <div>
      <div style={{
        fontSize: 9, fontWeight: 700, color: t.textDim,
        textTransform: "uppercase", letterSpacing: 1, marginBottom: 4,
      }}>
        Capabilities ({carapaces.length})
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {carapaces.map((id) => (
          <div key={id} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "3px 8px", borderRadius: 4,
            background: t.purpleSubtle,
            border: `1px solid ${t.purpleBorder}`,
          }}>
            <Shield size={10} color={t.purple} />
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
  const ReactDOM = require("react-dom");
  return ReactDOM.createPortal(
    <BotInfoPanelContent {...props} />,
    document.body,
  );
}
