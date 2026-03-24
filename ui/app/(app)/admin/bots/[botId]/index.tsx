import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { View, Text, ScrollView, ActivityIndicator, Pressable } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { ArrowLeft, Save, Search, X, ChevronRight } from "lucide-react";
import { useBotEditorData, useUpdateBot } from "@/src/api/hooks/useBots";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import {
  TextInput, SelectInput, Toggle, FormRow, Section, Row, Col,
} from "@/src/components/shared/FormControls";
import type { BotConfig, SkillConfig, BotEditorData } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Section definitions
// ---------------------------------------------------------------------------
const SECTIONS = [
  { key: "identity", label: "Identity" },
  { key: "prompt", label: "System Prompt" },
  { key: "tools", label: "Tools" },
  { key: "skills", label: "Skills" },
  { key: "memory", label: "Memory" },
  { key: "knowledge", label: "Knowledge" },
  { key: "persona", label: "Persona" },
  { key: "elevation", label: "Elevation" },
  { key: "attachments", label: "Attachments" },
  { key: "workspace", label: "Workspace" },
  { key: "delegation", label: "Delegation" },
  { key: "display", label: "Display" },
  { key: "advanced", label: "Advanced" },
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

// ---------------------------------------------------------------------------
// Section nav sidebar
// ---------------------------------------------------------------------------
function SectionNav({
  active,
  onSelect,
  filter,
  matchingSections,
}: {
  active: SectionKey;
  onSelect: (k: SectionKey) => void;
  filter: string;
  matchingSections: Set<SectionKey>;
}) {
  return (
    <div style={{
      width: 160, flexShrink: 0, borderRight: "1px solid #1a1a1a",
      paddingTop: 8, overflowY: "auto",
    }}>
      {SECTIONS.map((s) => {
        const dimmed = filter && !matchingSections.has(s.key);
        return (
          <button
            key={s.key}
            onClick={() => onSelect(s.key)}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              width: "100%", padding: "7px 12px", border: "none",
              background: active === s.key ? "#1a1a1a" : "transparent",
              borderLeft: active === s.key ? "2px solid #3b82f6" : "2px solid transparent",
              color: dimmed ? "#333" : active === s.key ? "#e5e5e5" : "#888",
              fontSize: 12, fontWeight: active === s.key ? 600 : 400,
              cursor: "pointer", textAlign: "left",
              transition: "all 0.1s",
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
// Checkbox grid for multi-select (tools, skills, bots, etc)
// ---------------------------------------------------------------------------
function CheckboxGrid({
  items,
  selected,
  onToggle,
  filter,
  columns = 2,
  mono = true,
}: {
  items: { value: string; label?: string }[];
  selected: string[];
  onToggle: (v: string) => void;
  filter?: string;
  columns?: number;
  mono?: boolean;
}) {
  const filtered = filter
    ? items.filter(
        (i) =>
          i.value.toLowerCase().includes(filter.toLowerCase()) ||
          (i.label || "").toLowerCase().includes(filter.toLowerCase())
      )
    : items;

  if (filtered.length === 0) {
    return <div style={{ color: "#555", fontSize: 11, padding: 8 }}>No matches</div>;
  }

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: `repeat(${columns}, 1fr)`,
      gap: 2,
    }}>
      {filtered.map((item) => {
        const checked = selected.includes(item.value);
        return (
          <label
            key={item.value}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "4px 8px", borderRadius: 4, cursor: "pointer",
              background: checked ? "rgba(59,130,246,0.1)" : "transparent",
              border: `1px solid ${checked ? "#3b82f633" : "#1a1a1a"}`,
              fontSize: 11,
            }}
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={() => onToggle(item.value)}
              style={{ accentColor: "#3b82f6" }}
            />
            <span style={{
              color: checked ? "#93c5fd" : "#999",
              fontFamily: mono ? "monospace" : "inherit",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }} title={item.label || item.value}>
              {item.label || item.value}
            </span>
          </label>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tool section with grouped display
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

  const toggleTool = useCallback((name: string) => {
    const current = draft.local_tools || [];
    update({
      local_tools: current.includes(name)
        ? current.filter((t) => t !== name)
        : [...current, name],
    });
  }, [draft.local_tools, update]);

  const togglePin = useCallback((name: string) => {
    const current = draft.pinned_tools || [];
    update({
      pinned_tools: current.includes(name)
        ? current.filter((t) => t !== name)
        : [...current, name],
    });
  }, [draft.pinned_tools, update]);

  const toggleMcp = useCallback((name: string) => {
    const current = draft.mcp_servers || [];
    update({
      mcp_servers: current.includes(name)
        ? current.filter((t) => t !== name)
        : [...current, name],
    });
  }, [draft.mcp_servers, update]);

  const toggleClient = useCallback((name: string) => {
    const current = draft.client_tools || [];
    update({
      client_tools: current.includes(name)
        ? current.filter((t) => t !== name)
        : [...current, name],
    });
  }, [draft.client_tools, update]);

  const localTools = draft.local_tools || [];
  const pinnedTools = draft.pinned_tools || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Tool filter */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        background: "#111", border: "1px solid #333", borderRadius: 6,
        padding: "4px 8px",
      }}>
        <Search size={12} color="#555" />
        <input
          type="text"
          value={toolFilter}
          onChange={(e) => setToolFilter(e.target.value)}
          placeholder="Filter tools..."
          style={{
            flex: 1, background: "transparent", border: "none", outline: "none",
            color: "#e5e5e5", fontSize: 12,
          }}
        />
        {toolFilter && (
          <button onClick={() => setToolFilter("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 2 }}>
            <X size={12} color="#555" />
          </button>
        )}
      </div>

      {/* Local tools by group */}
      {editorData.tool_groups.map((group) => (
        <div key={group.integration} style={{
          border: "1px solid #1a1a1a", borderRadius: 8, overflow: "hidden",
        }}>
          <div style={{
            padding: "6px 10px", background: "#0a0a0a",
            display: "flex", alignItems: "center", gap: 6,
          }}>
            {!group.is_core && (
              <span style={{
                fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 3,
                background: "#92400e33", color: "#fbbf24",
                textTransform: "uppercase", letterSpacing: "0.05em",
              }}>
                {group.integration}
              </span>
            )}
            {group.is_core && (
              <span style={{ fontSize: 11, fontWeight: 600, color: "#888" }}>Core Tools</span>
            )}
            <span style={{ fontSize: 10, color: "#444", marginLeft: "auto" }}>{group.total}</span>
          </div>
          {group.packs.map((pack) => {
            const filtered = toolFilter
              ? pack.tools.filter((t) => t.name.toLowerCase().includes(toolFilter.toLowerCase()))
              : pack.tools;
            if (filtered.length === 0) return null;
            return (
              <div key={pack.pack}>
                {group.packs.length > 1 && (
                  <div style={{ padding: "3px 10px", background: "#0a0a0a66", fontSize: 10, color: "#555", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    {pack.pack}
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, padding: 4 }}>
                  {filtered.map((tool) => {
                    const enabled = localTools.includes(tool.name);
                    const pinned = pinnedTools.includes(tool.name);
                    return (
                      <div
                        key={tool.name}
                        style={{
                          display: "flex", alignItems: "center", gap: 4,
                          padding: "3px 6px", borderRadius: 3, fontSize: 11,
                          background: enabled ? "rgba(59,130,246,0.08)" : "transparent",
                          border: `1px solid ${enabled ? "#3b82f622" : "#1a1a1a"}`,
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={enabled}
                          onChange={() => toggleTool(tool.name)}
                          style={{ accentColor: "#3b82f6" }}
                        />
                        <span
                          style={{
                            fontFamily: "monospace", color: enabled ? "#93c5fd" : "#666",
                            flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          }}
                          title={tool.name}
                        >
                          {tool.name}
                        </span>
                        {draft.tool_retrieval && enabled && (
                          <button
                            onClick={() => togglePin(tool.name)}
                            title={pinned ? "Unpin" : "Pin (bypass RAG)"}
                            style={{
                              background: "none", border: "none", cursor: "pointer",
                              fontSize: 10, padding: 0, opacity: pinned ? 1 : 0.3,
                            }}
                          >
                            📌
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      ))}

      {/* MCP Servers */}
      {editorData.mcp_servers.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            MCP Servers
          </div>
          <CheckboxGrid
            items={editorData.mcp_servers.map((s) => ({ value: s }))}
            selected={draft.mcp_servers || []}
            onToggle={toggleMcp}
            filter={toolFilter}
          />
        </div>
      )}

      {/* Client Tools */}
      {editorData.client_tools.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Client Tools
          </div>
          <CheckboxGrid
            items={editorData.client_tools.map((t) => ({ value: t }))}
            selected={draft.client_tools || []}
            onToggle={toggleClient}
            filter={toolFilter}
          />
        </div>
      )}

      {/* Tool Retrieval */}
      <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
        <Toggle
          value={draft.tool_retrieval ?? true}
          onChange={(v) => update({ tool_retrieval: v })}
          label="Tool Retrieval (RAG)"
          description="Embed tool descriptions and select only relevant tools per turn. Pinned tools bypass filtering."
        />
        {draft.tool_retrieval && (
          <div style={{ marginTop: 8, maxWidth: 200 }}>
            <FormRow label="Similarity Threshold">
              <TextInput
                value={String(draft.tool_similarity_threshold ?? "")}
                onChangeText={(v) => update({ tool_similarity_threshold: v ? parseFloat(v) : null })}
                placeholder="0.35"
                type="number"
              />
            </FormRow>
          </div>
        )}
      </div>

      {/* Tool Result Summarization */}
      <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "#e5e5e5", marginBottom: 4 }}>Tool Result Summarization</div>
        <div style={{ fontSize: 11, color: "#555", marginBottom: 8 }}>Summarizes large tool outputs before injecting into context.</div>
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
          style={{ maxWidth: 200 }}
        />
      </div>

      {/* Context Compression */}
      <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "#e5e5e5", marginBottom: 4 }}>Context Compression</div>
        <div style={{ fontSize: 11, color: "#555", marginBottom: 8 }}>Summarizes conversation history via a cheap model before each expensive LLM call.</div>
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
          style={{ maxWidth: 200 }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skills section
// ---------------------------------------------------------------------------
function SkillsSection({
  editorData,
  draft,
  update,
}: {
  editorData: BotEditorData;
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
}) {
  const [filter, setFilter] = useState("");
  const skills = draft.skills || [];

  const isSelected = (id: string) => skills.some((s) => s.id === id);
  const getEntry = (id: string) => skills.find((s) => s.id === id);

  const toggle = (id: string) => {
    if (isSelected(id)) {
      update({ skills: skills.filter((s) => s.id !== id) });
    } else {
      update({ skills: [...skills, { id, mode: "on_demand" }] });
    }
  };

  const setMode = (id: string, mode: string) => {
    update({
      skills: skills.map((s) =>
        s.id === id ? { ...s, mode, similarity_threshold: mode === "rag" ? s.similarity_threshold : null } : s
      ),
    });
  };

  const filtered = filter
    ? editorData.all_skills.filter(
        (s) =>
          s.id.toLowerCase().includes(filter.toLowerCase()) ||
          s.name.toLowerCase().includes(filter.toLowerCase()) ||
          (s.description || "").toLowerCase().includes(filter.toLowerCase())
      )
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
          display: "flex", alignItems: "center", gap: 8,
          background: "#111", border: "1px solid #333", borderRadius: 6, padding: "4px 8px",
        }}>
          <Search size={12} color="#555" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter skills..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#e5e5e5", fontSize: 12 }}
          />
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        {filtered.map((skill) => {
          const sel = isSelected(skill.id);
          const entry = getEntry(skill.id);
          return (
            <div
              key={skill.id}
              style={{
                padding: 8, borderRadius: 6,
                background: sel ? "rgba(59,130,246,0.06)" : "#0a0a0a",
                border: `1px solid ${sel ? "#3b82f633" : "#1a1a1a"}`,
              }}
            >
              <label style={{ display: "flex", alignItems: "flex-start", gap: 6, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={sel}
                  onChange={() => toggle(skill.id)}
                  style={{ accentColor: "#3b82f6", marginTop: 2 }}
                />
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
                  <select
                    value={entry.mode || "on_demand"}
                    onChange={(e) => setMode(skill.id, e.target.value)}
                    style={{
                      background: "#111", border: "1px solid #333", borderRadius: 4,
                      padding: "2px 8px", fontSize: 11, color: "#e5e5e5",
                    }}
                  >
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
// Main Bot Editor
// ---------------------------------------------------------------------------
export default function BotEditorScreen() {
  const { botId } = useLocalSearchParams<{ botId: string }>();
  const router = useRouter();
  const { data: editorData, isLoading } = useBotEditorData(botId);
  const updateMutation = useUpdateBot(botId);
  const scrollRef = useRef<ScrollView>(null);

  const [activeSection, setActiveSection] = useState<SectionKey>("identity");
  const [filter, setFilter] = useState("");
  const [draft, setDraft] = useState<BotConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  // Initialize draft from editor data
  useEffect(() => {
    if (editorData?.bot && !draft) {
      setDraft({ ...editorData.bot });
    }
  }, [editorData]);

  const update = useCallback((patch: Partial<BotConfig>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
    setDirty(true);
    setSaved(false);
  }, []);

  const handleSave = useCallback(async () => {
    if (!draft || !botId) return;
    // Build the update payload — send memory/knowledge as memory_config/knowledge_config
    const payload: any = { ...draft };
    if (draft.memory) {
      payload.memory_config = draft.memory;
      delete payload.memory;
    }
    if (draft.knowledge) {
      payload.knowledge_config = draft.knowledge;
      delete payload.knowledge;
    }
    // Remove read-only fields
    delete payload.id;
    delete payload.created_at;
    delete payload.updated_at;
    // Remove null/undefined to use PATCH semantics
    for (const key of Object.keys(payload)) {
      if (payload[key] === undefined) delete payload[key];
    }
    try {
      await updateMutation.mutateAsync(payload);
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      // Error handled by mutation state
    }
  }, [draft, botId, updateMutation]);

  // Search matching - which sections contain matching field names
  const matchingSections = useMemo(() => {
    if (!filter) return new Set<SectionKey>(SECTIONS.map((s) => s.key));
    const q = filter.toLowerCase();
    const match = new Set<SectionKey>();
    // Simple keyword matching per section
    const keywords: Record<SectionKey, string[]> = {
      identity: ["id", "name", "model", "provider"],
      prompt: ["system", "prompt"],
      tools: ["tool", "mcp", "client", "pin", "rag", "retrieval", "summarization", "compression"],
      skills: ["skill"],
      memory: ["memory", "cross", "channel"],
      knowledge: ["knowledge"],
      persona: ["persona"],
      elevation: ["elevation", "elevate", "threshold"],
      attachments: ["attachment", "summarization", "vision"],
      workspace: ["workspace", "docker", "host", "exec", "sandbox", "index"],
      delegation: ["delegat", "harness", "bot"],
      display: ["display", "avatar", "icon", "slack", "emoji"],
      advanced: ["audio", "compaction", "interval", "keep_turns"],
    };
    for (const [key, kws] of Object.entries(keywords)) {
      if (kws.some((kw) => kw.includes(q) || q.includes(kw))) {
        match.add(key as SectionKey);
      }
    }
    // Also match section labels
    for (const s of SECTIONS) {
      if (s.label.toLowerCase().includes(q)) match.add(s.key);
    }
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
        <button
          onClick={() => router.back()}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 4 }}
        >
          <ArrowLeft size={16} color="#888" />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#e5e5e5" }}>{draft.name}</div>
          <div style={{ fontSize: 10, color: "#555", fontFamily: "monospace" }}>{draft.id}</div>
        </div>

        {/* Search */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "#111", border: "1px solid #333", borderRadius: 6,
          padding: "4px 10px", width: 200,
        }}>
          <Search size={12} color="#555" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Find setting..."
            style={{
              flex: 1, background: "transparent", border: "none", outline: "none",
              color: "#e5e5e5", fontSize: 12,
            }}
          />
          {filter && (
            <button onClick={() => setFilter("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>
              <X size={10} color="#555" />
            </button>
          )}
        </div>

        {/* Save */}
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

      {/* Error banner */}
      {updateMutation.isError && (
        <div style={{ padding: "8px 16px", background: "#7f1d1d33", color: "#fca5a5", fontSize: 12 }}>
          {(updateMutation.error as Error)?.message || "Failed to save"}
        </div>
      )}

      {/* Body: nav + content */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <SectionNav
          active={activeSection}
          onSelect={setActiveSection}
          filter={filter}
          matchingSections={matchingSections}
        />

        <ScrollView
          ref={scrollRef}
          className="flex-1"
          contentContainerStyle={{ padding: 20, maxWidth: 800 }}
        >
          {/* Identity */}
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
                    <TextInput
                      value={draft.name}
                      onChangeText={(v) => update({ name: v })}
                    />
                  </FormRow>
                </Col>
              </Row>
              <FormRow label="Model">
                <LlmModelDropdown
                  value={draft.model}
                  onChange={(v) => update({ model: v })}
                />
              </FormRow>
            </div>
          )}

          {/* System Prompt */}
          {activeSection === "prompt" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>System Prompt</div>
              <LlmPrompt
                value={draft.system_prompt || ""}
                onChange={(v) => update({ system_prompt: v })}
                rows={16}
                placeholder="Enter system prompt..."
              />
            </div>
          )}

          {/* Tools */}
          {activeSection === "tools" && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 12 }}>Tools</div>
              <ToolsSection editorData={editorData} draft={draft} update={update} />
            </div>
          )}

          {/* Skills */}
          {activeSection === "skills" && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 12 }}>Skills</div>
              <SkillsSection editorData={editorData} draft={draft} update={update} />
            </div>
          )}

          {/* Memory */}
          {activeSection === "memory" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Memory</div>
              <div style={{ fontSize: 11, color: "#555" }}>
                Short facts stored between turns. Relevant memories retrieved by semantic similarity each turn.
              </div>
              <Toggle
                value={draft.memory?.enabled ?? false}
                onChange={(v) => update({ memory: { ...draft.memory, enabled: v } })}
                label="Enable Memory"
              />
              <Toggle
                value={draft.memory?.cross_channel ?? false}
                onChange={(v) => update({ memory: { ...draft.memory, cross_channel: v } })}
                label="Cross-Channel"
                description="Share memories across all channels for this client+bot"
              />
              <Row>
                <Col>
                  <FormRow label="Similarity Threshold">
                    <TextInput
                      value={String(draft.memory?.similarity_threshold ?? 0.45)}
                      onChangeText={(v) => update({ memory: { ...draft.memory, similarity_threshold: v ? parseFloat(v) : 0.45 } })}
                      type="number"
                    />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Max Inject Chars">
                    <TextInput
                      value={String(draft.memory_max_inject_chars ?? "")}
                      onChangeText={(v) => update({ memory_max_inject_chars: v ? parseInt(v) : null })}
                      placeholder="default (3000)"
                      type="number"
                    />
                  </FormRow>
                </Col>
              </Row>
              <FormRow label="Memory Prompt" description="Guidance on what the bot should remember">
                <LlmPrompt
                  value={draft.memory?.prompt || ""}
                  onChange={(v) => update({ memory: { ...draft.memory, prompt: v || undefined } })}
                  rows={4}
                  placeholder="Specific guidance on what's worth remembering..."
                />
              </FormRow>
            </div>
          )}

          {/* Knowledge */}
          {activeSection === "knowledge" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Knowledge</div>
              <div style={{ fontSize: 11, color: "#555" }}>
                Longer-form documents written by the bot via write_knowledge. Retrieved by semantic similarity per turn.
              </div>
              <Toggle
                value={draft.knowledge?.enabled ?? false}
                onChange={(v) => update({ knowledge: { ...draft.knowledge, enabled: v } })}
                label="Enable Knowledge"
              />
              <div style={{ maxWidth: 300 }}>
                <FormRow label="Max Inject Chars">
                  <TextInput
                    value={String(draft.knowledge_max_inject_chars ?? "")}
                    onChangeText={(v) => update({ knowledge_max_inject_chars: v ? parseInt(v) : null })}
                    placeholder="default (8000)"
                    type="number"
                  />
                </FormRow>
              </div>
            </div>
          )}

          {/* Persona */}
          {activeSection === "persona" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Persona</div>
              <div style={{ fontSize: 11, color: "#555" }}>
                Injects a persistent personality/tone as a separate system message.
              </div>
              <Toggle
                value={draft.persona ?? false}
                onChange={(v) => update({ persona: v })}
                label="Enable Persona"
              />
              {draft.persona && (
                <LlmPrompt
                  value={draft.persona_content || ""}
                  onChange={(v) => update({ persona_content: v })}
                  label="Persona Content"
                  rows={8}
                  placeholder="Describe the bot's personality, tone, and style..."
                />
              )}
            </div>
          )}

          {/* Elevation */}
          {activeSection === "elevation" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Model Elevation</div>
              <div style={{ fontSize: 11, color: "#555" }}>
                Automatically elevate to a more capable model for complex requests.
              </div>
              <SelectInput
                value={draft.elevation_enabled === true ? "true" : draft.elevation_enabled === false ? "false" : ""}
                onChange={(v) => update({ elevation_enabled: v === "true" ? true : v === "false" ? false : null })}
                options={[
                  { label: "Inherit (default)", value: "" },
                  { label: "Enabled", value: "true" },
                  { label: "Disabled", value: "false" },
                ]}
                style={{ maxWidth: 200 }}
              />
              <Row>
                <Col>
                  <FormRow label="Threshold (0.0-1.0)">
                    <TextInput
                      value={String(draft.elevation_threshold ?? "")}
                      onChangeText={(v) => update({ elevation_threshold: v ? parseFloat(v) : null })}
                      placeholder="inherit"
                      type="number"
                    />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Elevated Model">
                    <LlmModelDropdown
                      value={draft.elevated_model || ""}
                      onChange={(v) => update({ elevated_model: v || null })}
                      placeholder="inherit"
                    />
                  </FormRow>
                </Col>
              </Row>
            </div>
          )}

          {/* Attachments */}
          {activeSection === "attachments" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Attachment Summarization</div>
              <div style={{ fontSize: 11, color: "#555" }}>
                Override global attachment summarization settings for this bot.
              </div>
              <SelectInput
                value={draft.attachment_summarization_enabled === true ? "true" : draft.attachment_summarization_enabled === false ? "false" : ""}
                onChange={(v) => update({ attachment_summarization_enabled: v === "true" ? true : v === "false" ? false : null })}
                options={[
                  { label: "Inherit (default)", value: "" },
                  { label: "Enabled", value: "true" },
                  { label: "Disabled", value: "false" },
                ]}
                style={{ maxWidth: 200 }}
              />
              <Row>
                <Col>
                  <FormRow label="Vision / Summary Model">
                    <TextInput
                      value={draft.attachment_summary_model ?? ""}
                      onChangeText={(v) => update({ attachment_summary_model: v || null })}
                      placeholder="inherit"
                    />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Text Max Chars">
                    <TextInput
                      value={String(draft.attachment_text_max_chars ?? "")}
                      onChangeText={(v) => update({ attachment_text_max_chars: v ? parseInt(v) : null })}
                      placeholder="inherit (40000)"
                      type="number"
                    />
                  </FormRow>
                </Col>
              </Row>
              <div style={{ maxWidth: 300 }}>
                <FormRow label="Vision Concurrency">
                  <TextInput
                    value={String(draft.attachment_vision_concurrency ?? "")}
                    onChangeText={(v) => update({ attachment_vision_concurrency: v ? parseInt(v) : null })}
                    placeholder="inherit (3)"
                    type="number"
                  />
                </FormRow>
              </div>
            </div>
          )}

          {/* Workspace */}
          {activeSection === "workspace" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Workspace</div>
              <div style={{ fontSize: 11, color: "#555" }}>
                Unified execution environment. When enabled, exec_command, search_workspace, and delegate_to_exec tools are auto-injected.
              </div>
              <Toggle
                value={draft.workspace?.enabled ?? false}
                onChange={(v) => update({ workspace: { ...draft.workspace, enabled: v } })}
                label="Enable Workspace"
              />
              {draft.workspace?.enabled && (
                <>
                  <SelectInput
                    value={draft.workspace?.type || "docker"}
                    onChange={(v) => update({ workspace: { ...draft.workspace, type: v } })}
                    options={[
                      { label: "Docker Container", value: "docker" },
                      { label: "Host Execution", value: "host" },
                    ]}
                    style={{ maxWidth: 200 }}
                  />
                  <Row>
                    <Col>
                      <FormRow label="Timeout (seconds)">
                        <TextInput
                          value={String(draft.workspace?.timeout ?? "")}
                          onChangeText={(v) => update({ workspace: { ...draft.workspace, timeout: v ? parseInt(v) : null } })}
                          placeholder="default (30)"
                          type="number"
                        />
                      </FormRow>
                    </Col>
                    <Col>
                      <FormRow label="Max Output Bytes">
                        <TextInput
                          value={String(draft.workspace?.max_output_bytes ?? "")}
                          onChangeText={(v) => update({ workspace: { ...draft.workspace, max_output_bytes: v ? parseInt(v) : null } })}
                          placeholder="default (65536)"
                          type="number"
                        />
                      </FormRow>
                    </Col>
                  </Row>

                  {draft.workspace?.type === "docker" && (
                    <div style={{ borderLeft: "2px solid #1e3a5f", paddingLeft: 12 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: "#888", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>Docker Settings</div>
                      <Row>
                        <Col>
                          <FormRow label="Image">
                            <TextInput
                              value={draft.workspace?.docker?.image || ""}
                              onChangeText={(v) => update({ workspace: { ...draft.workspace, docker: { ...draft.workspace?.docker, image: v } } })}
                              placeholder="python:3.12-slim"
                            />
                          </FormRow>
                        </Col>
                        <Col>
                          <FormRow label="Network Mode">
                            <SelectInput
                              value={draft.workspace?.docker?.network || "none"}
                              onChange={(v) => update({ workspace: { ...draft.workspace, docker: { ...draft.workspace?.docker, network: v } } })}
                              options={[
                                { label: "none (no network)", value: "none" },
                                { label: "bridge", value: "bridge" },
                                { label: "host", value: "host" },
                              ]}
                            />
                          </FormRow>
                        </Col>
                      </Row>
                    </div>
                  )}

                  {draft.workspace?.type === "host" && (
                    <div style={{ borderLeft: "2px solid #166534", paddingLeft: 12 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: "#888", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>Host Settings</div>
                      <FormRow label="Custom Root">
                        <TextInput
                          value={draft.workspace?.host?.root || ""}
                          onChangeText={(v) => update({ workspace: { ...draft.workspace, host: { ...draft.workspace?.host, root: v } } })}
                          placeholder="auto: ~/.agent-workspaces/<bot-id>/"
                        />
                      </FormRow>
                    </div>
                  )}
                </>
              )}

              {/* Docker Sandbox Profiles */}
              {editorData.all_sandbox_profiles.length > 0 && (
                <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "#e5e5e5", marginBottom: 4 }}>Docker Sandbox Profiles</div>
                  <div style={{ fontSize: 11, color: "#555", marginBottom: 8 }}>
                    Restrict which profiles this bot can use.
                  </div>
                  <CheckboxGrid
                    items={editorData.all_sandbox_profiles.map((p) => ({
                      value: p.name,
                      label: p.description ? `${p.name} — ${p.description}` : p.name,
                    }))}
                    selected={draft.docker_sandbox_profiles || []}
                    onToggle={(name) => {
                      const current = draft.docker_sandbox_profiles || [];
                      update({
                        docker_sandbox_profiles: current.includes(name)
                          ? current.filter((n) => n !== name)
                          : [...current, name],
                      });
                    }}
                  />
                </div>
              )}
            </div>
          )}

          {/* Delegation */}
          {activeSection === "delegation" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Delegation</div>
              <div style={{ fontSize: 11, color: "#555" }}>
                Allow this bot to delegate work to other bots or external harnesses.
              </div>

              {editorData.all_bots.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Delegate-to Bots
                  </div>
                  <div style={{ fontSize: 10, color: "#555", marginBottom: 6 }}>
                    These bots can be called via delegate_to_agent. @-tagged bots bypass this list.
                  </div>
                  <CheckboxGrid
                    items={editorData.all_bots.map((b) => ({ value: b.id, label: `${b.name} (${b.id})` }))}
                    selected={draft.delegation_config?.delegate_bots || draft.delegate_bots || []}
                    onToggle={(id) => {
                      const dc = { ...draft.delegation_config };
                      const current = dc.delegate_bots || draft.delegate_bots || [];
                      dc.delegate_bots = current.includes(id)
                        ? current.filter((b: string) => b !== id)
                        : [...current, id];
                      update({ delegation_config: dc });
                    }}
                    mono={false}
                  />
                </div>
              )}

              {editorData.all_harnesses.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Harness Access
                  </div>
                  <div style={{ fontSize: 10, color: "#555", marginBottom: 6 }}>
                    External CLI harnesses this bot can invoke via delegate_to_harness.
                  </div>
                  <CheckboxGrid
                    items={editorData.all_harnesses.map((h) => ({ value: h }))}
                    selected={draft.delegation_config?.harness_access || draft.harness_access || []}
                    onToggle={(h) => {
                      const dc = { ...draft.delegation_config };
                      const current = dc.harness_access || draft.harness_access || [];
                      dc.harness_access = current.includes(h)
                        ? current.filter((x: string) => x !== h)
                        : [...current, h];
                      update({ delegation_config: dc });
                    }}
                  />
                </div>
              )}

              {editorData.all_bots.length === 0 && editorData.all_harnesses.length === 0 && (
                <div style={{ color: "#555", fontSize: 12 }}>No other bots or harnesses configured.</div>
              )}
            </div>
          )}

          {/* Display */}
          {activeSection === "display" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Display</div>
              <Row>
                <Col>
                  <FormRow label="Display Name">
                    <TextInput
                      value={draft.display_name || ""}
                      onChangeText={(v) => update({ display_name: v || undefined })}
                      placeholder={draft.name}
                    />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Avatar URL">
                    <TextInput
                      value={draft.avatar_url || ""}
                      onChangeText={(v) => update({ avatar_url: v || undefined })}
                      placeholder="https://..."
                    />
                  </FormRow>
                </Col>
              </Row>

              <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "#555", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>Slack</div>
                <div style={{ maxWidth: 300 }}>
                  <FormRow label="Icon Emoji" description="Overrides Avatar URL in Slack. Requires chat:write.customize.">
                    <TextInput
                      value={draft.integration_config?.slack?.icon_emoji || ""}
                      onChangeText={(v) => {
                        const ic = { ...draft.integration_config };
                        ic.slack = { ...(ic.slack || {}), icon_emoji: v || undefined };
                        update({ integration_config: ic });
                      }}
                      placeholder=":robot_face:"
                    />
                  </FormRow>
                </div>
              </div>
            </div>
          )}

          {/* Advanced */}
          {activeSection === "advanced" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5", marginBottom: 4 }}>Advanced</div>
              <FormRow label="Audio Input">
                <SelectInput
                  value={draft.audio_input || "transcribe"}
                  onChange={(v) => update({ audio_input: v })}
                  options={[
                    { label: "transcribe (Whisper STT)", value: "transcribe" },
                    { label: "native (multimodal)", value: "native" },
                  ]}
                  style={{ maxWidth: 300 }}
                />
              </FormRow>
              <div style={{ borderTop: "1px solid #1a1a1a", paddingTop: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 500, color: "#e5e5e5", marginBottom: 8 }}>Context Compaction</div>
                <Toggle
                  value={draft.context_compaction ?? true}
                  onChange={(v) => update({ context_compaction: v })}
                  label="Enable Compaction"
                  description="Summarise conversation history when it gets too long."
                />
                <Row gap={12}>
                  <Col>
                    <FormRow label="Compaction Interval (turns)">
                      <TextInput
                        value={String(draft.compaction_interval ?? "")}
                        onChangeText={(v) => update({ compaction_interval: v ? parseInt(v) : null })}
                        placeholder="default"
                        type="number"
                      />
                    </FormRow>
                  </Col>
                  <Col>
                    <FormRow label="Keep Turns (verbatim)">
                      <TextInput
                        value={String(draft.compaction_keep_turns ?? "")}
                        onChangeText={(v) => update({ compaction_keep_turns: v ? parseInt(v) : null })}
                        placeholder="default"
                        type="number"
                      />
                    </FormRow>
                  </Col>
                </Row>
              </div>
            </div>
          )}
        </ScrollView>
      </div>
    </View>
  );
}
