import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { ArrowLeft, Save, Search, X } from "lucide-react";
import { useBotEditorData, useUpdateBot, useCreateBot } from "@/src/api/hooks/useBots";
import { useBotElevation } from "@/src/api/hooks/useElevation";
import { useGoBack } from "@/src/hooks/useGoBack";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { PromptTemplateSelector } from "@/src/components/shared/PromptTemplateSelector";
import {
  TextInput, SelectInput, Toggle, FormRow, Row, Col,
} from "@/src/components/shared/FormControls";
import type { BotConfig, BotEditorData } from "@/src/types/api";
import { useThemeTokens } from "@/src/theme/tokens";
import { MemorySection, KnowledgeSection } from "./MemoryKnowledgeSections";
import { SECTIONS, MOBILE_NAV_BREAKPOINT, type SectionKey } from "./constants";
import { BigTextarea } from "./BigTextarea";
import { SectionNav } from "./SectionNav";
import { ModelParamsSection } from "./ModelParamsSection";
import { ToolsSection } from "./ToolsSection";
import { SkillsSection } from "./SkillsSection";
import { WorkspaceSection } from "./WorkspaceSection";
import { BotPermissionsSection } from "./BotPermissionsSection";
import { BotToolPoliciesSection } from "./BotToolPoliciesSection";
import { HistoryModeSection } from "./HistoryModeSection";

