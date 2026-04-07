import { useState, useMemo } from "react";
import { useWindowDimensions } from "react-native";
import { Search, X, Info, AlertTriangle, Plus, Pin, Wrench, Shield, Puzzle, Server, ChevronDown, ChevronRight } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import {
  TextInput, SelectInput, Toggle, FormRow, Row, Col,
} from "@/src/components/shared/FormControls";
import { AdvancedSection } from "@/src/components/shared/SettingsControls";
import type { BotConfig, BotEditorData, ToolGroup, ResolvedToolEntry } from "@/src/types/api";
import { MOBILE_NAV_BREAKPOINT } from "./constants";
import { ToolSchemaModal } from "./ToolSchemaModal";

// ---------------------------------------------------------------------------
// Pinned Tools picker (default view)
// ---------------------------------------------------------------------------
function PinnedToolsPicker({
  editorData, draft, update,
}: {
  editorData: BotEditorData; draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
}) {
  const t = useThemeTokens();
  const pinnedTools = draft.pinned_tools || [];
  const localTools = draft.local_tools || [];
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");

  const allToolsByName = useMemo(() => {
    const map = new Map<string, { name: string; description?: string | null }>();
    for (const g of editorData.tool_groups) {
      for (const p of g.packs) {
        for (const tool of p.tools) {
          map.set(tool.name, tool);
        }
      }
    }
    return map;
  }, [editorData.tool_groups]);

  // Build grouped, filtered results for the search dropdown
  const groupedResults = useMemo(() => {
    const pinSet = new Set(pinnedTools);
    const q = search.toLowerCase();
    return editorData.tool_groups
      .map((group) => {
        const tools = group.packs.flatMap((p) => p.tools).filter((tool) => {
          if (pinSet.has(tool.name)) return false;
          if (!q) return true;
          return (
            tool.name.toLowerCase().includes(q) ||
            (tool.description && tool.description.toLowerCase().includes(q))
          );
        });
        return { ...group, tools };
      })
      .filter((g) => g.tools.length > 0);
  }, [editorData.tool_groups, pinnedTools, search]);

  const addPin = (name: string) => {
    const nextPinned = [...pinnedTools, name];
    const nextLocal = localTools.includes(name) ? localTools : [...localTools, name];
    update({ pinned_tools: nextPinned, local_tools: nextLocal });
  };

  const removePin = (name: string) => {
    update({ pinned_tools: pinnedTools.filter((n) => n !== name) });
  };

  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        Pinned Tools
      </div>
      {pinnedTools.length === 0 && !adding && (
        <div style={{ fontSize: 11, color: t.textDim, padding: "4px 0 8px" }}>
          No pinned tools. Tools are discovered automatically per conversation.
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
        {pinnedTools.map((name) => {
          const tool = allToolsByName.get(name);
          return (
            <div key={name} style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "3px 8px", borderRadius: 4, fontSize: 11,
              background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
            }}>
              <Pin size={9} color={t.accent} />
              <span style={{ fontFamily: "monospace", color: t.accent }}
                title={tool?.description || name}>{name}</span>
              <button
                onClick={() => removePin(name)}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex" }}
                title="Unpin"
              >
                <X size={10} color={t.textDim} />
              </button>
            </div>
          );
        })}
        {!adding && (
          <button
            onClick={() => setAdding(true)}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "3px 8px", borderRadius: 4, fontSize: 11,
              background: "transparent", border: `1px dashed ${t.surfaceBorder}`,
              color: t.textDim, cursor: "pointer",
            }}
          >
            <Plus size={10} /> Pin a tool
          </button>
        )}
      </div>
      {adding && (
        <div style={{
          padding: 8, borderRadius: 6,
          border: `1px solid ${t.surfaceBorder}`, background: t.inputBg,
          marginBottom: 8,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
            <Search size={12} color={t.textDim} />
            <input
              type="text" value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search tools to pin..."
              autoFocus
              style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }}
            />
            <button onClick={() => { setAdding(false); setSearch(""); }}
              style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>
              <X size={12} color={t.textDim} />
            </button>
          </div>
          <div style={{ maxHeight: 260, overflow: "auto" }}>
            {groupedResults.length === 0 && (
              <span style={{ fontSize: 11, color: t.textDim, padding: 4, display: "block" }}>No matching tools</span>
            )}
            {groupedResults.map((group) => (
              <div key={group.integration}>
                <div style={{
                  fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase",
                  letterSpacing: "0.05em", padding: "6px 6px 2px",
                  borderTop: `1px solid ${t.inputBg}`,
                }}>
                  {group.is_core ? "Core" : group.integration}
                </div>
                {group.tools.map((tool) => (
                  <button key={tool.name} onClick={() => { addPin(tool.name); setSearch(""); }}
                    style={{
                      display: "block", width: "100%", textAlign: "left",
                      padding: "4px 6px", fontSize: 11,
                      color: t.text, background: "transparent", border: "none",
                      cursor: "pointer", borderRadius: 3,
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = t.surfaceOverlay; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
                  >
                    <span style={{ fontFamily: "monospace" }}>{tool.name}</span>
                    {tool.description && (
                      <span style={{ fontSize: 10, color: t.textDim, marginLeft: 6 }}>
                        {tool.description.length > 60 ? tool.description.slice(0, 60) + "\u2026" : tool.description}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MCP Servers section (compact toggles)
// ---------------------------------------------------------------------------
function McpServersSection({
  editorData, draft, update, filter,
}: {
  editorData: BotEditorData; draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
  filter: string;
}) {
  const t = useThemeTokens();
  const { width } = useWindowDimensions();
  const mobile = width < MOBILE_NAV_BREAKPOINT;

  const toggleMcp = (name: string) => {
    const cur = draft.mcp_servers || [];
    update({ mcp_servers: cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name] });
  };

  if (editorData.mcp_servers.length === 0) return null;

  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>MCP Servers</div>
      <div style={{ display: "grid", gridTemplateColumns: mobile ? "1fr" : "1fr 1fr", gap: 2 }}>
        {editorData.mcp_servers.filter((s) => !filter || s.toLowerCase().includes(filter)).map((srv) => {
          const on = (draft.mcp_servers || []).includes(srv);
          return (
            <label key={srv} style={{
              display: "flex", alignItems: "center", gap: 6, padding: "4px 8px",
              borderRadius: 4, cursor: "pointer", fontSize: 11,
              background: on ? t.accentSubtle : "transparent",
              border: `1px solid ${on ? t.accentBorder : "transparent"}`,
            }}>
              <input type="checkbox" checked={on} onChange={() => toggleMcp(srv)} style={{ accentColor: t.accent }} />
              <span style={{ fontFamily: "monospace", color: on ? t.accent : t.textDim }}>{srv}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Client Tools section (compact toggles)
// ---------------------------------------------------------------------------
function ClientToolsSection({
  editorData, draft, update, filter,
}: {
  editorData: BotEditorData; draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
  filter: string;
}) {
  const t = useThemeTokens();
  const { width } = useWindowDimensions();
  const mobile = width < MOBILE_NAV_BREAKPOINT;

  const toggleClient = (name: string) => {
    const cur = draft.client_tools || [];
    update({ client_tools: cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name] });
  };

  if (editorData.client_tools.length === 0) return null;

  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Client Tools</div>
      <div style={{ display: "grid", gridTemplateColumns: mobile ? "1fr" : "1fr 1fr", gap: 2 }}>
        {editorData.client_tools.filter((ct) => !filter || ct.toLowerCase().includes(filter)).map((tool) => {
          const on = (draft.client_tools || []).includes(tool);
          return (
            <label key={tool} style={{
              display: "flex", alignItems: "center", gap: 6, padding: "4px 8px",
              borderRadius: 4, cursor: "pointer", fontSize: 11,
              background: on ? t.accentSubtle : "transparent",
              border: `1px solid ${on ? t.accentBorder : "transparent"}`,
            }}>
              <input type="checkbox" checked={on} onChange={() => toggleClient(tool)} style={{ accentColor: t.accent }} />
              <span style={{ fontFamily: "monospace", color: on ? t.accent : t.textDim }}>{tool}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Full tool list (advanced view)
// ---------------------------------------------------------------------------
function FullToolList({
  editorData, draft, update,
}: {
  editorData: BotEditorData; draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
}) {
  const [toolFilter, setToolFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [schemaModalTool, setSchemaModalTool] = useState<string | null>(null);

  const localTools = draft.local_tools || [];
  const pinnedTools = draft.pinned_tools || [];
  const excludeTools: string[] = (draft.tool_result_config as any)?.exclude_tools || [];

  const autoInjectedTools = new Set<string>();
  if (draft.memory_scheme === "workspace-files") {
    autoInjectedTools.add("search_memory");
    autoInjectedTools.add("get_memory_file");
    autoInjectedTools.add("file");
  }
  if (draft.history_mode === "file" || draft.history_mode === "structured") {
    autoInjectedTools.add("read_conversation_history");
  }

  const toggleTool = (name: string) => {
    if (localTools.includes(name)) {
      update({
        local_tools: localTools.filter((n) => n !== name),
        pinned_tools: pinnedTools.filter((n) => n !== name),
      });
    } else {
      update({ local_tools: [...localTools, name] });
    }
  };

  const togglePin = (name: string) => {
    const next = pinnedTools.includes(name)
      ? pinnedTools.filter((n) => n !== name)
      : [...pinnedTools, name];
    update({ pinned_tools: next });
  };

  const toggleNoSum = (name: string) => {
    const next = excludeTools.includes(name)
      ? excludeTools.filter((n) => n !== name)
      : [...excludeTools, name];
    update({ tool_result_config: { ...draft.tool_result_config, exclude_tools: next } });
  };

  const togglePack = (toolNames: string[]) => {
    const allEnabled = toolNames.every((n) => localTools.includes(n));
    if (allEnabled) {
      update({
        local_tools: localTools.filter((n) => !toolNames.includes(n)),
        pinned_tools: pinnedTools.filter((n) => !toolNames.includes(n)),
      });
    } else {
      const toAdd = toolNames.filter((n) => !localTools.includes(n));
      update({ local_tools: [...localTools, ...toAdd] });
    }
  };

  const toggleGroup = (group: ToolGroup) => {
    const allNames = group.packs.flatMap((p) => p.tools.map((tool) => tool.name));
    const allEnabled = allNames.every((n) => localTools.includes(n));
    if (allEnabled) {
      update({
        local_tools: localTools.filter((n) => !allNames.includes(n)),
        pinned_tools: pinnedTools.filter((n) => !allNames.includes(n)),
      });
    } else {
      const toAdd = allNames.filter((n) => !localTools.includes(n));
      update({ local_tools: [...localTools, ...toAdd] });
    }
  };

  const t = useThemeTokens();
  const { width } = useWindowDimensions();
  const toolsMobile = width < MOBILE_NAV_BREAKPOINT;
  const q = toolFilter.toLowerCase();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Search bar + counts */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6, flex: 1,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6, padding: "5px 10px",
        }}>
          <Search size={12} color={t.textDim} />
          <input
            type="text" value={toolFilter}
            onChange={(e) => setToolFilter(e.target.value)}
            placeholder="Search tools..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }}
          />
          {toolFilter && (
            <button onClick={() => setToolFilter("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>
              <X size={10} color={t.textDim} />
            </button>
          )}
        </div>
        <span style={{ fontSize: 11, color: t.textDim }}>
          {localTools.length} selected
          {autoInjectedTools.size > 0 && <> · <span style={{ color: t.purple }}>{autoInjectedTools.size} auto</span></>}
          {pinnedTools.length > 0 && <> · {pinnedTools.length} pinned</>}
        </span>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, fontSize: 10, color: t.textDim, flexWrap: "wrap" }}>
        <span>&#10003; = enabled</span>
        {autoInjectedTools.size > 0 && <span style={{ color: t.purple }}>auto = injected by memory scheme</span>}
        {draft.tool_retrieval && <span style={{ color: "#eab308" }}>pinned = always available</span>}
        <span style={{ color: "#f97316" }}>skip sum = skip summarization</span>
      </div>

      {/* Local tool groups */}
      {editorData.tool_groups.map((group) => {
        const groupKey = group.integration;
        return (
          <div key={groupKey} style={{ border: `1px solid ${t.surfaceRaised}`, borderRadius: 8, overflow: "hidden" }}>
            {/* Group header */}
            <div style={{
              padding: "6px 10px", background: t.surface,
              display: "flex", alignItems: "center", gap: 6,
            }}>
              {group.is_core ? (
                <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted }}>Core</span>
              ) : (
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 3,
                  background: t.warningSubtle, color: t.warningMuted, textTransform: "uppercase",
                }}>
                  {group.integration}
                </span>
              )}
              {(() => {
                const allNames = group.packs.flatMap((p) => p.tools.map((tool) => tool.name));
                const selectedCount = allNames.filter((n) => localTools.includes(n)).length;
                const allEnabled = selectedCount === allNames.length && allNames.length > 0;
                return (
                  <>
                    <span style={{ fontSize: 9, color: t.textDim, marginLeft: "auto" }}>
                      {selectedCount}/{allNames.length}
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); toggleGroup(group); }}
                      style={{
                        background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                        padding: "1px 6px", fontSize: 9, cursor: "pointer",
                        color: allEnabled ? t.dangerMuted : t.success,
                      }}
                      title={allEnabled ? "Deselect all in group" : "Select all in group"}
                    >
                      {allEnabled ? "none" : "all"}
                    </button>
                  </>
                );
              })()}
            </div>

            {/* Packs */}
            {group.packs.map((pack) => {
              const packKey = `${groupKey}::${pack.pack}`;
              const filtered = q ? pack.tools.filter((tool) => tool.name.toLowerCase().includes(q)) : pack.tools;
              if (filtered.length === 0) return null;

              const packNames = pack.tools.map((tool) => tool.name);
              const allEnabled = packNames.every((n) => localTools.includes(n));
              const someEnabled = packNames.some((n) => localTools.includes(n));
              const isCollapsed = !q && collapsed[packKey];

              return (
                <div key={pack.pack}>
                  {group.packs.length > 1 && (
                    <div
                      style={{
                        display: "flex", alignItems: "center", gap: 6,
                        padding: "4px 10px", background: `${t.surface}66`, cursor: "pointer",
                        borderTop: `1px solid ${t.inputBg}`,
                      }}
                      onClick={() => setCollapsed((c) => ({ ...c, [packKey]: !c[packKey] }))}
                    >
                      <span style={{
                        fontSize: 8, color: t.textDim, transform: isCollapsed ? "rotate(0deg)" : "rotate(90deg)",
                        transition: "transform 0.15s", display: "inline-block",
                      }}>&#9654;</span>
                      <span style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", flex: 1 }}>
                        {pack.label ?? pack.pack}
                      </span>
                      <button
                        onClick={(e) => { e.stopPropagation(); togglePack(packNames); }}
                        style={{
                          background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                          padding: "1px 6px", fontSize: 9, cursor: "pointer",
                          color: allEnabled ? t.dangerMuted : t.success,
                        }}
                        title={allEnabled ? "Disable all" : "Enable all"}
                      >
                        {allEnabled ? "none" : someEnabled ? "all" : "all"}
                      </button>
                      <span style={{ fontSize: 9, color: t.textDim }}>{packNames.filter((n) => localTools.includes(n)).length}/{packNames.length}</span>
                    </div>
                  )}

                  {pack.warning && (
                    <div style={{
                      display: "flex", alignItems: "center", gap: 6,
                      padding: "3px 10px", fontSize: 10,
                      background: t.warningSubtle, color: t.warningMuted,
                      borderTop: `1px solid ${t.inputBg}`,
                    }}>
                      <AlertTriangle size={10} />
                      <span>{pack.warning}</span>
                    </div>
                  )}

                  {!isCollapsed && (
                    <div style={{ display: "grid", gridTemplateColumns: toolsMobile ? "1fr" : "1fr 1fr", gap: 1, padding: 4 }}>
                      {filtered.map((tool) => {
                        const autoInj = autoInjectedTools.has(tool.name);
                        const enabled = localTools.includes(tool.name) || autoInj;
                        const pinned = pinnedTools.includes(tool.name);
                        const noSum = excludeTools.includes(tool.name);
                        return (
                          <div
                            key={tool.name}
                            style={{
                              display: "flex", alignItems: "center", gap: 4,
                              padding: "3px 6px", borderRadius: 3, fontSize: 11,
                              background: autoInj ? t.purpleSubtle : enabled ? t.accentSubtle : "transparent",
                              border: `1px solid ${autoInj ? t.purpleBorder : enabled ? t.accentBorder : "transparent"}`,
                            }}
                          >
                            <input
                              type="checkbox" checked={enabled}
                              onChange={() => !autoInj && toggleTool(tool.name)}
                              disabled={autoInj}
                              style={{ accentColor: autoInj ? t.purple : t.accent, cursor: autoInj ? "default" : undefined }}
                              title={autoInj ? "Auto-injected by memory scheme" : undefined}
                            />
                            <span
                              style={{
                                fontFamily: "monospace", color: autoInj ? t.purple : enabled ? t.accent : t.textDim,
                                flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                              }}
                              title={autoInj ? `${tool.name} — auto-injected by workspace-files memory scheme` : tool.description || tool.name}
                            >
                              {tool.name}
                            </span>
                            <button
                              onClick={(e) => { e.stopPropagation(); setSchemaModalTool(tool.name); }}
                              title="View tool schema"
                              style={{
                                background: "none", border: "none", cursor: "pointer",
                                padding: 0, display: "flex", alignItems: "center",
                                opacity: 0.3, color: t.textDim,
                              }}
                              onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.opacity = "0.8"; }}
                              onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.opacity = "0.3"; }}
                            >
                              <Info size={11} />
                            </button>
                            {autoInj && (
                              <span style={{
                                fontSize: 8, fontWeight: 700, padding: "0px 4px", borderRadius: 3,
                                background: t.purpleSubtle, color: t.purple, textTransform: "uppercase",
                                letterSpacing: "0.05em", whiteSpace: "nowrap",
                              }}>auto</span>
                            )}
                            {enabled && draft.tool_retrieval && (
                              <button
                                onClick={() => togglePin(tool.name)}
                                title={pinned ? "Unpin" : "Pin (bypass RAG)"}
                                style={{
                                  background: "none", border: "none", cursor: "pointer",
                                  fontSize: 10, padding: 0, opacity: pinned ? 1 : 0.25,
                                }}
                              >
                                <Pin size={10} />
                              </button>
                            )}
                            {enabled && (
                              <button
                                onClick={() => toggleNoSum(tool.name)}
                                title={noSum ? "Allow summarization" : "Skip summarization"}
                                style={{
                                  background: "none", border: "none", cursor: "pointer",
                                  fontSize: 10, padding: 0, opacity: noSum ? 1 : 0.25, color: "#f97316",
                                }}
                              >
                                &#128263;
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}

      {schemaModalTool && (
        <ToolSchemaModal
          toolName={schemaModalTool}
          onClose={() => setSchemaModalTool(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Resolved capabilities summary (read-only, bot-level)
// ---------------------------------------------------------------------------

/** Color for a provenance source tag */
function sourceColor(source: string, t: ReturnType<typeof useThemeTokens>): string {
  if (source === "bot") return t.textDim;
  if (source.startsWith("carapace:")) return t.purple || "#8b5cf6";
  if (source === "memory_scheme") return "#10b981";
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
  // Sort: "bot" first, then carapaces, then memory_scheme
  const order = (s: string) => s === "bot" ? 0 : s.startsWith("carapace:") ? 1 : 2;
  return [...map.entries()]
    .sort(([a], [b]) => order(a) - order(b))
    .map(([source, { label, tools }]) => ({ source, label, tools }));
}

function ResolvedSummary({ editorData, draft }: { editorData: BotEditorData; draft: BotConfig }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);

  const preview = editorData.resolved_preview;
  const skills = draft.skills || [];
  const carapaces = draft.carapaces || [];
  const clientTools = draft.client_tools || [];

  // Use resolved preview if available, fall back to draft data
  const toolCount = preview ? preview.tools.length : (draft.local_tools || []).length;
  const pinnedCount = preview ? preview.pinned_tools.length : (draft.pinned_tools || []).length;
  const mcpCount = preview ? preview.mcp_servers.length : (draft.mcp_servers || []).length;

  // Group tools by source for provenance display
  const toolGroups = useMemo(() => {
    if (!preview) return [];
    return groupBySource(preview.tools);
  }, [preview]);

  const pinnedGroups = useMemo(() => {
    if (!preview) return [];
    return groupBySource(preview.pinned_tools);
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

  const renderToolChip = (name: string, color: string) => (
    <span key={name} style={{
      fontSize: 10, fontFamily: "monospace", padding: "1px 6px", borderRadius: 3,
      background: t.surfaceOverlay, color: t.textMuted,
    }}>
      {name}
    </span>
  );

  const renderSourceGroup = (
    group: { source: string; label: string; tools: string[] },
    sectionLabel?: string,
  ) => {
    const color = sourceColor(group.source, t);
    return (
      <div key={`${sectionLabel || ""}:${group.source}`} style={{ marginBottom: 2 }}>
        <div style={{
          fontSize: 9, color, fontWeight: 600,
          marginBottom: 2, display: "flex", alignItems: "center", gap: 4,
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
        <div style={{ display: "flex", flexWrap: "wrap", gap: 3, marginLeft: 2 }}>
          {group.tools.map((name) => renderToolChip(name, color))}
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
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 12px", cursor: "pointer",
          background: t.surface,
        }}
      >
        {expanded ? <ChevronDown size={12} color={t.textDim} /> : <ChevronRight size={12} color={t.textDim} />}
        <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted }}>
          Resolved Capabilities
        </span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {toolCount > 0 && (
            <span style={{ fontSize: 10, color: t.textDim, display: "inline-flex", alignItems: "center", gap: 3 }}>
              <Wrench size={9} /> {toolCount}
            </span>
          )}
          {carapaces.length > 0 && (
            <span style={{ fontSize: 10, color: t.textDim, display: "inline-flex", alignItems: "center", gap: 3 }}>
              <Shield size={9} /> {carapaces.length}
            </span>
          )}
          {skills.length > 0 && (
            <span style={{ fontSize: 10, color: t.textDim, display: "inline-flex", alignItems: "center", gap: 3 }}>
              <Puzzle size={9} /> {skills.length}
            </span>
          )}
          {mcpCount > 0 && (
            <span style={{ fontSize: 10, color: t.textDim, display: "inline-flex", alignItems: "center", gap: 3 }}>
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
              <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
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

          {/* Tools — with provenance (new) or grouped by integration (fallback) */}
          {preview ? (
            <>
              {/* Pinned tools with provenance */}
              {pinnedGroups.length > 0 && (
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: "#eab308", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                    Pinned ({pinnedCount})
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingLeft: 4 }}>
                    {pinnedGroups.map((g) => renderSourceGroup(g, "pinned"))}
                  </div>
                </div>
              )}

              {/* All tools with provenance */}
              {toolGroups.length > 0 && (
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                    Tools ({toolCount})
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
              {/* Fallback: pinned tools (no provenance) */}
              {(draft.pinned_tools || []).length > 0 && (
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: "#eab308", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
                    Pinned ({(draft.pinned_tools || []).length})
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                    {(draft.pinned_tools || []).map((name) => renderToolChip(name, t.textMuted))}
                  </div>
                </div>
              )}

              {/* Fallback: tools grouped by integration */}
              {fallbackGroupedTools.map((group) => (
                <div key={group.integration}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
                    {group.is_core ? "Core" : group.integration} ({group.tools.length})
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                    {group.tools.map((tool) => renderToolChip(tool.name, t.textMuted))}
                  </div>
                </div>
              ))}

              {/* Fallback: MCP servers */}
              {(draft.mcp_servers || []).length > 0 && (
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
                    MCP Servers ({(draft.mcp_servers || []).length})
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                    {(draft.mcp_servers || []).map((s) => renderToolChip(s, t.textMuted))}
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
              <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
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
              <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                {clientTools.map((ct) => renderToolChip(ct, t.textMuted))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------
export function ToolsSection({
  editorData,
  draft,
  update,
}: {
  editorData: BotEditorData;
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
}) {
  const t = useThemeTokens();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Info text */}
      <div style={{ fontSize: 11, color: t.textDim }}>
        Tools are automatically discovered based on conversation context. Pin specific tools to always include them.
      </div>

      {/* Resolved capabilities summary */}
      <ResolvedSummary editorData={editorData} draft={draft} />

      {/* Pinned Tools */}
      <PinnedToolsPicker editorData={editorData} draft={draft} update={update} />

      {/* MCP Servers */}
      <McpServersSection editorData={editorData} draft={draft} update={update} filter="" />

      {/* Client Tools */}
      <ClientToolsSection editorData={editorData} draft={draft} update={update} filter="" />

      {/* Advanced: full tool list + settings */}
      <AdvancedSection title="Advanced Tool Settings">
        <div style={{ display: "flex", flexDirection: "column", gap: 16, paddingTop: 8 }}>
          {/* Full tool list */}
          <FullToolList editorData={editorData} draft={draft} update={update} />

          {/* Tool Retrieval */}
          <div style={{ borderTop: `1px solid ${t.surfaceRaised}`, paddingTop: 12 }}>
            <Toggle
              value={draft.tool_retrieval ?? true}
              onChange={(v) => update({ tool_retrieval: v })}
              label="Tool Retrieval (RAG)"
              description="Only pass top-K relevant tools per turn. Pinned tools bypass filtering."
            />
            {(draft.tool_retrieval ?? true) && (
              <div style={{ marginTop: 8, maxWidth: 300 }}>
                <FormRow label="Similarity Threshold">
                  <TextInput
                    value={String(draft.tool_similarity_threshold ?? "")}
                    onChangeText={(v) => update({ tool_similarity_threshold: v ? parseFloat(v) : null })}
                    placeholder="0.35" type="number"
                  />
                </FormRow>
              </div>
            )}
          </div>

          {/* Tool Discovery */}
          {(draft.tool_retrieval ?? true) && (
            <div style={{ borderTop: `1px solid ${t.surfaceRaised}`, paddingTop: 12 }}>
              <Toggle
                value={draft.tool_discovery ?? true}
                onChange={(v) => update({ tool_discovery: v })}
                label="Tool Discovery"
                description="Discover undeclared tools from the full tool pool via RAG. Disable to restrict to manually configured tools only."
              />
            </div>
          )}

          {/* Tool Result Summarization */}
          <div style={{ borderTop: `1px solid ${t.surfaceRaised}`, paddingTop: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: t.text, marginBottom: 4 }}>Tool Result Summarization</div>
            <div style={{ fontSize: 11, color: t.textDim, marginBottom: 8 }}>Summarizes large tool outputs.</div>
            <Row gap={12}>
              <Col>
                <SelectInput
                  value={draft.tool_result_config?.enabled === true ? "true" : draft.tool_result_config?.enabled === false ? "false" : ""}
                  onChange={(v) => {
                    const trc = { ...draft.tool_result_config };
                    if (v === "true") trc.enabled = true;
                    else if (v === "false") trc.enabled = false;
                    else delete trc.enabled;
                    update({ tool_result_config: trc });
                  }}
                  options={[
                    { label: "Inherit global", value: "" },
                    { label: "Force on", value: "true" },
                    { label: "Force off", value: "false" },
                  ]}
                />
              </Col>
              <Col>
                <FormRow label="Trigger size (chars)">
                  <TextInput
                    value={String((draft.tool_result_config as any)?.threshold ?? "")}
                    onChangeText={(v) => update({ tool_result_config: { ...draft.tool_result_config, threshold: v ? parseInt(v) : undefined } })}
                    placeholder="global (3000)" type="number"
                  />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="Summarizer model">
                  <LlmModelDropdown
                    value={(draft.tool_result_config as any)?.model ?? ""}
                    onChange={(v) => update({ tool_result_config: { ...draft.tool_result_config, model: v || undefined } })}
                    placeholder="global model"
                  />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="Max summary tokens">
                  <TextInput
                    value={String((draft.tool_result_config as any)?.max_tokens ?? "")}
                    onChangeText={(v) => update({ tool_result_config: { ...draft.tool_result_config, max_tokens: v ? parseInt(v) : undefined } })}
                    placeholder="global (300)" type="number"
                  />
                </FormRow>
              </Col>
            </Row>
          </div>
        </div>
      </AdvancedSection>
    </div>
  );
}
