import { useState } from "react";
import { useWindowDimensions } from "react-native";
import { Search, X, Info, AlertTriangle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import {
  TextInput, SelectInput, Toggle, FormRow, Row, Col,
} from "@/src/components/shared/FormControls";
import type { BotConfig, BotEditorData, ToolGroup } from "@/src/types/api";
import { MOBILE_NAV_BREAKPOINT } from "./constants";
import { ToolSchemaModal } from "./ToolSchemaModal";

export function ToolsSection({
  editorData,
  draft,
  update,
}: {
  editorData: BotEditorData;
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
}) {
  const [toolFilter, setToolFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [schemaModalTool, setSchemaModalTool] = useState<string | null>(null);

  const localTools = draft.local_tools || [];
  const pinnedTools = draft.pinned_tools || [];
  const excludeTools: string[] = (draft.tool_result_config as any)?.exclude_tools || [];

  // Tools auto-injected at runtime (not in local_tools but still active)
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
    const next = localTools.includes(name)
      ? localTools.filter((t) => t !== name)
      : [...localTools, name];
    update({ local_tools: next });
  };

  const togglePin = (name: string) => {
    const next = pinnedTools.includes(name)
      ? pinnedTools.filter((t) => t !== name)
      : [...pinnedTools, name];
    update({ pinned_tools: next });
  };

  const toggleNoSum = (name: string) => {
    const next = excludeTools.includes(name)
      ? excludeTools.filter((t) => t !== name)
      : [...excludeTools, name];
    update({ tool_result_config: { ...draft.tool_result_config, exclude_tools: next } });
  };

  const toggleMcp = (name: string) => {
    const cur = draft.mcp_servers || [];
    update({ mcp_servers: cur.includes(name) ? cur.filter((t) => t !== name) : [...cur, name] });
  };

  const toggleClient = (name: string) => {
    const cur = draft.client_tools || [];
    update({ client_tools: cur.includes(name) ? cur.filter((t) => t !== name) : [...cur, name] });
  };

  // Toggle all tools in a pack
  const togglePack = (toolNames: string[]) => {
    const allEnabled = toolNames.every((n) => localTools.includes(n));
    if (allEnabled) {
      update({ local_tools: localTools.filter((t) => !toolNames.includes(t)) });
    } else {
      const toAdd = toolNames.filter((n) => !localTools.includes(n));
      update({ local_tools: [...localTools, ...toAdd] });
    }
  };

  // Toggle all tools in an entire integration group
  const toggleGroup = (group: ToolGroup) => {
    const allNames = group.packs.flatMap((p) => p.tools.map((t) => t.name));
    const allEnabled = allNames.every((n) => localTools.includes(n));
    if (allEnabled) {
      update({ local_tools: localTools.filter((t) => !allNames.includes(t)) });
    } else {
      const toAdd = allNames.filter((n) => !localTools.includes(n));
      update({ local_tools: [...localTools, ...toAdd] });
    }
  };

  const t = useThemeTokens();
  const { width: toolsWinWidth } = useWindowDimensions();
  const toolsMobile = toolsWinWidth < MOBILE_NAV_BREAKPOINT;
  const q = toolFilter.toLowerCase();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
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
        <span>✓ = enabled</span>
        {autoInjectedTools.size > 0 && <span style={{ color: t.purple }}>auto = injected by memory scheme</span>}
        {draft.tool_retrieval && <span style={{ color: "#eab308" }}>📌 = pinned (bypass RAG)</span>}
        <span style={{ color: "#f97316" }}>🔇 = skip summarization</span>
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
                const allNames = group.packs.flatMap((p) => p.tools.map((t) => t.name));
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
              const filtered = q ? pack.tools.filter((t) => t.name.toLowerCase().includes(q)) : pack.tools;
              if (filtered.length === 0) return null;

              const packNames = pack.tools.map((t) => t.name);
              const allEnabled = packNames.every((n) => localTools.includes(n));
              const someEnabled = packNames.some((n) => localTools.includes(n));
              const isCollapsed = !q && collapsed[packKey];

              return (
                <div key={pack.pack}>
                  {/* Pack header with toggle-all */}
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
                      }}>▶</span>
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
                      <span style={{ fontSize: 9, color: t.surfaceBorder }}>{packNames.filter((n) => localTools.includes(n)).length}/{packNames.length}</span>
                    </div>
                  )}

                  {/* Pack warning */}
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

                  {/* Tool rows */}
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
                              >📌</button>
                            )}
                            {enabled && (
                              <button
                                onClick={() => toggleNoSum(tool.name)}
                                title={noSum ? "Allow summarization" : "Skip summarization"}
                                style={{
                                  background: "none", border: "none", cursor: "pointer",
                                  fontSize: 10, padding: 0, opacity: noSum ? 1 : 0.25,
                                }}
                              >🔇</button>
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

      {/* MCP Servers */}
      {editorData.mcp_servers.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>MCP Servers</div>
          <div style={{ display: "grid", gridTemplateColumns: toolsMobile ? "1fr" : "1fr 1fr", gap: 2 }}>
            {editorData.mcp_servers.filter((s) => !q || s.toLowerCase().includes(q)).map((srv) => {
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
      )}

      {/* Client Tools */}
      {editorData.client_tools.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Client Tools</div>
          <div style={{ display: "grid", gridTemplateColumns: toolsMobile ? "1fr" : "1fr 1fr", gap: 2 }}>
            {editorData.client_tools.filter((ct) => !q || ct.toLowerCase().includes(q)).map((tool) => {
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
      )}

      {/* Tool Retrieval */}
      <div style={{ borderTop: `1px solid ${t.surfaceRaised}`, paddingTop: 12 }}>
        <Toggle
          value={draft.tool_retrieval ?? true}
          onChange={(v) => update({ tool_retrieval: v })}
          label="Tool Retrieval (RAG)"
          description="Only pass top-K relevant tools per turn. Pinned tools bypass filtering."
        />
        {draft.tool_retrieval && (
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

      {/* Tool Result Summarization */}
      <div style={{ borderTop: `1px solid ${t.surfaceRaised}`, paddingTop: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: t.text, marginBottom: 4 }}>Tool Result Summarization</div>
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 8 }}>Summarizes large tool outputs. Use 🔇 above to exclude tools.</div>
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

      {schemaModalTool && (
        <ToolSchemaModal
          toolName={schemaModalTool}
          onClose={() => setSchemaModalTool(null)}
        />
      )}
    </div>
  );
}
