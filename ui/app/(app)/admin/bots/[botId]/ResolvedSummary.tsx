/**
 * ResolvedSummary — read-only view of a bot's resolved tool set with provenance labels.
 * Shows a single unified list of all tools the bot will have, with pinned status
 * and source provenance for each.
 */
import { useState, useMemo } from "react";
import { Wrench, Shield, Puzzle, Server, Pin, ChevronDown, ChevronRight } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import type { BotConfig, BotEditorData, ResolvedToolEntry } from "@/src/types/api";

/** Color for a provenance source tag */
function sourceColor(source: string, t: ReturnType<typeof useThemeTokens>): string {
  if (source === "bot") return t.textDim;
  if (source.startsWith("carapace:")) return t.purple || "#8b5cf6";
  if (source === "memory_scheme") return "#10b981";
  if (source === "auto") return "#6366f1";
  return t.textDim;
}

/** Group resolved tool entries by source for display */
function groupBySource(entries: ResolvedToolEntry[]): { source: string; label: string; tools: string[] }[] {
  const map = new Map<string, { label: string; tools: string[] }>();
  for (const e of entries) {
    let group = map.get(e.source);
    if (!group) {
      group = { label: e.source_label, tools: [] };
      map.set(e.source, group);
    }
    group.tools.push(e.name);
  }
  const order = (s: string) => s === "bot" ? 0 : s.startsWith("carapace:") ? 1 : 2;
  return [...map.entries()]
    .sort(([a], [b]) => order(a) - order(b))
    .map(([source, { label, tools }]) => ({ source, label, tools }));
}