// ---------------------------------------------------------------------------
// Main Bot Editor
// ---------------------------------------------------------------------------
export default function BotEditorScreen() {
  const t = useThemeTokens();
  const { botId } = useLocalSearchParams<{ botId: string }>();
  const isNew = botId === "new";
  const router = useRouter();
  const goBack = useGoBack("/admin/bots");
  const { data: editorData, isLoading } = useBotEditorData(botId);
  const { data: elevationData } = useBotElevation(isNew ? undefined : botId);
  const updateMutation = useUpdateBot(isNew ? undefined : botId);
  const createMutation = useCreateBot();
  const scrollRef = useRef<ScrollView>(null);
  const systemPromptRef = useRef<HTMLTextAreaElement>(null);

  const { width: windowWidth } = useWindowDimensions();
  const isMobile = windowWidth < MOBILE_NAV_BREAKPOINT;

  const [activeSection, setActiveSection] = useState<SectionKey>("identity");
  const [filter, setFilter] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [draft, setDraft] = useState<BotConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (editorData?.bot && !draft) {
      setDraft({ ...editorData.bot });
      if (isNew) setDirty(true);
    }
  }, [editorData]);

  const update = useCallback((patch: Partial<BotConfig>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
    setDirty(true);
    setSaved(false);
  }, []);

  const saveMutation = isNew ? createMutation : updateMutation;

  const handleSave = useCallback(async () => {
    if (!draft) return;
    const payload: any = { ...draft };
    if (draft.memory) { payload.memory_config = draft.memory; delete payload.memory; }
    if (draft.knowledge) { payload.knowledge_config = draft.knowledge; delete payload.knowledge; }
    if (!isNew) { delete payload.id; }
    delete payload.created_at; delete payload.updated_at;
    for (const key of Object.keys(payload)) { if (payload[key] === undefined) delete payload[key]; }
    try {
      if (isNew) {
        if (!payload.id || !payload.name || !payload.model) return;
        await createMutation.mutateAsync(payload);
        router.push(`/admin/bots/${payload.id}` as any);
      } else {
        await updateMutation.mutateAsync(payload);
      }
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (_) { /* handled by mutation state */ }
  }, [draft, isNew, createMutation, updateMutation, router]);

  const matchingSections = useMemo(() => {
    if (!filter) return new Set<SectionKey>(SECTIONS.map((s) => s.key));
    const q = filter.toLowerCase();
    const match = new Set<SectionKey>();
    const keywords: Record<SectionKey, string[]> = {
      identity: ["id", "name", "model", "provider", "temperature", "params", "creativity"],
      prompt: ["system", "prompt"],
      persona: ["persona", "personality", "tone"],
      tools: ["tool", "mcp", "client", "pin", "rag", "retrieval", "summarization"],
      skills: ["skill"],
      memory: ["memory", "cross", "channel"],
      knowledge: ["knowledge"],
      elevation: ["elevation", "elevate", "threshold"],
      attachments: ["attachment", "summarization", "vision"],
      workspace: ["workspace", "docker", "host", "exec", "sandbox", "index", "command", "port", "mount"],
      delegation: ["delegat", "harness", "bot"],
      permissions: ["permission", "scope", "api", "key", "access"],
      tool_policies: ["tool", "policy", "policies", "allow", "deny", "approval"],
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
        display: "flex", alignItems: "center", gap: isMobile ? 8 : 12,
        padding: isMobile ? "10px 12px" : "10px 16px", borderBottom: `1px solid ${t.surfaceRaised}`,
        flexWrap: isMobile && searchOpen ? "wrap" : "nowrap",
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <ArrowLeft size={18} color={t.textMuted} />
        </button>
        {(!isMobile || !searchOpen) && (
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{isNew ? "New Bot" : draft.name}</div>
            {!isNew && <div style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>{draft.id}</div>}
          </div>
        )}
        {isMobile ? (
          searchOpen ? (
            <div style={{
              display: "flex", alignItems: "center", gap: 6, flex: 1,
              background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6, padding: "4px 10px", minHeight: 36,
            }}>
              <Search size={14} color={t.textDim} />
              <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find setting..."
                autoFocus
                style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 16 }} />
              <button onClick={() => { setFilter(""); setSearchOpen(false); }} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, minWidth: 24, minHeight: 24, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <X size={14} color={t.textDim} />
              </button>
            </div>
          ) : (
            <button onClick={() => setSearchOpen(true)} style={{ background: "none", border: "none", cursor: "pointer", padding: 8, minWidth: 44, minHeight: 44, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Search size={16} color={t.textMuted} />
            </button>
          )
        ) : (
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6, padding: "4px 10px", width: 180,
          }}>
            <Search size={12} color={t.textDim} />
            <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find setting..."
              style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 14 }} />
            {filter && (
              <button onClick={() => setFilter("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                <X size={10} color={t.textDim} />
              </button>
            )}
          </div>
        )}
        <button
          onClick={handleSave}
          disabled={!dirty || saveMutation.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: isMobile ? "6px 12px" : "6px 16px", borderRadius: 6, border: "none",
            background: dirty ? t.accent : t.surfaceRaised,
            color: dirty ? "#fff" : t.textDim,
            fontSize: 12, fontWeight: 600, cursor: dirty ? "pointer" : "default",
            opacity: saveMutation.isPending ? 0.6 : 1,
            minHeight: 36,
          }}
        >
          <Save size={13} />
          {saveMutation.isPending ? "..." : saved ? "Saved!" : isNew ? "Create" : "Save"}
        </button>
      </div>

      {saveMutation.isError && (
        <div style={{ padding: "8px 16px", background: "#7f1d1d33", color: "#dc2626", fontSize: 12 }}>
          {(saveMutation.error as Error)?.message || "Failed to save"}
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

        <ScrollView ref={scrollRef} className="flex-1" contentContainerStyle={{ padding: isMobile ? 12 : 20, maxWidth: 800, width: "100%" }}>

          {activeSection === "identity" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text, marginBottom: 4 }}>Identity</div>
              <Row>
                <Col>
                  <FormRow label="Bot ID">
                    <TextInput
                      value={draft.id}
                      onChangeText={isNew ? (v) => update({ id: v.toLowerCase().replace(/[^a-z0-9_-]/g, "") }) : () => {}}
                      style={isNew ? {} : { opacity: 0.5, cursor: "not-allowed" }}
                      placeholder="my-bot-id"
                    />
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
              <FormRow label="Fallback Models" description="Ordered list of models tried when the primary fails. Global list is appended as catch-all.">
                <FallbackModelList
                  value={draft.fallback_models ?? []}
                  onChange={(v) => update({ fallback_models: v })}
                />
              </FormRow>
              {editorData.model_param_definitions?.length > 0 && (
                <ModelParamsSection
                  definitions={editorData.model_param_definitions}
                  support={editorData.model_param_support}
                  model={draft.model}
                  params={draft.model_params || {}}
                  onChange={(p) => update({ model_params: p })}
                />
              )}
            </div>
          )}

          {activeSection === "prompt" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>System Prompt</div>
                <PromptTemplateSelector
                  textareaRef={systemPromptRef}
                  value={draft.system_prompt || ""}
                  onChange={(v) => update({ system_prompt: v })}
                  workspaceId={draft.shared_workspace_id ?? undefined}
                />
              </div>
              <BigTextarea
                ref={systemPromptRef}
                value={draft.system_prompt || ""}
                onChange={(v) => update({ system_prompt: v })}
                placeholder="Enter system prompt..."
                minRows={28}
              />
            </div>
          )}

          {activeSection === "persona" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Persona</div>
              <div style={{ fontSize: 11, color: t.textDim }}>Injects a persistent personality/tone as a separate system message (distinct from the system prompt).</div>
              {editorData.bot.persona_from_workspace ? (
                <>
                  <div style={{ opacity: 0.6, pointerEvents: "none" }}>
                    <Toggle value={true} onChange={() => {}} label="Enable Persona" />
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 10, color: t.textDim, background: "rgba(147,197,253,0.12)", padding: "2px 8px", borderRadius: 4 }}>
                      workspace file
                    </span>
                    <span style={{ fontSize: 11, color: "#2563eb" }}>
                      <code style={{ color: "#d97706" }}>bots/{editorData.bot.id}/persona.md</code>
                    </span>
                  </div>
                  {editorData.bot.shared_workspace_id && (
                    <a
                      href={`/admin/workspaces/${editorData.bot.shared_workspace_id}`}
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 4,
                        fontSize: 11, fontWeight: 600, color: "#2563eb",
                        textDecoration: "none", alignSelf: "flex-start",
                      }}
                    >
                      Open Workspace &rarr;
                    </a>
                  )}
                  <div style={{ opacity: 0.6 }}>
                    <BigTextarea
                      value={editorData.bot.workspace_persona_content || ""}
                      onChange={() => {}}
                      placeholder=""
                      minRows={20}
                      readOnly
                    />
                  </div>
                </>
              ) : (
                <>
                  <Toggle value={draft.persona ?? false} onChange={(v) => update({ persona: v })} label="Enable Persona" />
                  {draft.persona && (
                    <BigTextarea
                      value={draft.persona_content || ""}
                      onChange={(v) => update({ persona_content: v })}
                      placeholder="Describe the bot's personality, tone, and style..."
                      minRows={20}
                    />
                  )}
                  {draft.shared_workspace_id && (
                    <div style={{ padding: "8px 0", fontSize: 11, color: t.textDim, lineHeight: 1.6 }}>
                      Tip: Create <code style={{ color: "#d97706" }}>bots/{draft.id || "bot-id"}/persona.md</code> in the workspace to manage persona as a file.
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {activeSection === "tools" && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text, marginBottom: 12 }}>Tools</div>
              <ToolsSection editorData={editorData} draft={draft} update={update} />
            </div>
          )}

          {activeSection === "skills" && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text, marginBottom: 12 }}>Skills</div>
              <SkillsSection editorData={editorData} draft={draft} update={update} />
              {editorData.workspace_skills && editorData.workspace_skills.length > 0 && (
                <div style={{ marginTop: 20 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: "#9333ea" }}>Workspace Skills</span>
                    <span style={{ fontSize: 10, color: t.textDim, background: "rgba(168,85,247,0.12)", padding: "2px 8px", borderRadius: 4 }}>
                      auto-injected
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: t.textDim, marginBottom: 8 }}>
                    These skills come from the workspace filesystem and are automatically injected into this bot's context.
                    Manage them by adding/removing <code style={{ color: t.textMuted }}>.md</code> files in the workspace <code style={{ color: t.textMuted }}>common/skills/</code> or <code style={{ color: t.textMuted }}>bots/{"{bot_id}"}/skills/</code> directories.
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 6 }}>
                    {editorData.workspace_skills.map((ws) => (
                      <div key={ws.skill_id} style={{
                        padding: 8, borderRadius: 6,
                        background: "rgba(168,85,247,0.04)",
                        border: "1px solid #2d1f4e",
                      }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ fontSize: 12, fontWeight: 500, color: "#9333ea" }}>{ws.name}</span>
                          <span style={{
                            fontSize: 9, padding: "1px 6px", borderRadius: 3,
                            background: "rgba(168,85,247,0.15)", color: "#a78bfa",
                          }}>{ws.mode}</span>
                          {ws.bot_id && (
                            <span style={{ fontSize: 9, color: t.textDim, fontFamily: "monospace" }}>bot: {ws.bot_id}</span>
                          )}
                        </div>
                        <div style={{ fontSize: 10, color: t.textDim, marginTop: 2, fontFamily: "monospace" }}>
                          {ws.source_path}
                        </div>
                        <div style={{ fontSize: 10, color: t.surfaceBorder, marginTop: 2 }}>
                          {ws.chunk_count} chunks {ws.workspace_name && <span>· {ws.workspace_name}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {draft.api_permissions && draft.api_permissions.length > 0 && draft.api_docs_mode && (
                <div style={{ marginTop: 20 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: "#3b82f6" }}>Virtual Skills</span>
                    <span style={{ fontSize: 10, color: t.textDim, background: "rgba(59,130,246,0.12)", padding: "2px 8px", borderRadius: 4 }}>
                      from permissions
                    </span>
                  </div>
                  <div style={{
                    padding: 8, borderRadius: 6,
                    background: "rgba(59,130,246,0.04)",
                    border: "1px solid rgba(59,130,246,0.15)",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontSize: 12, fontWeight: 500, color: "#3b82f6" }}>api_reference</span>
                      <span style={{
                        fontSize: 9, padding: "1px 6px", borderRadius: 3,
                        background: "rgba(59,130,246,0.15)", color: "#60a5fa",
                      }}>on-demand</span>
                    </div>
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
                      Auto-generated API docs filtered to this bot's {draft.api_permissions.length} scope{draft.api_permissions.length !== 1 ? "s" : ""}.
                      Available via <code style={{ color: t.textMuted, fontSize: 10 }}>get_skill("api_reference")</code>.
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeSection === "memory" && (
            <MemorySection draft={draft} update={update} botId={botId} />
          )}

          {activeSection === "knowledge" && (
            <KnowledgeSection draft={draft} update={update} />
          )}

          {activeSection === "elevation" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Model Elevation</div>
              <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
                Automatically switches to a more capable (and expensive) model when the conversation becomes complex.
                On each turn, a rule-based classifier scores 8 weighted signals from 0.0 to 1.0. If the combined score
                meets or exceeds the <strong style={{ color: t.text }}>threshold</strong>, the turn is sent to the
                {" "}<strong style={{ color: t.text }}>elevated model</strong> instead of this bot's default model.
                No elevation occurs during compaction turns, or if the elevated model is the same as the bot's model.
              </div>

              <div style={{
                background: t.surfaceRaised, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6, padding: 14,
                display: "flex", flexDirection: "column", gap: 10,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>Signals &amp; Weights</div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.7, fontFamily: "monospace" }}>
                  <div><span style={{ color: "#6b9" }}>message_length</span>{"   "}(+0.10) — long user messages (500-1500+ chars)</div>
                  <div><span style={{ color: "#6b9" }}>code_content</span>{"    "}(+0.20) — code blocks or inline backticks</div>
                  <div><span style={{ color: "#6b9" }}>keyword_elevate</span>{" "}(+0.20) — "explain", "design", "debug", "refactor", "analyze", etc.</div>
                  <div><span style={{ color: "#e66" }}>keyword_simple</span>{"  "}(-0.20) — "weather", "timer", "turn on/off", etc.</div>
                  <div><span style={{ color: "#6b9" }}>tool_complexity</span>{" "}(+0.15) — complex tools (delegation, exec) vs simple tools</div>
                  <div><span style={{ color: "#6b9" }}>conv_depth</span>{"      "}(+0.10) — number of tool messages in context (5-15+)</div>
                  <div><span style={{ color: "#6b9" }}>iteration_depth</span>{" "}(+0.10) — tool iterations so far this turn (3-8+)</div>
                  <div><span style={{ color: "#6b9" }}>prior_errors</span>{"    "}(+0.15) — error patterns in recent tool results</div>
                </div>
                <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.5 }}>
                  Each signal outputs 0.0-1.0, multiplied by its weight. The sum (clamped to 0-1) is compared against
                  the threshold. For example, a message with code (+0.14) and an "explain" keyword (+0.16) scores 0.30 —
                  below the default 0.4 threshold. Add a deep conversation (+0.08) and prior errors (+0.075) and it
                  crosses 0.4, triggering elevation.
                </div>
              </div>

              <div style={{
                background: t.surfaceRaised, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6, padding: 14,
                display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>Config Resolution</div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6 }}>
                  Settings resolve with priority: <strong style={{ color: t.text }}>Bot</strong> &gt;{" "}
                  <strong style={{ color: t.text }}>Channel</strong> &gt;{" "}
                  <strong style={{ color: t.text }}>Global (.env)</strong>. Each field is resolved independently — a bot
                  can override the threshold while inheriting enabled/model from the channel or globals.
                  Set to "Inherit" to use the next level's value.
                </div>
              </div>

              <SelectInput
                value={draft.elevation_enabled === true ? "true" : draft.elevation_enabled === false ? "false" : ""}
                onChange={(v) => update({ elevation_enabled: v === "true" ? true : v === "false" ? false : null })}
                options={[{ label: "Inherit (default)", value: "" }, { label: "Enabled", value: "true" }, { label: "Disabled", value: "false" }]}
                style={{ maxWidth: 300 }}
              />
              <Row>
                <Col>
                  <FormRow label="Threshold (0.0-1.0)">
                    <TextInput value={String(draft.elevation_threshold ?? "")}
                      onChangeText={(v) => update({ elevation_threshold: v ? parseFloat(v) : null })} placeholder="inherit" type="number" />
                  </FormRow>
                  <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>
                    Lower = elevate more often (more expensive). Higher = only elevate for very complex turns. Default: 0.4.
                  </div>
                </Col>
                <Col>
                  <FormRow label="Elevated Model">
                    <LlmModelDropdown value={draft.elevated_model || ""} onChange={(v) => update({ elevated_model: v || null })} placeholder="inherit" />
                  </FormRow>
                  <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>
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
                    background: t.surfaceRaised, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6, padding: 14,
                  }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>Stats</div>
                    <div style={{ fontSize: 11, color: t.textMuted }}>
                      Total: <span style={{ color: t.text }}>{elevationData.stats.total_decisions}</span>
                    </div>
                    <div style={{ fontSize: 11, color: t.textMuted }}>
                      Elevated: <span style={{ color: "#f59e0b" }}>{elevationData.stats.elevated_count}</span>
                      {" "}({(elevationData.stats.elevation_rate * 100).toFixed(1)}%)
                    </div>
                    <div style={{ fontSize: 11, color: t.textMuted }}>
                      Avg score: <span style={{ color: t.text }}>{elevationData.stats.avg_score.toFixed(3)}</span>
                    </div>
                    {elevationData.stats.avg_latency_ms != null && (
                      <div style={{ fontSize: 11, color: t.textMuted }}>
                        Avg latency: <span style={{ color: t.text }}>{elevationData.stats.avg_latency_ms}ms</span>
                      </div>
                    )}
                  </div>

                  {/* Recent decisions */}
                  <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginTop: 8 }}>Recent Decisions</div>
                  {elevationData.recent.length === 0 ? (
                    <div style={{ fontSize: 12, color: t.textDim, fontStyle: "italic" }}>No elevation decisions recorded yet.</div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {elevationData.recent.map((entry) => (
                        <div key={entry.id} style={{
                          background: entry.was_elevated ? "#1a1f1a" : t.surfaceRaised,
                          border: `1px solid ${entry.was_elevated ? "#2a3a2a" : t.surfaceOverlay}`,
                          borderRadius: 6, padding: 10,
                          display: "flex", flexDirection: "column", gap: 4,
                        }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                              <span style={{
                                fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 3,
                                background: entry.was_elevated ? "#f59e0b22" : "#33333366",
                                color: entry.was_elevated ? "#f59e0b" : t.textMuted,
                              }}>
                                {entry.was_elevated ? "ELEVATED" : "BASE"}
                              </span>
                              <span style={{ fontSize: 11, color: t.text, fontFamily: "monospace" }}>
                                {entry.model_chosen}
                              </span>
                            </div>
                            <span style={{ fontSize: 10, color: t.textDim }}>
                              {new Date(entry.created_at).toLocaleString()}
                            </span>
                          </div>
                          <div style={{ display: "flex", gap: 12, fontSize: 10, color: t.textMuted }}>
                            <span>score: <span style={{ color: t.text }}>{entry.classifier_score.toFixed(3)}</span></span>
                            {entry.tokens_used != null && <span>tokens: {entry.tokens_used}</span>}
                            {entry.latency_ms != null && <span>latency: {entry.latency_ms}ms</span>}
                          </div>
                          {entry.rules_fired.length > 0 && (
                            <div style={{ fontSize: 10, color: "#6b9" }}>
                              rules: {entry.rules_fired.join(", ")}
                            </div>
                          )}
                          {entry.elevation_reason && (
                            <div style={{ fontSize: 10, color: t.textMuted }}>{entry.elevation_reason}</div>
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
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Attachment Summarization</div>
              <div style={{ fontSize: 11, color: t.textDim }}>Override global attachment summarization settings.</div>
              <SelectInput
                value={draft.attachment_summarization_enabled === true ? "true" : draft.attachment_summarization_enabled === false ? "false" : ""}
                onChange={(v) => update({ attachment_summarization_enabled: v === "true" ? true : v === "false" ? false : null })}
                options={[{ label: "Inherit (default)", value: "" }, { label: "Enabled", value: "true" }, { label: "Disabled", value: "false" }]}
                style={{ maxWidth: 300 }}
              />
              <Row>
                <Col>
                  <FormRow label="Vision / Summary Model">
                    <LlmModelDropdown
                      value={draft.attachment_summary_model ?? ""}
                      onChange={(v) => update({ attachment_summary_model: v || undefined })}
                      placeholder="inherit"
                      allowClear
                    />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Text Max Chars">
                    <TextInput value={String(draft.attachment_text_max_chars ?? "")}
                      onChangeText={(v) => update({ attachment_text_max_chars: v ? parseInt(v) : null })} placeholder="40000" type="number" />
                  </FormRow>
                </Col>
              </Row>
              <div style={{ maxWidth: 300 }}>
                <FormRow label="Vision Concurrency">
                  <TextInput value={String(draft.attachment_vision_concurrency ?? "")}
                    onChangeText={(v) => update({ attachment_vision_concurrency: v ? parseInt(v) : null })} placeholder="3" type="number" />
                </FormRow>
              </div>
            </div>
          )}

          {activeSection === "workspace" && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text, marginBottom: 12 }}>Workspace</div>
              <WorkspaceSection editorData={editorData} draft={draft} update={update} />
            </div>
          )}

          {activeSection === "delegation" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Delegation</div>
              <div style={{ fontSize: 11, color: t.textDim }}>Allow this bot to delegate work to other bots or external harnesses.</div>
              {editorData.all_bots.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 4, textTransform: "uppercase" }}>Delegate-to Bots</div>
                  <div style={{ fontSize: 10, color: t.textDim, marginBottom: 6 }}>@-tagged bots in messages bypass this list.</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 2 }}>
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
                          <span style={{ color: on ? "#8b5cf6" : t.textDim }}>{b.name}</span>
                          <span style={{ color: t.surfaceBorder, fontFamily: "monospace", fontSize: 10 }}>{b.id}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
              {editorData.all_harnesses.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 4, textTransform: "uppercase" }}>Harness Access</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 2 }}>
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
                          <span style={{ fontFamily: "monospace", color: on ? "#8b5cf6" : t.textDim }}>{h}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
              {editorData.all_bots.length === 0 && editorData.all_harnesses.length === 0 && (
                <div style={{ color: t.textDim, fontSize: 12 }}>No other bots or harnesses configured.</div>
              )}
            </div>
          )}

          {activeSection === "permissions" && (
            <BotPermissionsSection
              permissions={draft.api_permissions || []}
              onChange={(p) => update({ api_permissions: p })}
              docsMode={draft.api_docs_mode}
              onDocsModeChange={(m) => update({ api_docs_mode: m })}
            />
          )}

          {activeSection === "tool_policies" && draft.id && (
            <BotToolPoliciesSection botId={draft.id} />
          )}

          {activeSection === "display" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Display</div>
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
              <div style={{ borderTop: `1px solid ${t.surfaceRaised}`, paddingTop: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 8 }}>Slack</div>
                <div>
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
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Advanced</div>
              <FormRow label="Audio Input">
                <SelectInput value={draft.audio_input || "transcribe"} onChange={(v) => update({ audio_input: v })}
                  options={[{ label: "transcribe (Whisper STT)", value: "transcribe" }, { label: "native (multimodal)", value: "native" }]}
                />
              </FormRow>
              <HistoryModeSection draft={draft} update={update} />
            </div>
          )}

        </ScrollView>
      </div>
    </View>
  );
}
