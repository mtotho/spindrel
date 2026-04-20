import { useState, useMemo } from "react";
import { useSettings } from "@/src/api/hooks/useSettings";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { Search, X, Info, AlertTriangle, Plus, Pin } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import {
  TextInput, SelectInput, Toggle, FormRow, Row, Col,
} from "@/src/components/shared/FormControls";
import { AdvancedSection, InfoBanner } from "@/src/components/shared/SettingsControls";
import type { BotConfig, BotEditorData, ToolGroup } from "@/src/types/api";
import { ResolvedSummary } from "./ResolvedSummary";
import { MOBILE_NAV_BREAKPOINT } from "./constants";
import { ToolSchemaModal } from "./ToolSchemaModal";
import { EnrolledToolsPanel } from "./EnrolledToolsPanel";
import { useEnrolledTools } from "@/src/api/hooks/useEnrolledTools";

// ---------------------------------------------------------------------------
// Pinned Tools picker (default view)
// ---------------------------------------------------------------------------
function PinnedToolsPicker({
  editorData, draft, update, discovery,
}: {
  editorData: BotEditorData; draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
  discovery: boolean;
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
          {discovery
            ? "No pinned tools. All tools are discoverable \u2014 pin any that must be available every turn."
            : "No pinned tools. Enable tools below, then pin any that must be available every turn."}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
        {pinnedTools.map((name) => {
          const tool = allToolsByName.get(name);
          return (
            <div key={name} style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "3px 8px", borderRadius: 4, fontSize: 11,
              background: discovery ? t.warningSubtle : t.accentSubtle,
              border: `1px solid ${discovery ? t.warningBorder : t.accentBorder}`,
            }}>
              <Pin size={9} color={discovery ? t.warningMuted : t.accent} />
              <span style={{ fontFamily: "monospace", color: discovery ? t.warningMuted : t.accent }}
                title={tool?.description || name}>{name}</span>
              <button
                onClick={() => removePin(name)}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex", flexDirection: "row" }}
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
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
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
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
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
  const { width } = useWindowSize();
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
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "4px 8px",
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
  const { width } = useWindowSize();
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
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "4px 8px",
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
  editorData, draft, update, discovery,
}: {
  editorData: BotEditorData; draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
  discovery: boolean;
}) {
  const [toolFilter, setToolFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [schemaModalTool, setSchemaModalTool] = useState<string | null>(null);

  const localTools = draft.local_tools || [];
  const pinnedTools = draft.pinned_tools || [];
  const excludeTools: string[] = (draft.tool_result_config as any)?.exclude_tools || [];

  // Runtime-enrolled tools — accrued via successful tool calls / get_tool_info.
  // Tools present here but NOT in draft.local_tools are effectively pinned at
  // runtime but would otherwise render as "discoverable" in the list below.
  const { data: enrolledList } = useEnrolledTools(draft.id);
  const enrolledSet = useMemo(
    () => new Set((enrolledList || []).map((e) => e.tool_name)),
    [enrolledList],
  );

  const autoInjectedTools = new Set<string>();
  if (draft.memory_scheme === "workspace-files") {
    autoInjectedTools.add("search_memory");
    autoInjectedTools.add("get_memory_file");
    autoInjectedTools.add("file");
    autoInjectedTools.add("manage_bot_skill");
  }
  // Channel awareness — any bot can list channels and read history
  autoInjectedTools.add("list_channels");
  autoInjectedTools.add("read_conversation_history");
  // Tool retrieval: get_tool_info is always injected when tool_retrieval is on
  if (draft.tool_retrieval !== false) {
    autoInjectedTools.add("get_tool_info");
  }
  // Auto-discovery: search_tools is injected so the LLM can semantically search
  // the full pool when it doesn't see what it needs.
  if (draft.tool_retrieval !== false && draft.tool_discovery !== false) {
    autoInjectedTools.add("search_tools");
  }
  // Skill discovery: auto-injected when bot has skills
  if (editorData.all_skills.length > 0) {
    autoInjectedTools.add("get_skill");
    autoInjectedTools.add("get_skill_list");
  }
  // activate_capability is auto-injected by context assembly when capability
  // RAG finds relevant matches — the checkbox state is irrelevant.
  autoInjectedTools.add("activate_capability");

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
    const isPinned = pinnedTools.includes(name);
    if (isPinned) {
      update({ pinned_tools: pinnedTools.filter((n) => n !== name) });
    } else {
      const nextLocal = localTools.includes(name) ? localTools : [...localTools, name];
      update({ pinned_tools: [...pinnedTools, name], local_tools: nextLocal });
    }
  };

  const toggleNoSum = (name: string) => {
    const next = excludeTools.includes(name)
      ? excludeTools.filter((n) => n !== name)
      : [...excludeTools, name];
    update({ tool_result_config: { ...draft.tool_result_config, exclude_tools: next } });
  };

  // Discovery mode: cycle through discoverable → included → pinned → discoverable.
  // `enrolled` (runtime working-set) collapses into the same promotion path as
  // `discoverable`: clicking promotes it to `included` in the declared config.
  const cycleToolState = (name: string) => {
    const isPinned = pinnedTools.includes(name);
    const isIncluded = localTools.includes(name);
    if (isPinned) {
      // pinned → discoverable (remove from both)
      update({
        pinned_tools: pinnedTools.filter((n) => n !== name),
        local_tools: localTools.filter((n) => n !== name),
      });
    } else if (isIncluded) {
      // included → pinned
      update({ pinned_tools: [...pinnedTools, name] });
    } else {
      // discoverable / enrolled → included
      update({ local_tools: [...localTools, name] });
    }
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
  const { width } = useWindowSize();
  const toolsMobile = width < MOBILE_NAV_BREAKPOINT;
  const q = toolFilter.toLowerCase();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Search bar + counts */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flex: 1,
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
          {localTools.length} {discovery ? "included" : "enabled"}
          {autoInjectedTools.size > 0 && <> · <span style={{ color: t.purple }}>{autoInjectedTools.size} auto</span></>}
          {pinnedTools.length > 0 && <> · {pinnedTools.length} pinned</>}
        </span>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", flexDirection: "row", gap: 12, fontSize: 10, color: t.textDim, flexWrap: "wrap", alignItems: "center" }}>
        {discovery ? (
          <>
            <span>Click badge to cycle:</span>
            <span style={{
              padding: "1px 6px", borderRadius: 8, fontSize: 9, fontWeight: 600,
              border: `1px dashed ${t.surfaceBorder}`, color: t.textDim,
            }}>discover</span>
            <span style={{ color: t.textDim }}>{"\u2192"}</span>
            <span style={{
              padding: "1px 6px", borderRadius: 8, fontSize: 9, fontWeight: 600,
              background: t.accentSubtle, border: `1px solid ${t.accentBorder}`, color: t.accent,
            }}>included</span>
            <span style={{ color: t.textDim }}>{"\u2192"}</span>
            <span style={{
              padding: "1px 6px", borderRadius: 8, fontSize: 9, fontWeight: 600,
              background: t.warningSubtle, border: `1px solid ${t.warningBorder}`, color: t.warningMuted,
            }}><Pin size={7} style={{ display: "inline", verticalAlign: "middle", marginRight: 2 }} />pinned</span>
            <span style={{ color: t.textDim }}>{"\u2192 \u2026"}</span>
            <span style={{
              padding: "1px 6px", borderRadius: 8, fontSize: 9, fontWeight: 600,
              background: (t.successSubtle ?? t.accentSubtle),
              border: `1px solid ${t.successBorder ?? t.accentBorder}`,
              color: (t.success ?? t.accent),
            }}>enrolled</span>
            <span style={{ color: t.textDim }}>= accreted at runtime</span>
          </>
        ) : (
          <>
            <span>&#10003; = enabled</span>
            {draft.tool_retrieval && <span style={{ color: "#eab308" }}>pinned = always available</span>}
          </>
        )}
        {autoInjectedTools.size > 0 && <span style={{ color: t.purple }}>auto = injected at runtime</span>}
        <span style={{ color: "#f97316" }}>skip sum = skip summarization</span>
      </div>

      {/* Local tool groups */}
      {editorData.tool_groups.map((group) => {
        const groupKey = group.integration;

        // Cluster packs by their meta-group; ungrouped packs go under null key
        const metaClusters = new Map<string | null, typeof group.packs>();
        const metaOrder: (string | null)[] = [];
        for (const pack of group.packs) {
          const mg = pack.group ?? null;
          if (!metaClusters.has(mg)) { metaClusters.set(mg, []); metaOrder.push(mg); }
          metaClusters.get(mg)!.push(pack);
        }

        return (
          <div key={groupKey} style={{ border: `1px solid ${t.surfaceRaised}`, borderRadius: 8, overflow: "hidden" }}>
            {/* Integration header */}
            <div style={{
              padding: "6px 10px", background: t.surface,
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
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
                      title={discovery
                        ? (allEnabled ? "Clear all in group" : "Include all in group")
                        : (allEnabled ? "Disable all in group" : "Enable all in group")}
                    >
                      {allEnabled ? "none" : "all"}
                    </button>
                  </>
                );
              })()}
            </div>

            {/* Meta-grouped packs */}
            {metaOrder.map((metaGroup) => {
              const clusterPacks = metaClusters.get(metaGroup)!;
              const metaKey = `${groupKey}::meta::${metaGroup ?? "ungrouped"}`;
              const isMetaCollapsed = !q && collapsed[metaKey];

              // Ungrouped packs render without a meta-group header
              if (!metaGroup) {
                return <>{clusterPacks.map((pack) => renderPack(pack, groupKey))}</>;
              }

              const metaNames = clusterPacks.flatMap((p) => p.tools.map((tool) => tool.name));
              const metaSelected = metaNames.filter((n) => localTools.includes(n)).length;
              const metaAllEnabled = metaSelected === metaNames.length && metaNames.length > 0;

              return (
                <div key={metaKey}>
                  <div
                    style={{
                      display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                      padding: "5px 10px", background: `${t.surface}aa`,
                      borderTop: `1px solid ${t.surfaceRaised}`, cursor: "pointer",
                    }}
                    onClick={() => setCollapsed((c) => ({ ...c, [metaKey]: !c[metaKey] }))}
                  >
                    <span style={{
                      fontSize: 8, color: t.textDim, transform: isMetaCollapsed ? "rotate(0deg)" : "rotate(90deg)",
                      transition: "transform 0.15s", display: "inline-block",
                    }}>&#9654;</span>
                    <span style={{
                      fontSize: 10, fontWeight: 600, color: t.textMuted,
                      textTransform: "uppercase", letterSpacing: "0.06em", flex: 1,
                    }}>
                      {metaGroup}
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); togglePack(metaNames); }}
                      style={{
                        background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                        padding: "1px 6px", fontSize: 9, cursor: "pointer",
                        color: metaAllEnabled ? t.dangerMuted : t.success,
                      }}
                      title={metaAllEnabled ? "Disable all in group" : "Enable all in group"}
                    >
                      {metaAllEnabled ? "none" : "all"}
                    </button>
                    <span style={{ fontSize: 9, color: t.textDim }}>{metaSelected}/{metaNames.length}</span>
                  </div>
                  {!isMetaCollapsed && clusterPacks.map((pack) => renderPack(pack, groupKey))}
                </div>
              );
            })}
          </div>
        );

        function renderPack(pack: typeof group.packs[number], gKey: string) {
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
                        display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
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
                        title={discovery
                          ? (allEnabled ? "Clear all" : "Include all")
                          : (allEnabled ? "Disable all" : "Enable all")}
                      >
                        {allEnabled ? "none" : someEnabled ? "all" : "all"}
                      </button>
                      <span style={{ fontSize: 9, color: t.textDim }}>{packNames.filter((n) => localTools.includes(n)).length}/{packNames.length}</span>
                    </div>
                  )}

                  {pack.warning && (
                    <div style={{
                      display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
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
                        const isIncluded = localTools.includes(tool.name);
                        const enabled = isIncluded || autoInj;
                        const pinned = pinnedTools.includes(tool.name);
                        const isEnrolled = enrolledSet.has(tool.name);
                        const noSum = excludeTools.includes(tool.name);

                        // Discovery mode: 5 visual states. `enrolled` means the
                        // bot has accreted this tool into its working set at
                        // runtime (via get_tool_info or a successful call), but
                        // it's not in the declared local_tools list.
                        const toolState = discovery
                          ? (autoInj
                              ? "auto"
                              : pinned
                                ? "pinned"
                                : isIncluded
                                  ? "included"
                                  : isEnrolled
                                    ? "enrolled"
                                    : "discoverable")
                          : null;

                        const stateStyles: Record<string, { bg: string; border: string; color: string }> = {
                          pinned:       { bg: t.warningSubtle, border: t.warningBorder, color: t.warningMuted },
                          included:     { bg: t.accentSubtle,  border: t.accentBorder,  color: t.accent },
                          enrolled:     { bg: t.successSubtle ?? t.accentSubtle, border: t.successBorder ?? t.accentBorder, color: t.success ?? t.accent },
                          discoverable: { bg: "transparent",   border: "transparent",   color: t.textDim },
                          auto:         { bg: t.purpleSubtle,  border: t.purpleBorder,  color: t.purple },
                        };

                        const rowBg = toolState
                          ? stateStyles[toolState].bg
                          : (autoInj ? t.purpleSubtle : enabled ? t.accentSubtle : "transparent");
                        const rowBorder = toolState
                          ? stateStyles[toolState].border
                          : (autoInj ? t.purpleBorder : enabled ? t.accentBorder : "transparent");
                        const textColor = toolState
                          ? stateStyles[toolState].color
                          : (autoInj ? t.purple : enabled ? t.accent : t.textDim);

                        const badgeTooltips: Record<string, string> = {
                          pinned: "Always in context \u2014 click to make discoverable",
                          included: "Priority in search \u2014 click to pin",
                          enrolled: "Accreted at runtime (working set) \u2014 click to make it a declared inclusion",
                          discoverable: "Found via auto-discovery \u2014 click to include",
                          auto: "Injected automatically based on bot config",
                        };

                        return (
                          <div
                            key={tool.name}
                            style={{
                              display: "flex", flexDirection: "row", alignItems: "center", gap: discovery ? 6 : 4,
                              padding: "3px 6px", borderRadius: 3, fontSize: 11,
                              background: rowBg,
                              border: `1px solid ${rowBorder}`,
                            }}
                          >
                            {discovery && toolState ? (
                              <button
                                disabled={autoInj}
                                onClick={() => cycleToolState(tool.name)}
                                title={badgeTooltips[toolState]}
                                style={{
                                  display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
                                  padding: "1px 6px", borderRadius: 8, fontSize: 9, fontWeight: 600,
                                  background: "transparent",
                                  border: `1px ${toolState === "discoverable" ? "dashed" : "solid"} ${toolState === "discoverable" ? t.surfaceBorder : stateStyles[toolState].border}`,
                                  color: stateStyles[toolState].color,
                                  cursor: autoInj ? "default" : "pointer",
                                  minWidth: 70, justifyContent: "center",
                                  textTransform: "uppercase", letterSpacing: "0.03em",
                                  flexShrink: 0,
                                  transition: "all 0.15s",
                                }}
                              >
                                {toolState === "pinned" && <Pin size={8} />}
                                {toolState === "discoverable" ? "discover" : toolState}
                              </button>
                            ) : (
                              <input
                                type="checkbox" checked={enabled}
                                onChange={() => !autoInj && toggleTool(tool.name)}
                                disabled={autoInj}
                                style={{ accentColor: autoInj ? t.purple : t.accent, cursor: autoInj ? "default" : undefined }}
                                title={autoInj ? "Auto-injected at runtime" : undefined}
                              />
                            )}
                            <span
                              style={{
                                fontFamily: "monospace", color: textColor,
                                flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                              }}
                              title={autoInj ? `${tool.name} \u2014 auto-injected at runtime` : tool.description || tool.name}
                            >
                              {tool.name}
                            </span>
                            <button
                              onClick={(e) => { e.stopPropagation(); setSchemaModalTool(tool.name); }}
                              title="View tool schema"
                              style={{
                                background: "none", border: "none", cursor: "pointer",
                                padding: 0, display: "flex", flexDirection: "row", alignItems: "center",
                                opacity: 0.3, color: t.textDim,
                              }}
                              onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.opacity = "0.8"; }}
                              onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.opacity = "0.3"; }}
                            >
                              <Info size={11} />
                            </button>
                            {!discovery && autoInj && (
                              <span style={{
                                fontSize: 8, fontWeight: 700, padding: "0px 4px", borderRadius: 3,
                                background: t.purpleSubtle, color: t.purple, textTransform: "uppercase",
                                letterSpacing: "0.05em", whiteSpace: "nowrap",
                              }}>auto</span>
                            )}
                            {!discovery && enabled && draft.tool_retrieval && (
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
                            {(discovery ? (toolState === "included" || toolState === "pinned") : enabled) && (
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
        }
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

  // Global settings — show inherited values in tool result summarization fields
  const { data: settingsData } = useSettings();
  const globalToolSum = useMemo(() => {
    if (!settingsData) return { enabled: true, threshold: "3000", model: "", maxTokens: "300" };
    const all = settingsData.groups.flatMap((g) => g.settings);
    const get = (key: string) => all.find((s) => s.key === key);
    return {
      enabled: get("TOOL_RESULT_SUMMARIZE_ENABLED")?.value ?? true,
      threshold: String(get("TOOL_RESULT_SUMMARIZE_THRESHOLD")?.value ?? "3000"),
      model: String(get("TOOL_RESULT_SUMMARIZE_MODEL")?.value ?? ""),
      maxTokens: String(get("TOOL_RESULT_SUMMARIZE_MAX_TOKENS")?.value ?? "300"),
    };
  }, [settingsData]);

  const retrieval = draft.tool_retrieval ?? true;
  const discovery = retrieval && (draft.tool_discovery ?? true);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Discovery & Retrieval */}
      <div style={{
        display: "flex", flexDirection: "column", gap: 12,
        padding: "14px 16px", borderRadius: 10,
        border: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <Toggle
            value={retrieval}
            onChange={(v) => update({ tool_retrieval: v })}
            label="Tool Retrieval"
            description="Semantic search selects the most relevant tools per turn."
          />
          {retrieval && (
            <div style={{ paddingLeft: 24, display: "flex", flexDirection: "column", gap: 10 }}>
              <Toggle
                value={discovery}
                onChange={(v) => update({ tool_discovery: v })}
                label="Auto-Discovery"
                description="Discover tools beyond this bot's configured set from the full pool."
              />
              <div style={{ maxWidth: 180 }}>
                <FormRow label="Similarity Threshold">
                  <TextInput
                    value={String(draft.tool_similarity_threshold ?? "")}
                    onChangeText={(v) => update({ tool_similarity_threshold: v ? parseFloat(v) : null })}
                    placeholder="0.45" type="number"
                  />
                </FormRow>
              </div>
            </div>
          )}
        </div>
        <div style={{ fontSize: 10, color: t.textDim, lineHeight: "14px", borderTop: `1px solid ${t.surfaceBorder}`, paddingTop: 8 }}>
          Skills and capabilities also use semantic search per turn. Memory scheme and channel overrides can add or remove tools at runtime.
        </div>
      </div>

      {/* Resolved capabilities summary */}
      <ResolvedSummary editorData={editorData} draft={draft} />

      {/* Mode explanation banner */}
      {discovery ? (
        <InfoBanner variant="info">
          <strong>All tools are discoverable.</strong> This bot can find and use any tool via semantic search.
          Pin tools that must be available every turn. Include tools to give them priority in search results.
        </InfoBanner>
      ) : retrieval ? (
        <InfoBanner variant="warning">
          <strong>Manual toolkit.</strong> Only enabled tools are available to this bot. The most relevant
          are selected each turn via semantic search. Pin tools to include them every turn regardless of relevance.
        </InfoBanner>
      ) : (
        <InfoBanner variant="warning">
          <strong>Static toolkit.</strong> All enabled tools are passed to the bot every turn.
          Consider enabling retrieval for large toolsets to reduce context usage.
        </InfoBanner>
      )}

      {/* Pinned Tools */}
      <PinnedToolsPicker editorData={editorData} draft={draft} update={update} discovery={discovery} />

      {/* Enrolled Tools (persistent working set) */}
      {discovery && draft.id && <EnrolledToolsPanel botId={draft.id} />}

      {/* MCP Servers */}
      <McpServersSection editorData={editorData} draft={draft} update={update} filter="" />

      {/* Client Tools */}
      <ClientToolsSection editorData={editorData} draft={draft} update={update} filter="" />

      {/* Full tool list */}
      <AdvancedSection title={discovery ? "Tool Pool" : "Available Tools"}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, paddingTop: 8 }}>
          <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4, lineHeight: "16px" }}>
            {discovery
              ? "All tools below are available via auto-discovery. Click a tool\u2019s status badge to cycle its state: discoverable (found at stricter threshold) \u2192 included (priority in search) \u2192 pinned (always in context). Auto-injected tools are managed by the system."
              : "Check tools to make them available to this bot. With retrieval on, the most relevant enabled tools are selected each turn. Pinned tools are always included regardless of relevance."}
          </div>
          <FullToolList editorData={editorData} draft={draft} update={update} discovery={discovery} />
        </div>
      </AdvancedSection>

      {/* Tool Result Summarization */}
      <AdvancedSection title="Tool Result Summarization">
        <div style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}>
          <div style={{ fontSize: 11, color: t.textDim }}>Summarizes large tool outputs to save context.</div>
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
                  { label: `Inherit (${globalToolSum.enabled ? "On" : "Off"})`, value: "" },
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
                  placeholder={`inherit (${globalToolSum.threshold})`} type="number"
                />
              </FormRow>
            </Col>
            <Col>
              <FormRow label="Summarizer model">
                <LlmModelDropdown
                  value={(draft.tool_result_config as any)?.model ?? ""}
                  onChange={(v) => update({ tool_result_config: { ...draft.tool_result_config, model: v || undefined } })}
                  placeholder={globalToolSum.model ? `inherit (${globalToolSum.model.split("/").pop()})` : "inherit"}
                />
              </FormRow>
            </Col>
            <Col>
              <FormRow label="Max summary tokens">
                <TextInput
                  value={String((draft.tool_result_config as any)?.max_tokens ?? "")}
                  onChangeText={(v) => update({ tool_result_config: { ...draft.tool_result_config, max_tokens: v ? parseInt(v) : undefined } })}
                  placeholder={`inherit (${globalToolSum.maxTokens})`} type="number"
                />
              </FormRow>
            </Col>
          </Row>
        </div>
      </AdvancedSection>

      {/* Iteration Limits — per-bot overrides for loop cap + run_script inner budget. */}
      <AdvancedSection title="Iteration Limits">
        <div style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}>
          <div style={{ fontSize: 11, color: t.textDim }}>
            Caps how many tool calls one turn (or one <code>run_script</code>)
            can make. Blank = inherit server default. Tighter caps reduce cost
            amplification from loops or prompt injection.
          </div>
          <Row gap={12}>
            <Col>
              <FormRow label="Max tool calls per turn">
                <TextInput
                  value={String(draft.max_iterations ?? "")}
                  onChangeText={(v) => update({ max_iterations: v ? parseInt(v) : null })}
                  placeholder="inherit (15)"
                  type="number"
                />
              </FormRow>
            </Col>
            <Col>
              <FormRow label="Max inner calls per run_script">
                <TextInput
                  value={String(draft.max_script_tool_calls ?? "")}
                  onChangeText={(v) => update({ max_script_tool_calls: v ? parseInt(v) : null })}
                  placeholder="inherit (50)"
                  type="number"
                />
              </FormRow>
            </Col>
          </Row>
        </div>
      </AdvancedSection>
    </div>
  );
}