export function ResolvedSummary({ editorData, draft }: { editorData: BotEditorData; draft: BotConfig }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);

  const preview = editorData.resolved_preview;
  const skills = draft.skills || [];
  const carapaces = draft.carapaces || [];
  const clientTools = draft.client_tools || [];

  const toolCount = preview ? preview.tools.length : (draft.local_tools || []).length;
  const mcpCount = preview ? preview.mcp_servers.length : (draft.mcp_servers || []).length;

  // Build pinned set for marking tools
  const pinnedSet = useMemo(() => {
    if (!preview) return new Set(draft.pinned_tools || []);
    return new Set(preview.pinned_tools.map((e) => e.name));
  }, [preview, draft.pinned_tools]);

  const pinnedCount = pinnedSet.size;

  // Group tools by source for provenance display
  const toolGroups = useMemo(() => {
    if (!preview) return [];
    return groupBySource(preview.tools);
  }, [preview]);

  const mcpGroups = useMemo(() => {
    if (!preview) return [];
    return groupBySource(preview.mcp_servers);
  }, [preview]);

  // Fallback: group by integration (old behavior) when no preview
  const fallbackGroupedTools = useMemo(() => {
    if (preview) return [];
    const localTools = draft.local_tools || [];
    const enabled = new Set(localTools);
    return editorData.tool_groups
      .map((group) => {
        const tools = group.packs
          .flatMap((p) => p.tools)
          .filter((tool) => enabled.has(tool.name));
        return { integration: group.integration, is_core: group.is_core, tools };
      })
      .filter((g) => g.tools.length > 0);
  }, [preview, editorData.tool_groups, draft.local_tools]);

  /** Render a single tool chip, with optional pin indicator */
  const renderToolChip = (name: string) => {
    const pinned = pinnedSet.has(name);
    return (
      <span key={name} style={{
        fontSize: 10, fontFamily: "monospace", padding: "1px 6px", borderRadius: 3,
        background: pinned ? "#eab30810" : t.surfaceOverlay,
        color: pinned ? "#eab308" : t.textMuted,
        border: pinned ? "1px solid #eab30820" : undefined,
        display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
      }}>
        {pinned && <Pin size={7} />}
        {name}
      </span>
    );
  };

  /** Render a provenance source group with its tools */
  const renderSourceGroup = (
    group: { source: string; label: string; tools: string[] },
    sectionLabel?: string,
  ) => {
    const color = sourceColor(group.source, t);
    return (
      <div key={`${sectionLabel || ""}:${group.source}`} style={{ marginBottom: 2 }}>
        <div style={{
          fontSize: 9, color, fontWeight: 600,
          marginBottom: 2, display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
        }}>
          <span style={{
            padding: "0 4px", borderRadius: 3, lineHeight: "14px",
            background: `${color}12`, border: `1px solid ${color}25`,
          }}>
            {group.label}
          </span>
          <span style={{ color: t.textDim, fontWeight: 400 }}>
            ({group.tools.length})
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 3, marginLeft: 2 }}>
          {group.tools.map((name) => renderToolChip(name))}
        </div>
      </div>
    );
  };

  return (
    <div style={{
      borderRadius: 8,
      border: `1px solid ${t.surfaceRaised}`,
      overflow: "hidden",
    }}>
      <div
        onClick={() => setExpanded((e) => !e)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
          padding: "8px 12px", cursor: "pointer",
          background: t.surface,
        }}
      >
        {expanded ? <ChevronDown size={12} color={t.textDim} /> : <ChevronRight size={12} color={t.textDim} />}
        <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted }}>
          Resolved Capabilities
        </span>
        <span style={{ marginLeft: "auto", display: "flex", flexDirection: "row", gap: 8 }}>
          {toolCount > 0 && (
            <span style={{ fontSize: 10, color: t.textDim, display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
              <Wrench size={9} /> {toolCount}
            </span>
          )}
          {carapaces.length > 0 && (
            <span style={{ fontSize: 10, color: t.textDim, display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
              <Shield size={9} /> {carapaces.length}
            </span>
          )}
          {skills.length > 0 && (
            <span style={{ fontSize: 10, color: t.textDim, display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
              <Puzzle size={9} /> {skills.length}
            </span>
          )}
          {mcpCount > 0 && (
            <span style={{ fontSize: 10, color: t.textDim, display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
              <Server size={9} /> {mcpCount}
            </span>
          )}
        </span>
      </div>

      {expanded && (
        <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 10, borderTop: `1px solid ${t.inputBg}` }}>
          {/* Caveat */}
          <div style={{
            fontSize: 10, color: t.warningMuted, padding: "4px 8px",
            background: t.warningSubtle, borderRadius: 4,
            border: `1px solid ${t.warningSubtle}`,
            lineHeight: "15px",
          }}>
            Bot-level tools before channel overrides. Check a specific channel to see what applies there.
          </div>

          {/* Capabilities */}
          {carapaces.length > 0 && (
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
                Capabilities ({carapaces.length})
              </div>
              <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 3 }}>
                {carapaces.map((id) => (
                  <span key={id} style={{
                    fontSize: 10, padding: "1px 6px", borderRadius: 3,
                    background: `${t.purple || "#8b5cf6"}10`, color: t.purple || "#8b5cf6",
                    border: `1px solid ${t.purple || "#8b5cf6"}20`,
                  }}>
                    {id}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Unified tools list — with provenance (new) or grouped by integration (fallback) */}
          {preview ? (
            <>
              {toolGroups.length > 0 && (
                <div>
                  <div style={{
                    fontSize: 9, fontWeight: 700, color: t.textDim,
                    textTransform: "uppercase", letterSpacing: "0.05em",
                    marginBottom: 2,
                  }}>
                    Tools ({toolCount})
                  </div>
                  <div style={{
                    fontSize: 9, color: t.textDim, marginBottom: 6,
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                  }}>
                    All tools the bot can use.
                    {pinnedCount > 0 && (
                      <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 2, color: "#eab308" }}>
                        <Pin size={7} /> = pinned (always included)
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingLeft: 4 }}>
                    {toolGroups.map((g) => renderSourceGroup(g, "tools"))}
                  </div>
                </div>
              )}

              {/* MCP servers with provenance */}
              {mcpGroups.length > 0 && (
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                    MCP Servers ({mcpCount})
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingLeft: 4 }}>
                    {mcpGroups.map((g) => renderSourceGroup(g, "mcp"))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              {/* Fallback: tools grouped by integration */}
              {fallbackGroupedTools.length > 0 && (
                <div>
                  <div style={{
                    fontSize: 9, fontWeight: 700, color: t.textDim,
                    textTransform: "uppercase", letterSpacing: "0.05em",
                    marginBottom: 2,
                  }}>
                    Tools ({(draft.local_tools || []).length})
                  </div>
                  <div style={{
                    fontSize: 9, color: t.textDim, marginBottom: 6,
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                  }}>
                    All tools the bot can use.
                    {pinnedCount > 0 && (
                      <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 2, color: "#eab308" }}>
                        <Pin size={7} /> = pinned (always included)
                      </span>
                    )}
                  </div>
                  {fallbackGroupedTools.map((group) => (
                    <div key={group.integration} style={{ marginBottom: 4 }}>
                      <div style={{ fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
                        {group.is_core ? "Core" : group.integration} ({group.tools.length})
                      </div>
                      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 3 }}>
                        {group.tools.map((tool) => renderToolChip(tool.name))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Fallback: MCP servers */}
              {(draft.mcp_servers || []).length > 0 && (
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
                    MCP Servers ({(draft.mcp_servers || []).length})
                  </div>
                  <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 3 }}>
                    {(draft.mcp_servers || []).map((s) => renderToolChip(s))}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Skills */}
          {skills.length > 0 && (
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
                Skills ({skills.length})
              </div>
              <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 3 }}>
                {skills.map((s) => (
                  <span key={s.id} style={{
                    fontSize: 10, padding: "1px 6px", borderRadius: 3,
                    background: `${t.accent}12`, color: t.accent,
                    border: `1px solid ${t.accent}25`,
                  }}>
                    {s.id}{s.mode === "pinned" ? " (pinned)" : ""}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Client tools */}
          {clientTools.length > 0 && (
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
                Client Tools ({clientTools.length})
              </div>
              <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 3 }}>
                {clientTools.map((ct) => renderToolChip(ct))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
