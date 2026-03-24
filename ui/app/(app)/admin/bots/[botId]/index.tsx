import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { View, Text, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { ArrowLeft, Save, Search, X, Plus, Trash2, Package, ChevronDown } from "lucide-react";
import { useBotEditorData, useUpdateBot } from "@/src/api/hooks/useBots";
import { useBotElevation } from "@/src/api/hooks/useElevation";
import { useBotMemories, useDeleteMemory } from "@/src/api/hooks/useMemories";
import { useGoBack } from "@/src/hooks/useGoBack";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import {
  TextInput, SelectInput, Toggle, FormRow, Row, Col,
} from "@/src/components/shared/FormControls";
import type { BotConfig, BotEditorData } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Sections — Prompt & Persona adjacent, no compaction
// ---------------------------------------------------------------------------
const SECTIONS = [
  { key: "identity", label: "Identity" },
  { key: "prompt", label: "System Prompt" },
  { key: "persona", label: "Persona" },
  { key: "tools", label: "Tools" },
  { key: "skills", label: "Skills" },
  { key: "memory", label: "Memory" },
  { key: "knowledge", label: "Knowledge" },
  { key: "elevation", label: "Elevation" },
  { key: "attachments", label: "Attachments" },
  { key: "workspace", label: "Workspace" },
  { key: "delegation", label: "Delegation" },
  { key: "display", label: "Display" },
  { key: "advanced", label: "Advanced" },
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

// ---------------------------------------------------------------------------
// Large plain textarea (no @-tags) for system prompt & persona
// ---------------------------------------------------------------------------
function BigTextarea({
  value,
  onChange,
  placeholder,
  minRows = 24,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  minRows?: number;
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={minRows}
      style={{
        width: "100%", fontFamily: "monospace", fontSize: 13, lineHeight: "1.6",
        padding: "12px 16px", borderRadius: 8,
        border: "1px solid #333", background: "#0a0a0a", color: "#e5e7eb",
        resize: "vertical", outline: "none", transition: "border-color 0.15s",
        minHeight: minRows * 20,
      }}
      onFocus={(e) => { e.target.style.borderColor = "#3b82f6"; }}
      onBlur={(e) => { e.target.style.borderColor = "#333"; }}
    />
  );
}

// ---------------------------------------------------------------------------
// Dynamic list editor (for env vars, ports, mounts, commands, patterns)
// ---------------------------------------------------------------------------
function ListEditor({
  items,
  onUpdate,
  renderItem,
  renderAdd,
}: {
  items: any[];
  onUpdate: (items: any[]) => void;
  renderItem: (item: any, idx: number, remove: () => void) => React.ReactNode;
  renderAdd: (add: (item: any) => void) => React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {items.map((item, i) => (
        <div key={i}>{renderItem(item, i, () => onUpdate(items.filter((_, j) => j !== i)))}</div>
      ))}
      {renderAdd((item) => onUpdate([...items, item]))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section nav — sidebar on desktop, dropdown on mobile
// ---------------------------------------------------------------------------
const MOBILE_NAV_BREAKPOINT = 768;

function SectionNav({
  active,
  onSelect,
  filter,
  matchingSections,
  isMobile,
}: {
  active: SectionKey;
  onSelect: (k: SectionKey) => void;
  filter: string;
  matchingSections: Set<SectionKey>;
  isMobile: boolean;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);

  if (isMobile) {
    const activeLabel = SECTIONS.find((s) => s.key === active)?.label ?? active;
    return (
      <div style={{ position: "relative", borderBottom: "1px solid #1a1a1a" }}>
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          style={{
            display: "flex", alignItems: "center", gap: 6, width: "100%",
            padding: "8px 16px", background: "#0a0a0a", border: "none",
            color: "#e5e5e5", fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}
        >
          <span style={{ flex: 1, textAlign: "left" }}>{activeLabel}</span>
          <ChevronDown size={14} color="#555" style={{ transform: mobileOpen ? "rotate(180deg)" : "none", transition: "transform 0.15s" } as any} />
        </button>
        {mobileOpen && (
          <div style={{
            position: "absolute", top: "100%", left: 0, right: 0, zIndex: 20,
            background: "#0a0a0a", border: "1px solid #1a1a1a", borderTop: "none",
            maxHeight: 300, overflowY: "auto",
          }}>
            {SECTIONS.map((s) => {
              const dimmed = filter && !matchingSections.has(s.key);
              return (
                <button
                  key={s.key}
                  onClick={() => { onSelect(s.key); setMobileOpen(false); }}
                  style={{
                    display: "block", width: "100%", padding: "7px 16px", border: "none",
                    background: active === s.key ? "#1a1a1a" : "transparent",
                    color: dimmed ? "#333" : active === s.key ? "#3b82f6" : "#888",
                    fontSize: 12, fontWeight: active === s.key ? 600 : 400,
                    cursor: "pointer", textAlign: "left",
                  }}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{
      width: 150, flexShrink: 0, borderRight: "1px solid #1a1a1a",
      paddingTop: 8, overflowY: "auto",
    }}>
      {SECTIONS.map((s) => {
        const dimmed = filter && !matchingSections.has(s.key);
        return (
          <button
            key={s.key}
            onClick={() => onSelect(s.key)}
            style={{
              display: "block", width: "100%", padding: "7px 12px", border: "none",
              background: active === s.key ? "#1a1a1a" : "transparent",
              borderLeft: active === s.key ? "2px solid #3b82f6" : "2px solid transparent",
              color: dimmed ? "#333" : active === s.key ? "#e5e5e5" : "#888",
              fontSize: 12, fontWeight: active === s.key ? 600 : 400,
              cursor: "pointer", textAlign: "left", transition: "all 0.1s",
            }}
          >
            {s.label}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tools section — pack-level toggle + search + pin + no-summarize
// ---------------------------------------------------------------------------
function ToolsSection({
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

  const localTools = draft.local_tools || [];
  const pinnedTools = draft.pinned_tools || [];
  const excludeTools: string[] = (draft.tool_result_config as any)?.exclude_tools || [];

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

  const q = toolFilter.toLowerCase();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Search bar + counts */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6, flex: 1,
          background: "#111", border: "1px solid #333", borderRadius: 6, padding: "5px 10px",
        }}>
          <Search size={12} color="#555" />
          <input
            type="text" value={toolFilter}
            onChange={(e) => setToolFilter(e.target.value)}
            placeholder="Search tools..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#e5e5e5", fontSize: 12 }}
          />
          {toolFilter && (
            <button onClick={() => setToolFilter("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>
              <X size={10} color="#555" />
            </button>
          )}
        </div>
        <span style={{ fontSize: 11, color: "#555" }}>
          {localTools.length} selected
          {pinnedTools.length > 0 && <> · {pinnedTools.length} pinned</>}
        </span>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, fontSize: 10, color: "#555" }}>
        <span>✓ = enabled</span>
        {draft.tool_retrieval && <span style={{ color: "#eab308" }}>📌 = pinned (bypass RAG)</span>}
        <span style={{ color: "#f97316" }}>🔇 = skip summarization</span>
      </div>

      {/* Local tool groups */}
      {editorData.tool_groups.map((group) => {
        const groupKey = group.integration;
        return (
          <div key={groupKey} style={{ border: "1px solid #1a1a1a", borderRadius: 8, overflow: "hidden" }}>
            {/* Group header */}
            <div style={{
              padding: "6px 10px", background: "#0a0a0a",
              display: "flex", alignItems: "center", gap: 6,
            }}>
              {group.is_core ? (
                <span style={{ fontSize: 11, fontWeight: 600, color: "#888" }}>Core</span>
              ) : (
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 3,
                  background: "#92400e33", color: "#fbbf24", textTransform: "uppercase",
                }}>
                  {group.integration}
                </span>
              )}
              <span style={{ fontSize: 10, color: "#444", marginLeft: "auto" }}>{group.total}</span>
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
                        padding: "4px 10px", background: "#0a0a0a66", cursor: "pointer",
                        borderTop: "1px solid #111",
                      }}
                      onClick={() => setCollapsed((c) => ({ ...c, [packKey]: !c[packKey] }))}
                    >
                      <span style={{
                        fontSize: 8, color: "#555", transform: isCollapsed ? "rotate(0deg)" : "rotate(90deg)",
                        transition: "transform 0.15s", display: "inline-block",
                      }}>▶</span>
                      <span style={{ fontSize: 10, color: "#666", textTransform: "uppercase", letterSpacing: "0.05em", flex: 1 }}>
                        {pack.pack}
                      </span>
                      <button
                        onClick={(e) => { e.stopPropagation(); togglePack(packNames); }}
                        style={{
                          background: "none", border: "1px solid #333", borderRadius: 4,
                          padding: "1px 6px", fontSize: 9, cursor: "pointer",
                          color: allEnabled ? "#f87171" : "#86efac",
                        }}
                        title={allEnabled ? "Disable all" : "Enable all"}
                      >
                        {allEnabled ? "none" : someEnabled ? "all" : "all"}
                      </button>
                      <span style={{ fontSize: 9, color: "#444" }}>{packNames.filter((n) => localTools.includes(n)).length}/{packNames.length}</span>
                    </div>
                  )}

                  {/* Tool rows */}
                  {!isCollapsed && (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, padding: 4 }}>
                      {filtered.map((tool) => {
                        const enabled = localTools.includes(tool.name);
                        const pinned = pinnedTools.includes(tool.name);
                        const noSum = excludeTools.includes(tool.name);
                        return (
                          <div
                            key={tool.name}
                            style={{
                              display: "flex", alignItems: "center", gap: 4,
                              padding: "3px 6px", borderRadius: 3, fontSize: 11,
                              background: enabled ? "rgba(59,130,246,0.08)" : "transparent",
                              border: `1px solid ${enabled ? "#3b82f622" : "transparent"}`,
                            }}
                          >
                            <input
                              type="checkbox" checked={enabled}
                              onChange={() => toggleTool(tool.name)}
                              style={{ accentColor: "#3b82f6" }}
                            />
                            <span
                              style={{
                                fontFamily: "monospace", color: enabled ? "#93c5fd" : "#555",
                                flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                              }}
                              title={tool.name}
                            >
                              {tool.name}
                            </span>
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
          <div style={{ fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>MCP Servers</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
            {editorData.mcp_servers.filter((s) => !q || s.toLowerCase().includes(q)).map((srv) => {
              const on = (draft.mcp_servers || []).includes(srv);
              return (
                <label key={srv} style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "4px 8px",
                  borderRadius: 4, cursor: "pointer", fontSize: 11,
                  background: on ? "rgba(59,130,246,0.08)" : "transparent",
                  border: `1px solid ${on ? "#3b82f622" : "transparent"}`,
                }}>
                  <input type="checkbox" checked={on} onChange={() => toggleMcp(srv)} style={{ accentColor: "#3b82f6" }} />
                  <span style={{ fontFamily: "monospace", color: on ? "#93c5fd" : "#555" }}>{srv}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {/* Client Tools */}
      {editorData.client_tools.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Client Tools</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
            {editorData.client_tools.filter((t) => !q || t.toLowerCase().includes(q)).map((tool) => {
              const on = (draft.client_tools || []).includes(tool);
              return (
                <label key={tool} style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "4px 8px",
                  borderRadius: 4, cursor: "pointer", fontSize: 11,
                  background: on ? "rgba(59,130,246,0.08)" : "transparent",
                  border: `1px solid ${on ? "#3b82f622" : "transparent"}`,
                }}>
                  <input type="checkbox" checked={on} onChange={() => toggleClient(tool)} style={{ accentColor: "#3b82f6" }} />
                  <span style={{ fontFamily: "monospace", color: on ? "#93c5fd" : "#555" }}>{tool}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {/* Tool Retrieval */}
      <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
        <Toggle
          value={draft.tool_retrieval ?? true}
          onChange={(v) => update({ tool_retrieval: v })}
          label="Tool Retrieval (RAG)"
          description="Only pass top-K relevant tools per turn. Pinned tools bypass filtering."
        />
        {draft.tool_retrieval && (
          <div style={{ marginTop: 8, maxWidth: 200 }}>
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
      <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "#e5e5e5", marginBottom: 4 }}>Tool Result Summarization</div>
        <div style={{ fontSize: 11, color: "#555", marginBottom: 8 }}>Summarizes large tool outputs. Use 🔇 above to exclude tools.</div>
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
              <TextInput
                value={(draft.tool_result_config as any)?.model ?? ""}
                onChangeText={(v) => update({ tool_result_config: { ...draft.tool_result_config, model: v || undefined } })}
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

      {/* Context Compression */}
      <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "#e5e5e5", marginBottom: 4 }}>Context Compression</div>
        <div style={{ fontSize: 11, color: "#555", marginBottom: 8 }}>Summarizes conversation history via a cheap model before each LLM call.</div>
        <Row gap={12}>
          <Col>
            <SelectInput
              value={draft.compression_config?.enabled === true ? "true" : draft.compression_config?.enabled === false ? "false" : ""}
              onChange={(v) => {
                const cc = { ...draft.compression_config };
                if (v === "true") cc.enabled = true;
                else if (v === "false") cc.enabled = false;
                else delete cc.enabled;
                update({ compression_config: cc });
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
                value={String((draft.compression_config as any)?.threshold ?? "")}
                onChangeText={(v) => update({ compression_config: { ...draft.compression_config, threshold: v ? parseInt(v) : undefined } })}
                placeholder="global (20000)" type="number"
              />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Compression model">
              <TextInput
                value={(draft.compression_config as any)?.model ?? ""}
                onChangeText={(v) => update({ compression_config: { ...draft.compression_config, model: v || undefined } })}
                placeholder="global model"
              />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Keep turns (verbatim)">
              <TextInput
                value={String((draft.compression_config as any)?.keep_turns ?? "")}
                onChangeText={(v) => update({ compression_config: { ...draft.compression_config, keep_turns: v ? parseInt(v) : undefined } })}
                placeholder="global (2)" type="number"
              />
            </FormRow>
          </Col>
        </Row>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bot memories section (shown inside Memory tab)
// ---------------------------------------------------------------------------
function BotMemoriesSection({ botId }: { botId: string | undefined }) {
  const { data: memories, isLoading } = useBotMemories(botId);
  const deleteMut = useDeleteMemory();

  if (!botId) return null;

  return (
    <div style={{ marginTop: 8, borderTop: "1px solid #222", paddingTop: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#e5e5e5", marginBottom: 4 }}>
        Stored Memories
      </div>
      <div style={{ fontSize: 10, color: "#555", marginBottom: 12 }}>
        Facts this bot has memorized. Delete individual memories that are no longer relevant.
      </div>

      {isLoading && (
        <div style={{ padding: 12, color: "#555", fontSize: 12 }}>Loading...</div>
      )}

      {!isLoading && (!memories || memories.length === 0) && (
        <div style={{ padding: 12, color: "#444", fontSize: 12, fontStyle: "italic" }}>
          No memories stored yet.
        </div>
      )}

      {memories && memories.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {memories.map((m) => (
            <div key={m.id} style={{
              display: "flex", alignItems: "flex-start", gap: 8,
              padding: "8px 10px", background: "#111", borderRadius: 6,
              border: "1px solid #1a1a1a",
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 12, color: "#ccc", lineHeight: 1.5,
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                }}>
                  {m.content}
                </div>
                <div style={{ fontSize: 10, color: "#555", marginTop: 4 }}>
                  {new Date(m.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  {m.client_id && <span> &middot; {m.client_id.slice(0, 12)}</span>}
                </div>
              </div>
              <button
                onClick={() => {
                  if (confirm("Delete this memory?")) deleteMut.mutate(m.id);
                }}
                disabled={deleteMut.isPending}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  padding: 4, flexShrink: 0, color: "#666",
                }}
                title="Delete memory"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skills section
// ---------------------------------------------------------------------------
function SkillsSection({
  editorData, draft, update,
}: { editorData: BotEditorData; draft: BotConfig; update: (p: Partial<BotConfig>) => void }) {
  const [filter, setFilter] = useState("");
  const skills = draft.skills || [];
  const isSelected = (id: string) => skills.some((s) => s.id === id);
  const getEntry = (id: string) => skills.find((s) => s.id === id);

  const toggle = (id: string) => {
    update({
      skills: isSelected(id)
        ? skills.filter((s) => s.id !== id)
        : [...skills, { id, mode: "on_demand" }],
    });
  };

  const setMode = (id: string, mode: string) => {
    update({
      skills: skills.map((s) =>
        s.id === id ? { ...s, mode, similarity_threshold: mode === "rag" ? s.similarity_threshold : null } : s
      ),
    });
  };

  const filtered = filter
    ? editorData.all_skills.filter((s) =>
        s.id.toLowerCase().includes(filter.toLowerCase()) ||
        s.name.toLowerCase().includes(filter.toLowerCase()) ||
        (s.description || "").toLowerCase().includes(filter.toLowerCase()))
    : editorData.all_skills;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, color: "#555" }}>
        <strong style={{ color: "#888" }}>on_demand</strong>: index injected, agent calls get_skill.{" "}
        <strong style={{ color: "#888" }}>pinned</strong>: full content every turn.{" "}
        <strong style={{ color: "#888" }}>rag</strong>: semantic similarity per turn.
      </div>
      {editorData.all_skills.length > 6 && (
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "#111", border: "1px solid #333", borderRadius: 6, padding: "4px 8px",
        }}>
          <Search size={12} color="#555" />
          <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter skills..." style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#e5e5e5", fontSize: 12 }} />
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        {filtered.map((skill) => {
          const sel = isSelected(skill.id);
          const entry = getEntry(skill.id);
          return (
            <div key={skill.id} style={{
              padding: 8, borderRadius: 6,
              background: sel ? "rgba(59,130,246,0.06)" : "#0a0a0a",
              border: `1px solid ${sel ? "#3b82f633" : "#1a1a1a"}`,
            }}>
              <label style={{ display: "flex", alignItems: "flex-start", gap: 6, cursor: "pointer" }}>
                <input type="checkbox" checked={sel} onChange={() => toggle(skill.id)} style={{ accentColor: "#3b82f6", marginTop: 2 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 500, color: sel ? "#93c5fd" : "#999" }}>{skill.name}</span>
                    <span style={{ fontSize: 10, color: "#444", fontFamily: "monospace" }}>{skill.id}</span>
                  </div>
                  {skill.description && (
                    <div style={{ fontSize: 10, color: "#555", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {skill.description}
                    </div>
                  )}
                </div>
              </label>
              {sel && entry && (
                <div style={{ marginTop: 6, marginLeft: 22 }}>
                  <select value={entry.mode || "on_demand"} onChange={(e) => setMode(skill.id, e.target.value)}
                    style={{ background: "#111", border: "1px solid #333", borderRadius: 4, padding: "2px 8px", fontSize: 11, color: "#e5e5e5" }}>
                    <option value="on_demand">on_demand</option>
                    <option value="pinned">pinned</option>
                    <option value="rag">rag</option>
                  </select>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workspace section — full Docker/Host/Indexing config
// ---------------------------------------------------------------------------
function WorkspaceSection({
  editorData, draft, update,
}: { editorData: BotEditorData; draft: BotConfig; update: (p: Partial<BotConfig>) => void }) {
  const ws = draft.workspace || { enabled: false };
  const docker = ws.docker || {};
  const host = ws.host || {};
  const indexing = ws.indexing || {};

  const setWs = (patch: Record<string, any>) => update({ workspace: { ...ws, ...patch } });
  const setDocker = (patch: Record<string, any>) => setWs({ docker: { ...docker, ...patch } });
  const setHost = (patch: Record<string, any>) => setWs({ host: { ...host, ...patch } });
  const setIndexing = (patch: Record<string, any>) => setWs({ indexing: { ...indexing, ...patch } });

  // Env var add state
  const [newEnvKey, setNewEnvKey] = useState("");
  const [newEnvVal, setNewEnvVal] = useState("");
  const [newHostPort, setNewHostPort] = useState("");
  const [newContainerPort, setNewContainerPort] = useState("");
  const [newMountHost, setNewMountHost] = useState("");
  const [newMountContainer, setNewMountContainer] = useState("");
  const [newMountMode, setNewMountMode] = useState("rw");
  const [newCmd, setNewCmd] = useState("");
  const [newCmdSubs, setNewCmdSubs] = useState("");
  const [newBlocked, setNewBlocked] = useState("");
  const [newEnvPass, setNewEnvPass] = useState("");
  const [newPattern, setNewPattern] = useState("");

  const envEntries = Object.entries(docker.env || {});
  const ports: any[] = docker.ports || [];
  const mounts: any[] = docker.mounts || [];
  const commands: any[] = host.commands || [];
  const blocked: string[] = host.blocked_patterns || [];
  const envPass: string[] = host.env_passthrough || [];
  const patterns: string[] = indexing.patterns || [];

  const rowStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 6, padding: "3px 6px",
    background: "#111", borderRadius: 4, fontSize: 11,
  };
  const removeBtn = (onClick: () => void) => (
    <button onClick={onClick} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, color: "#f87171", fontSize: 12 }}>×</button>
  );
  const addBtn = (label: string, onClick: () => void) => (
    <button onClick={onClick} style={{
      padding: "3px 10px", fontSize: 11, background: "#1a1a1a", border: "1px solid #333",
      borderRadius: 4, color: "#888", cursor: "pointer",
    }}>{label}</button>
  );
  const miniInput = (value: string, onChange: (v: string) => void, placeholder: string, style?: React.CSSProperties) => (
    <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
      style={{ background: "#0a0a0a", border: "1px solid #333", borderRadius: 4, padding: "3px 6px", fontSize: 11, color: "#e5e5e5", outline: "none", ...style }}
      onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); }}
    />
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Toggle value={ws.enabled ?? false} onChange={(v) => setWs({ enabled: v })} label="Enable Workspace"
        description="Auto-injects exec_command, search_workspace, delegate_to_exec tools." />

      {ws.enabled && (
        <>
          <Row gap={12}>
            <Col>
              <FormRow label="Type">
                <SelectInput value={ws.type || "docker"} onChange={(v) => setWs({ type: v })}
                  options={[{ label: "Docker Container", value: "docker" }, { label: "Host Execution", value: "host" }]} />
              </FormRow>
            </Col>
            <Col>
              <FormRow label="Timeout (seconds)">
                <TextInput value={String(ws.timeout ?? "")} onChangeText={(v) => setWs({ timeout: v ? parseInt(v) : null })} placeholder="30" type="number" />
              </FormRow>
            </Col>
            <Col>
              <FormRow label="Max Output Bytes">
                <TextInput value={String(ws.max_output_bytes ?? "")} onChangeText={(v) => setWs({ max_output_bytes: v ? parseInt(v) : null })} placeholder="65536" type="number" />
              </FormRow>
            </Col>
          </Row>

          {/* Docker panel */}
          {(ws.type || "docker") === "docker" && (
            <div style={{ borderLeft: "2px solid #1e3a5f", paddingLeft: 12, display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#888", textTransform: "uppercase", letterSpacing: "0.05em" }}>Docker Settings</div>
              <Row gap={12}>
                <Col><FormRow label="Image"><TextInput value={docker.image || ""} onChangeText={(v) => setDocker({ image: v })} placeholder="python:3.12-slim" /></FormRow></Col>
                <Col><FormRow label="Network"><SelectInput value={docker.network || "none"} onChange={(v) => setDocker({ network: v })}
                  options={[{ label: "none", value: "none" }, { label: "bridge", value: "bridge" }, { label: "host", value: "host" }]} /></FormRow></Col>
              </Row>
              <Row gap={12}>
                <Col><FormRow label="Run as User"><TextInput value={docker.user || ""} onChangeText={(v) => setDocker({ user: v })} placeholder="image default" /></FormRow></Col>
                <Col><FormRow label="CPUs"><TextInput value={String(docker.cpus ?? "")} onChangeText={(v) => setDocker({ cpus: v ? parseFloat(v) : null })} placeholder="unlimited" type="number" /></FormRow></Col>
                <Col><FormRow label="Memory"><TextInput value={docker.memory || ""} onChangeText={(v) => setDocker({ memory: v })} placeholder="e.g. 512m, 2g" /></FormRow></Col>
              </Row>
              <Toggle value={docker.read_only_root ?? false} onChange={(v) => setDocker({ read_only_root: v })} label="Read-only root filesystem" />

              {/* Env vars */}
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: "#666", textTransform: "uppercase", marginBottom: 4 }}>Environment Variables</div>
                {envEntries.map(([k, v]) => (
                  <div key={k} style={rowStyle}>
                    <span style={{ fontFamily: "monospace", color: "#93c5fd", width: 120 }}>{k}</span>
                    <span style={{ color: "#555" }}>=</span>
                    <span style={{ fontFamily: "monospace", color: "#888", flex: 1 }}>{v as string}</span>
                    {removeBtn(() => { const e = { ...docker.env }; delete e[k]; setDocker({ env: e }); })}
                  </div>
                ))}
                <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                  {miniInput(newEnvKey, setNewEnvKey, "KEY", { width: 120 })}
                  <span style={{ color: "#555", fontSize: 11 }}>=</span>
                  {miniInput(newEnvVal, setNewEnvVal, "value", { flex: 1 })}
                  {addBtn("Add", () => {
                    if (newEnvKey.trim()) { setDocker({ env: { ...docker.env, [newEnvKey.trim()]: newEnvVal } }); setNewEnvKey(""); setNewEnvVal(""); }
                  })}
                </div>
              </div>

              {/* Ports */}
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: "#666", textTransform: "uppercase", marginBottom: 4 }}>Port Mappings</div>
                {ports.map((p: any, i: number) => (
                  <div key={i} style={rowStyle}>
                    <span style={{ fontFamily: "monospace", color: "#93c5fd" }}>{p.host_port ? `${p.host_port}:${p.container_port}` : p.container_port}</span>
                    {removeBtn(() => setDocker({ ports: ports.filter((_, j: number) => j !== i) }))}
                  </div>
                ))}
                <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                  {miniInput(newHostPort, setNewHostPort, "host (opt)", { width: 90 })}
                  <span style={{ color: "#555", fontSize: 11 }}>:</span>
                  {miniInput(newContainerPort, setNewContainerPort, "container", { width: 90 })}
                  {addBtn("Add", () => {
                    if (newContainerPort.trim()) { setDocker({ ports: [...ports, { host_port: newHostPort.trim(), container_port: newContainerPort.trim() }] }); setNewHostPort(""); setNewContainerPort(""); }
                  })}
                </div>
              </div>

              {/* Mounts */}
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: "#666", textTransform: "uppercase", marginBottom: 4 }}>Extra Volume Mounts</div>
                <div style={{ fontSize: 10, color: "#555", marginBottom: 4 }}>Workspace root always mounted at /workspace.</div>
                {mounts.map((m: any, i: number) => (
                  <div key={i} style={rowStyle}>
                    <span style={{ fontFamily: "monospace", color: "#93c5fd", flex: 1 }}>{m.host_path} : {m.container_path} : {m.mode || "rw"}</span>
                    {removeBtn(() => setDocker({ mounts: mounts.filter((_, j: number) => j !== i) }))}
                  </div>
                ))}
                <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                  {miniInput(newMountHost, setNewMountHost, "host path", { flex: 1 })}
                  <span style={{ color: "#555", fontSize: 11 }}>:</span>
                  {miniInput(newMountContainer, setNewMountContainer, "container path", { flex: 1 })}
                  <select value={newMountMode} onChange={(e) => setNewMountMode(e.target.value)}
                    style={{ background: "#0a0a0a", border: "1px solid #333", borderRadius: 4, padding: "3px 4px", fontSize: 11, color: "#e5e5e5", width: 50 }}>
                    <option value="rw">rw</option>
                    <option value="ro">ro</option>
                  </select>
                  {addBtn("Add", () => {
                    if (newMountHost.trim() && newMountContainer.trim()) {
                      setDocker({ mounts: [...mounts, { host_path: newMountHost.trim(), container_path: newMountContainer.trim(), mode: newMountMode }] });
                      setNewMountHost(""); setNewMountContainer(""); setNewMountMode("rw");
                    }
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Host panel */}
          {ws.type === "host" && (
            <div style={{ borderLeft: "2px solid #166534", paddingLeft: 12, display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#888", textTransform: "uppercase", letterSpacing: "0.05em" }}>Host Settings</div>
              <FormRow label="Custom Root"><TextInput value={host.root || ""} onChangeText={(v) => setHost({ root: v })} placeholder="auto: ~/.agent-workspaces/<bot-id>/" /></FormRow>

              {/* Commands */}
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: "#666", textTransform: "uppercase", marginBottom: 4 }}>Allowed Commands</div>
                <div style={{ fontSize: 10, color: "#555", marginBottom: 4 }}>Use * to allow any. Leave subcommands empty for all.</div>
                {commands.map((cmd: any, i: number) => (
                  <div key={i} style={rowStyle}>
                    <span style={{ fontFamily: "monospace", color: "#818cf8", width: 80 }}>{cmd.name}</span>
                    <span style={{ color: "#888", flex: 1 }}>{cmd.subcommands?.length ? cmd.subcommands.join(", ") : "(all)"}</span>
                    {removeBtn(() => setHost({ commands: commands.filter((_: any, j: number) => j !== i) }))}
                  </div>
                ))}
                <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                  {miniInput(newCmd, setNewCmd, "binary", { width: 100 })}
                  {miniInput(newCmdSubs, setNewCmdSubs, "subcommands (comma-sep)", { flex: 1 })}
                  {addBtn("Add", () => {
                    if (newCmd.trim()) {
                      const subs = newCmdSubs.trim() ? newCmdSubs.split(",").map((s) => s.trim()).filter(Boolean) : [];
                      setHost({ commands: [...commands, { name: newCmd.trim(), subcommands: subs }] });
                      setNewCmd(""); setNewCmdSubs("");
                    }
                  })}
                </div>
              </div>

              {/* Blocked patterns */}
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: "#666", textTransform: "uppercase", marginBottom: 4 }}>Blocked Patterns (regex)</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {blocked.map((pat, i) => (
                    <span key={i} style={{ display: "flex", alignItems: "center", gap: 4, background: "#111", borderRadius: 4, padding: "2px 8px", fontSize: 11, fontFamily: "monospace", color: "#fbbf24" }}>
                      {pat} {removeBtn(() => setHost({ blocked_patterns: blocked.filter((_, j) => j !== i) }))}
                    </span>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                  {miniInput(newBlocked, setNewBlocked, "regex pattern", { flex: 1 })}
                  {addBtn("Add", () => { if (newBlocked.trim()) { setHost({ blocked_patterns: [...blocked, newBlocked.trim()] }); setNewBlocked(""); } })}
                </div>
              </div>

              {/* Env passthrough */}
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: "#666", textTransform: "uppercase", marginBottom: 4 }}>Env Passthrough</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {envPass.map((v, i) => (
                    <span key={i} style={{ display: "flex", alignItems: "center", gap: 4, background: "#111", borderRadius: 4, padding: "2px 8px", fontSize: 11, fontFamily: "monospace", color: "#93c5fd" }}>
                      {v} {removeBtn(() => setHost({ env_passthrough: envPass.filter((_, j) => j !== i) }))}
                    </span>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                  {miniInput(newEnvPass, setNewEnvPass, "ENV_VAR_NAME", { width: 160 })}
                  {addBtn("Add", () => { if (newEnvPass.trim()) { setHost({ env_passthrough: [...envPass, newEnvPass.trim()] }); setNewEnvPass(""); } })}
                </div>
              </div>
            </div>
          )}

          {/* Indexing panel */}
          <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#888", textTransform: "uppercase", letterSpacing: "0.05em" }}>Workspace Indexing</div>
              <Toggle value={indexing.enabled !== false} onChange={(v) => setIndexing({ enabled: v })} label="Enable" />
              {indexing.enabled !== false && (
                <Toggle value={indexing.watch !== false} onChange={(v) => setIndexing({ watch: v })} label="Watch" />
              )}
            </div>
            {indexing.enabled !== false && (
              <>
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: "#666", textTransform: "uppercase", marginBottom: 4 }}>File Patterns</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {patterns.map((pat, i) => (
                      <span key={i} style={{ display: "flex", alignItems: "center", gap: 4, background: "#111", borderRadius: 4, padding: "2px 8px", fontSize: 11, fontFamily: "monospace", color: "#93c5fd" }}>
                        {pat} {removeBtn(() => setIndexing({ patterns: patterns.filter((_, j) => j !== i) }))}
                      </span>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                    {miniInput(newPattern, setNewPattern, "**/*.py", { width: 160 })}
                    {addBtn("Add", () => { if (newPattern.trim()) { setIndexing({ patterns: [...patterns, newPattern.trim()] }); setNewPattern(""); } })}
                  </div>
                </div>
                <Row gap={12}>
                  <Col><FormRow label="Similarity Threshold"><TextInput value={String(indexing.similarity_threshold ?? "")} onChangeText={(v) => setIndexing({ similarity_threshold: v ? parseFloat(v) : null })} placeholder="server default" type="number" /></FormRow></Col>
                  <Col><FormRow label="Top-K Results"><TextInput value={String(indexing.top_k ?? "")} onChangeText={(v) => setIndexing({ top_k: v ? parseInt(v) : null })} placeholder="8" type="number" /></FormRow></Col>
                  <Col><FormRow label="Cooldown (sec)"><TextInput value={String(indexing.cooldown_seconds ?? "")} onChangeText={(v) => setIndexing({ cooldown_seconds: v ? parseInt(v) : null })} placeholder="300" type="number" /></FormRow></Col>
                </Row>
              </>
            )}
          </div>
        </>
      )}

      {/* Sandbox profiles */}
      {editorData.all_sandbox_profiles.length > 0 && (
        <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "#e5e5e5", marginBottom: 4 }}>Docker Sandbox Profiles</div>
          <div style={{ fontSize: 11, color: "#555", marginBottom: 8 }}>Restrict which profiles this bot can use.</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
            {editorData.all_sandbox_profiles.map((p) => {
              const on = (draft.docker_sandbox_profiles || []).includes(p.name);
              return (
                <label key={p.name} style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "4px 8px",
                  borderRadius: 4, cursor: "pointer", fontSize: 11,
                  background: on ? "rgba(59,130,246,0.08)" : "transparent",
                }}>
                  <input type="checkbox" checked={on} style={{ accentColor: "#3b82f6" }}
                    onChange={() => {
                      const cur = draft.docker_sandbox_profiles || [];
                      update({ docker_sandbox_profiles: on ? cur.filter((n) => n !== p.name) : [...cur, p.name] });
                    }} />
                  <span style={{ fontFamily: "monospace", color: on ? "#93c5fd" : "#555" }}>{p.name}</span>
                  {p.description && <span style={{ color: "#444", marginLeft: 4 }}>{p.description}</span>}
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Bot Editor
// ---------------------------------------------------------------------------
export default function BotEditorScreen() {
  const { botId } = useLocalSearchParams<{ botId: string }>();
  const goBack = useGoBack("/admin/bots");
  const { data: editorData, isLoading } = useBotEditorData(botId);
  const { data: elevationData } = useBotElevation(botId);
  const updateMutation = useUpdateBot(botId);
  const scrollRef = useRef<ScrollView>(null);

  const { width: windowWidth } = useWindowDimensions();
  const isMobile = windowWidth < MOBILE_NAV_BREAKPOINT;

  const [activeSection, setActiveSection] = useState<SectionKey>("identity");
  const [filter, setFilter] = useState("");
  const [draft, setDraft] = useState<BotConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (editorData?.bot && !draft) setDraft({ ...editorData.bot });
  }, [editorData]);

  const update = useCallback((patch: Partial<BotConfig>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
    setDirty(true);
    setSaved(false);
  }, []);

  const handleSave = useCallback(async () => {
    if (!draft || !botId) return;
    const payload: any = { ...draft };
    if (draft.memory) { payload.memory_config = draft.memory; delete payload.memory; }
    if (draft.knowledge) { payload.knowledge_config = draft.knowledge; delete payload.knowledge; }
    delete payload.id; delete payload.created_at; delete payload.updated_at;
    for (const key of Object.keys(payload)) { if (payload[key] === undefined) delete payload[key]; }
    try {
      await updateMutation.mutateAsync(payload);
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (_) { /* handled by mutation state */ }
  }, [draft, botId, updateMutation]);

  const matchingSections = useMemo(() => {
    if (!filter) return new Set<SectionKey>(SECTIONS.map((s) => s.key));
    const q = filter.toLowerCase();
    const match = new Set<SectionKey>();
    const keywords: Record<SectionKey, string[]> = {
      identity: ["id", "name", "model", "provider"],
      prompt: ["system", "prompt"],
      persona: ["persona", "personality", "tone"],
      tools: ["tool", "mcp", "client", "pin", "rag", "retrieval", "summarization", "compression"],
      skills: ["skill"],
      memory: ["memory", "cross", "channel"],
      knowledge: ["knowledge"],
      elevation: ["elevation", "elevate", "threshold"],
      attachments: ["attachment", "summarization", "vision"],
      workspace: ["workspace", "docker", "host", "exec", "sandbox", "index", "command", "port", "mount"],
      delegation: ["delegat", "harness", "bot"],
      display: ["display", "avatar", "icon", "slack", "emoji"],
      advanced: ["audio", "compaction", "interval", "keep_turns"],
    };
    for (const [key, kws] of Object.entries(keywords)) {
      if (kws.some((kw) => kw.includes(q) || q.includes(kw))) match.add(key as SectionKey);
    }
    for (const s of SECTIONS) { if (s.label.toLowerCase().includes(q)) match.add(s.key); }
    return match;
  }, [filter]);

  if (isLoading || !editorData || !draft) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "10px 16px", borderBottom: "1px solid #1a1a1a",
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 4 }}>
          <ArrowLeft size={16} color="#888" />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#e5e5e5" }}>{draft.name}</div>
          <div style={{ fontSize: 10, color: "#555", fontFamily: "monospace" }}>{draft.id}</div>
        </div>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "#111", border: "1px solid #333", borderRadius: 6, padding: "4px 10px", width: 180,
        }}>
          <Search size={12} color="#555" />
          <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find setting..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#e5e5e5", fontSize: 12 }} />
          {filter && (
            <button onClick={() => setFilter("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>
              <X size={10} color="#555" />
            </button>
          )}
        </div>
        <button
          onClick={handleSave}
          disabled={!dirty || updateMutation.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 16px", borderRadius: 6, border: "none",
            background: dirty ? "#3b82f6" : "#1a1a1a",
            color: dirty ? "#fff" : "#555",
            fontSize: 12, fontWeight: 600, cursor: dirty ? "pointer" : "default",
            opacity: updateMutation.isPending ? 0.6 : 1,
          }}
        >
          <Save size={13} />
          {updateMutation.isPending ? "Saving..." : saved ? "Saved!" : "Save"}
        </button>
      </div>

      {updateMutation.isError && (
        <div style={{ padding: "8px 16px", background: "#7f1d1d33", color: "#fca5a5", fontSize: 12 }}>
          {(updateMutation.error as Error)?.message || "Failed to save"}
        </div>
      )}

      {/* Section nav: dropdown on mobile, sidebar on desktop */}
      {isMobile && (
        <SectionNav active={activeSection} onSelect={setActiveSection} filter={filter} matchingSections={matchingSections} isMobile />
      )}

      {/* Body */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {!isMobile && (
          <SectionNav active={activeSection} onSelect={setActiveSection} filter={filter} matchingSections={matchingSections} isMobile={false} />
        )}

        <ScrollView ref={scrollRef} className="flex-1" contentContainerStyle={{ padding: 20, maxWidth: 800 }}>

          {activeSection === "identity" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Identity</div>
              <Row>
                <Col>
                  <FormRow label="Bot ID">
                    <TextInput value={draft.id} onChangeText={() => {}} style={{ opacity: 0.5, cursor: "not-allowed" }} />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Display Name">
                    <TextInput value={draft.name} onChangeText={(v) => update({ name: v })} />
                  </FormRow>
                </Col>
              </Row>
              <FormRow label="Model">
                <LlmModelDropdown value={draft.model} onChange={(v) => update({ model: v })} />
              </FormRow>
            </div>
          )}

          {activeSection === "prompt" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>System Prompt</div>
              <BigTextarea
                value={draft.system_prompt || ""}
                onChange={(v) => update({ system_prompt: v })}
                placeholder="Enter system prompt..."
                minRows={28}
              />
            </div>
          )}

          {activeSection === "persona" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Persona</div>
              <div style={{ fontSize: 11, color: "#555" }}>Injects a persistent personality/tone as a separate system message (distinct from the system prompt).</div>
              <Toggle value={draft.persona ?? false} onChange={(v) => update({ persona: v })} label="Enable Persona" />
              {draft.persona && (
                <BigTextarea
                  value={draft.persona_content || ""}
                  onChange={(v) => update({ persona_content: v })}
                  placeholder="Describe the bot's personality, tone, and style..."
                  minRows={20}
                />
              )}
            </div>
          )}

          {activeSection === "tools" && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 12 }}>Tools</div>
              <ToolsSection editorData={editorData} draft={draft} update={update} />
            </div>
          )}

          {activeSection === "skills" && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 12 }}>Skills</div>
              <SkillsSection editorData={editorData} draft={draft} update={update} />
            </div>
          )}

          {activeSection === "memory" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Memory</div>
              <div style={{ fontSize: 11, color: "#555" }}>Short facts stored between turns. Relevant memories retrieved by semantic similarity.</div>
              <Toggle value={draft.memory?.enabled ?? false} onChange={(v) => update({ memory: { ...draft.memory, enabled: v } })} label="Enable Memory" />
              <Toggle value={draft.memory?.cross_channel ?? false} onChange={(v) => update({ memory: { ...draft.memory, cross_channel: v } })}
                label="Cross-Channel" description="Share memories across all channels for this client+bot" />
              <Row>
                <Col>
                  <FormRow label="Similarity Threshold">
                    <TextInput value={String(draft.memory?.similarity_threshold ?? 0.45)}
                      onChangeText={(v) => update({ memory: { ...draft.memory, similarity_threshold: v ? parseFloat(v) : 0.45 } })} type="number" />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Max Inject Chars">
                    <TextInput value={String(draft.memory_max_inject_chars ?? "")}
                      onChangeText={(v) => update({ memory_max_inject_chars: v ? parseInt(v) : null })} placeholder="3000" type="number" />
                  </FormRow>
                </Col>
              </Row>
              <FormRow label="Memory Prompt" description="Guidance on what the bot should remember">
                <LlmPrompt value={draft.memory?.prompt || ""}
                  onChange={(v) => update({ memory: { ...draft.memory, prompt: v || undefined } })}
                  rows={4} placeholder="Specific guidance on what's worth remembering..." />
              </FormRow>

              {/* Stored memories list */}
              <BotMemoriesSection botId={botId} />
            </div>
          )}

          {activeSection === "knowledge" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Knowledge</div>
              <div style={{ fontSize: 11, color: "#555" }}>Longer-form documents written by the bot. Retrieved by semantic similarity per turn.</div>
              <Toggle value={draft.knowledge?.enabled ?? false} onChange={(v) => update({ knowledge: { ...draft.knowledge, enabled: v } })} label="Enable Knowledge" />
              <div style={{ maxWidth: 300 }}>
                <FormRow label="Max Inject Chars">
                  <TextInput value={String(draft.knowledge_max_inject_chars ?? "")}
                    onChangeText={(v) => update({ knowledge_max_inject_chars: v ? parseInt(v) : null })} placeholder="8000" type="number" />
                </FormRow>
              </div>
            </div>
          )}

          {activeSection === "elevation" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Model Elevation</div>
              <div style={{ fontSize: 12, color: "#999", lineHeight: 1.6 }}>
                Automatically switches to a more capable (and expensive) model when the conversation becomes complex.
                On each turn, a rule-based classifier scores 8 weighted signals from 0.0 to 1.0. If the combined score
                meets or exceeds the <strong style={{ color: "#ccc" }}>threshold</strong>, the turn is sent to the
                {" "}<strong style={{ color: "#ccc" }}>elevated model</strong> instead of this bot's default model.
                No elevation occurs during compaction turns, or if the elevated model is the same as the bot's model.
              </div>

              <div style={{
                background: "#1a1a1a", border: "1px solid #2a2a2a", borderRadius: 6, padding: 14,
                display: "flex", flexDirection: "column", gap: 10,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#ccc" }}>Signals &amp; Weights</div>
                <div style={{ fontSize: 11, color: "#888", lineHeight: 1.7, fontFamily: "monospace" }}>
                  <div><span style={{ color: "#6b9" }}>message_length</span>{"   "}(+0.10) — long user messages (500-1500+ chars)</div>
                  <div><span style={{ color: "#6b9" }}>code_content</span>{"    "}(+0.20) — code blocks or inline backticks</div>
                  <div><span style={{ color: "#6b9" }}>keyword_elevate</span>{" "}(+0.20) — "explain", "design", "debug", "refactor", "analyze", etc.</div>
                  <div><span style={{ color: "#e66" }}>keyword_simple</span>{"  "}(-0.20) — "weather", "timer", "turn on/off", etc.</div>
                  <div><span style={{ color: "#6b9" }}>tool_complexity</span>{" "}(+0.15) — complex tools (delegation, exec) vs simple tools</div>
                  <div><span style={{ color: "#6b9" }}>conv_depth</span>{"      "}(+0.10) — number of tool messages in context (5-15+)</div>
                  <div><span style={{ color: "#6b9" }}>iteration_depth</span>{" "}(+0.10) — tool iterations so far this turn (3-8+)</div>
                  <div><span style={{ color: "#6b9" }}>prior_errors</span>{"    "}(+0.15) — error patterns in recent tool results</div>
                </div>
                <div style={{ fontSize: 11, color: "#666", lineHeight: 1.5 }}>
                  Each signal outputs 0.0-1.0, multiplied by its weight. The sum (clamped to 0-1) is compared against
                  the threshold. For example, a message with code (+0.14) and an "explain" keyword (+0.16) scores 0.30 —
                  below the default 0.4 threshold. Add a deep conversation (+0.08) and prior errors (+0.075) and it
                  crosses 0.4, triggering elevation.
                </div>
              </div>

              <div style={{
                background: "#1a1a1a", border: "1px solid #2a2a2a", borderRadius: 6, padding: 14,
                display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#ccc" }}>Config Resolution</div>
                <div style={{ fontSize: 11, color: "#888", lineHeight: 1.6 }}>
                  Settings resolve with priority: <strong style={{ color: "#ccc" }}>Bot</strong> &gt;{" "}
                  <strong style={{ color: "#ccc" }}>Channel</strong> &gt;{" "}
                  <strong style={{ color: "#ccc" }}>Global (.env)</strong>. Each field is resolved independently — a bot
                  can override the threshold while inheriting enabled/model from the channel or globals.
                  Set to "Inherit" to use the next level's value.
                </div>
              </div>

              <SelectInput
                value={draft.elevation_enabled === true ? "true" : draft.elevation_enabled === false ? "false" : ""}
                onChange={(v) => update({ elevation_enabled: v === "true" ? true : v === "false" ? false : null })}
                options={[{ label: "Inherit (default)", value: "" }, { label: "Enabled", value: "true" }, { label: "Disabled", value: "false" }]}
                style={{ maxWidth: 200 }}
              />
              <Row>
                <Col>
                  <FormRow label="Threshold (0.0-1.0)">
                    <TextInput value={String(draft.elevation_threshold ?? "")}
                      onChangeText={(v) => update({ elevation_threshold: v ? parseFloat(v) : null })} placeholder="inherit" type="number" />
                  </FormRow>
                  <div style={{ fontSize: 11, color: "#666", marginTop: 4 }}>
                    Lower = elevate more often (more expensive). Higher = only elevate for very complex turns. Default: 0.4.
                  </div>
                </Col>
                <Col>
                  <FormRow label="Elevated Model">
                    <LlmModelDropdown value={draft.elevated_model || ""} onChange={(v) => update({ elevated_model: v || null })} placeholder="inherit" />
                  </FormRow>
                  <div style={{ fontSize: 11, color: "#666", marginTop: 4 }}>
                    The model to switch to when elevation triggers. Typically a stronger/more expensive model than the bot's default.
                  </div>
                </Col>
              </Row>

              {/* Elevation observability */}
              {elevationData && (
                <>
                  {/* Stats bar */}
                  <div style={{
                    display: "flex", gap: 16, flexWrap: "wrap",
                    background: "#1a1a1a", border: "1px solid #2a2a2a", borderRadius: 6, padding: 14,
                  }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "#ccc" }}>Stats</div>
                    <div style={{ fontSize: 11, color: "#888" }}>
                      Total: <span style={{ color: "#e5e5e5" }}>{elevationData.stats.total_decisions}</span>
                    </div>
                    <div style={{ fontSize: 11, color: "#888" }}>
                      Elevated: <span style={{ color: "#f59e0b" }}>{elevationData.stats.elevated_count}</span>
                      {" "}({(elevationData.stats.elevation_rate * 100).toFixed(1)}%)
                    </div>
                    <div style={{ fontSize: 11, color: "#888" }}>
                      Avg score: <span style={{ color: "#e5e5e5" }}>{elevationData.stats.avg_score.toFixed(3)}</span>
                    </div>
                    {elevationData.stats.avg_latency_ms != null && (
                      <div style={{ fontSize: 11, color: "#888" }}>
                        Avg latency: <span style={{ color: "#e5e5e5" }}>{elevationData.stats.avg_latency_ms}ms</span>
                      </div>
                    )}
                  </div>

                  {/* Recent decisions */}
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#ccc", marginTop: 8 }}>Recent Decisions</div>
                  {elevationData.recent.length === 0 ? (
                    <div style={{ fontSize: 12, color: "#666", fontStyle: "italic" }}>No elevation decisions recorded yet.</div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {elevationData.recent.map((entry) => (
                        <div key={entry.id} style={{
                          background: entry.was_elevated ? "#1a1f1a" : "#1a1a1a",
                          border: `1px solid ${entry.was_elevated ? "#2a3a2a" : "#2a2a2a"}`,
                          borderRadius: 6, padding: 10,
                          display: "flex", flexDirection: "column", gap: 4,
                        }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                              <span style={{
                                fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 3,
                                background: entry.was_elevated ? "#f59e0b22" : "#33333366",
                                color: entry.was_elevated ? "#f59e0b" : "#888",
                              }}>
                                {entry.was_elevated ? "ELEVATED" : "BASE"}
                              </span>
                              <span style={{ fontSize: 11, color: "#ccc", fontFamily: "monospace" }}>
                                {entry.model_chosen}
                              </span>
                            </div>
                            <span style={{ fontSize: 10, color: "#666" }}>
                              {new Date(entry.created_at).toLocaleString()}
                            </span>
                          </div>
                          <div style={{ display: "flex", gap: 12, fontSize: 10, color: "#888" }}>
                            <span>score: <span style={{ color: "#e5e5e5" }}>{entry.classifier_score.toFixed(3)}</span></span>
                            {entry.tokens_used != null && <span>tokens: {entry.tokens_used}</span>}
                            {entry.latency_ms != null && <span>latency: {entry.latency_ms}ms</span>}
                          </div>
                          {entry.rules_fired.length > 0 && (
                            <div style={{ fontSize: 10, color: "#6b9" }}>
                              rules: {entry.rules_fired.join(", ")}
                            </div>
                          )}
                          {entry.elevation_reason && (
                            <div style={{ fontSize: 10, color: "#999" }}>{entry.elevation_reason}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {activeSection === "attachments" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Attachment Summarization</div>
              <div style={{ fontSize: 11, color: "#555" }}>Override global attachment summarization settings.</div>
              <SelectInput
                value={draft.attachment_summarization_enabled === true ? "true" : draft.attachment_summarization_enabled === false ? "false" : ""}
                onChange={(v) => update({ attachment_summarization_enabled: v === "true" ? true : v === "false" ? false : null })}
                options={[{ label: "Inherit (default)", value: "" }, { label: "Enabled", value: "true" }, { label: "Disabled", value: "false" }]}
                style={{ maxWidth: 200 }}
              />
              <Row>
                <Col>
                  <FormRow label="Vision / Summary Model">
                    <TextInput value={draft.attachment_summary_model ?? ""}
                      onChangeText={(v) => update({ attachment_summary_model: v || undefined })} placeholder="inherit" />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Text Max Chars">
                    <TextInput value={String(draft.attachment_text_max_chars ?? "")}
                      onChangeText={(v) => update({ attachment_text_max_chars: v ? parseInt(v) : null })} placeholder="40000" type="number" />
                  </FormRow>
                </Col>
              </Row>
              <div style={{ maxWidth: 200 }}>
                <FormRow label="Vision Concurrency">
                  <TextInput value={String(draft.attachment_vision_concurrency ?? "")}
                    onChangeText={(v) => update({ attachment_vision_concurrency: v ? parseInt(v) : null })} placeholder="3" type="number" />
                </FormRow>
              </div>
            </div>
          )}

          {activeSection === "workspace" && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 12 }}>Workspace</div>
              <WorkspaceSection editorData={editorData} draft={draft} update={update} />
            </div>
          )}

          {activeSection === "delegation" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Delegation</div>
              <div style={{ fontSize: 11, color: "#555" }}>Allow this bot to delegate work to other bots or external harnesses.</div>
              {editorData.all_bots.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 4, textTransform: "uppercase" }}>Delegate-to Bots</div>
                  <div style={{ fontSize: 10, color: "#555", marginBottom: 6 }}>@-tagged bots in messages bypass this list.</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
                    {editorData.all_bots.map((b) => {
                      const on = (draft.delegation_config?.delegate_bots || draft.delegate_bots || []).includes(b.id);
                      return (
                        <label key={b.id} style={{
                          display: "flex", alignItems: "center", gap: 6, padding: "4px 8px",
                          borderRadius: 4, cursor: "pointer", fontSize: 11,
                          background: on ? "rgba(139,92,246,0.08)" : "transparent",
                        }}>
                          <input type="checkbox" checked={on} style={{ accentColor: "#8b5cf6" }}
                            onChange={() => {
                              const dc = { ...draft.delegation_config };
                              const cur: string[] = dc.delegate_bots || draft.delegate_bots || [];
                              dc.delegate_bots = on ? cur.filter((x: string) => x !== b.id) : [...cur, b.id];
                              update({ delegation_config: dc });
                            }} />
                          <span style={{ color: on ? "#c4b5fd" : "#555" }}>{b.name}</span>
                          <span style={{ color: "#444", fontFamily: "monospace", fontSize: 10 }}>{b.id}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
              {editorData.all_harnesses.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 4, textTransform: "uppercase" }}>Harness Access</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
                    {editorData.all_harnesses.map((h) => {
                      const on = (draft.delegation_config?.harness_access || draft.harness_access || []).includes(h);
                      return (
                        <label key={h} style={{
                          display: "flex", alignItems: "center", gap: 6, padding: "4px 8px",
                          borderRadius: 4, cursor: "pointer", fontSize: 11,
                          background: on ? "rgba(139,92,246,0.08)" : "transparent",
                        }}>
                          <input type="checkbox" checked={on} style={{ accentColor: "#8b5cf6" }}
                            onChange={() => {
                              const dc = { ...draft.delegation_config };
                              const cur: string[] = dc.harness_access || draft.harness_access || [];
                              dc.harness_access = on ? cur.filter((x: string) => x !== h) : [...cur, h];
                              update({ delegation_config: dc });
                            }} />
                          <span style={{ fontFamily: "monospace", color: on ? "#c4b5fd" : "#555" }}>{h}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
              {editorData.all_bots.length === 0 && editorData.all_harnesses.length === 0 && (
                <div style={{ color: "#555", fontSize: 12 }}>No other bots or harnesses configured.</div>
              )}
            </div>
          )}

          {activeSection === "display" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Display</div>
              <Row>
                <Col>
                  <FormRow label="Display Name">
                    <TextInput value={draft.display_name || ""} onChangeText={(v) => update({ display_name: v || undefined })} placeholder={draft.name} />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Avatar URL">
                    <TextInput value={draft.avatar_url || ""} onChangeText={(v) => update({ avatar_url: v || undefined })} placeholder="https://..." />
                  </FormRow>
                </Col>
              </Row>
              <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "#555", textTransform: "uppercase", marginBottom: 8 }}>Slack</div>
                <div style={{ maxWidth: 300 }}>
                  <FormRow label="Icon Emoji" description="Overrides Avatar URL in Slack. Requires chat:write.customize.">
                    <TextInput value={draft.integration_config?.slack?.icon_emoji || ""}
                      onChangeText={(v) => {
                        const ic = { ...draft.integration_config };
                        ic.slack = { ...(ic.slack || {}), icon_emoji: v || undefined };
                        update({ integration_config: ic });
                      }} placeholder=":robot_face:" />
                  </FormRow>
                </div>
              </div>
            </div>
          )}

          {activeSection === "advanced" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Advanced</div>
              <FormRow label="Audio Input">
                <SelectInput value={draft.audio_input || "transcribe"} onChange={(v) => update({ audio_input: v })}
                  options={[{ label: "transcribe (Whisper STT)", value: "transcribe" }, { label: "native (multimodal)", value: "native" }]}
                  style={{ maxWidth: 300 }} />
              </FormRow>
            </div>
          )}

        </ScrollView>
      </div>
    </View>
  );
}
