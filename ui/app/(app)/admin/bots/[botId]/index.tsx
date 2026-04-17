import { useMemo, useCallback, useRef, useEffect, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { AlertTriangle, Save, Search, Trash2, X } from "lucide-react";
import { useBotEditorData, useUpdateBot, useCreateBot, useDeleteBot } from "@/src/api/hooks/useBots";
import { useSettings } from "@/src/api/hooks/useSettings";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useHashTab } from "@/src/hooks/useHashTab";
import { CarapacesSection } from "./CarapacesSection";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { LlmPrompt, GenerateButton } from "@/src/components/shared/LlmPrompt";
import { PromptTemplateSelector } from "@/src/components/shared/PromptTemplateSelector";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import {
  TextInput, SelectInput, Toggle, FormRow, Row, Col,
} from "@/src/components/shared/FormControls";
import type { BotConfig, BotEditorData } from "@/src/types/api";
import { useThemeTokens } from "@/src/theme/tokens";
import { useUIStore } from "@/src/stores/ui";
import { MemorySection } from "./MemoryKnowledgeSections";
import { SECTIONS, SECTION_KEYS, MOBILE_NAV_BREAKPOINT, type SectionKey } from "./constants";
import { BigTextarea } from "./BigTextarea";
import { SectionNav } from "./SectionNav";
import { ModelParamsSection } from "./ModelParamsSection";
import { ToolsSection } from "./ToolsSection";
import { SkillsSection } from "./SkillsSection";
import { LearningSection } from "./LearningSection";
import { WorkspaceSection } from "./WorkspaceSection";
import { BotPermissionsSection } from "./BotPermissionsSection";
import { BotToolPoliciesSection } from "./BotToolPoliciesSection";
import { BotHooksSection } from "./BotHooksSection";
import { HistoryModeSection } from "./HistoryModeSection";

// ---------------------------------------------------------------------------
// Main Bot Editor
// ---------------------------------------------------------------------------
export default function BotEditorScreen() {
  const t = useThemeTokens();
  const { botId } = useParams<{ botId: string }>();
  const isNew = botId === "new";
  const navigate = useNavigate();
  const { data: editorData, isLoading } = useBotEditorData(botId);
  const updateMutation = useUpdateBot(isNew ? undefined : botId);
  const createMutation = useCreateBot();
  const scrollRef = useRef<HTMLDivElement>(null);
  const systemPromptRef = useRef<HTMLTextAreaElement>(null);

  const { width: windowWidth } = useWindowSize();
  const isMobile = windowWidth < MOBILE_NAV_BREAKPOINT;

  const [activeSection, setActiveSection] = useHashTab<SectionKey>("identity", SECTION_KEYS);
  const [filter, setFilter] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [draft, setDraft] = useState<BotConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleteChannelWarning, setDeleteChannelWarning] = useState<string | null>(null);
  const deleteMutation = useDeleteBot();

  // Enrich command palette recent with bot name
  const enrichRecentPage = useUIStore((s) => s.enrichRecentPage);
  const loc = useLocation();
  useEffect(() => {
    if (editorData?.bot?.name) enrichRecentPage(loc.pathname, editorData.bot.name);
  }, [editorData?.bot?.name, loc.pathname, enrichRecentPage]);

  // Global settings — used to show inherited values in attachment fields
  const { data: settingsData } = useSettings();
  const globalAttach = useMemo(() => {
    if (!settingsData) return { enabled: true, model: "", maxChars: "40000", concurrency: "3" };
    const all = settingsData.groups.flatMap((g) => g.settings);
    const get = (key: string) => all.find((s) => s.key === key);
    return {
      enabled: get("ATTACHMENT_SUMMARY_ENABLED")?.value ?? true,
      model: String(get("ATTACHMENT_SUMMARY_MODEL")?.value ?? ""),
      maxChars: String(get("ATTACHMENT_TEXT_MAX_CHARS")?.value ?? "40000"),
      concurrency: String(get("ATTACHMENT_VISION_CONCURRENCY")?.value ?? "3"),
    };
  }, [settingsData]);

  // Load draft when editorData arrives, AND reload when botId changes
  // (same-route navigation, e.g. Ctrl+K → different bot, reuses this component).
  const loadedBotIdRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (editorData?.bot && loadedBotIdRef.current !== botId) {
      setDraft({ ...editorData.bot });
      setDirty(isNew);
      setSaved(false);
      setFilter("");
      setSearchOpen(false);
      setShowDeleteConfirm(false);
      setDeleteConfirmText("");
      setDeleteChannelWarning(null);
      loadedBotIdRef.current = botId;
    }
  }, [editorData, botId, isNew]);

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
    if (!isNew) { delete payload.id; }
    delete payload.created_at; delete payload.updated_at;
    for (const key of Object.keys(payload)) { if (payload[key] === undefined) delete payload[key]; }
    try {
      if (isNew) {
        if (!payload.id || !payload.name || !payload.model) return;
        await createMutation.mutateAsync(payload);
        navigate(`/admin/bots/${payload.id}`);
      } else {
        await updateMutation.mutateAsync(payload);
      }
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (_) { /* handled by mutation state */ }
  }, [draft, isNew, createMutation, updateMutation, navigate]);

  const matchingSections = useMemo(() => {
    if (!filter) return new Set<SectionKey>(SECTIONS.map((s) => s.key));
    const q = filter.toLowerCase();
    const match = new Set<SectionKey>();
    const keywords: Record<SectionKey, string[]> = {
      identity: ["id", "name", "model", "provider", "temperature", "params", "creativity"],
      prompt: ["system", "prompt"],
      persona: ["persona", "personality", "tone"],
      tools: ["tool", "mcp", "client", "pin", "rag", "retrieval", "discovery", "summarization"],
      skills: ["skill"],
      learning: ["learning", "authored", "surfac", "knowledge"],
      carapaces: ["capability", "carapace", "bundle", "expert"],
      memory: ["memory", "cross", "channel"],
      attachments: ["attachment", "summarization", "vision"],
      workspace: ["workspace", "docker", "host", "exec", "sandbox", "index", "command", "port", "mount"],
      delegation: ["delegat", "bot"],
      permissions: ["permission", "scope", "api", "key", "access"],
      tool_policies: ["tool", "policy", "policies", "allow", "deny", "approval"],
      hooks: ["hook", "trigger", "before", "after", "path", "cooldown"],
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
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner color={t.accent} />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      {/* Header */}
      <PageHeader variant="detail"
        parentLabel="Bots"
        backTo="/admin/bots"
        title={isNew ? "New Bot" : draft.name}
        subtitle={isNew ? undefined : draft.id}
        hideTitle={isMobile && searchOpen}
        right={<>
          {isMobile ? (
            searchOpen ? (
              <div style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flex: 1,
                background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6, padding: "4px 10px", minHeight: 36,
              }}>
                <Search size={14} color={t.textDim} />
                <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find setting..."
                  autoFocus
                  style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 16 }} />
                <button onClick={() => { setFilter(""); setSearchOpen(false); }} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, minWidth: 24, minHeight: 24, display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center" }}>
                  <X size={14} color={t.textDim} />
                </button>
              </div>
            ) : (
              <button onClick={() => setSearchOpen(true)} style={{ background: "none", border: "none", cursor: "pointer", padding: 8, minWidth: 44, minHeight: 44, display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center" }}>
                <Search size={16} color={t.textMuted} />
              </button>
            )
          ) : (
            <div style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
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
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
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
        </>}
      />

      {saveMutation.isError && (
        <div style={{ padding: "8px 16px", background: t.dangerSubtle, color: t.danger, fontSize: 12 }}>
          {(saveMutation.error as Error)?.message || "Failed to save"}
        </div>
      )}

      {/* Section nav: dropdown on mobile, sidebar on desktop */}
      {isMobile && (
        <SectionNav active={activeSection} onSelect={setActiveSection} filter={filter} matchingSections={matchingSections} isMobile />
      )}

      {/* Body */}
      <div style={{ display: "flex", flexDirection: "row", flex: 1, overflow: "hidden" }}>
        {!isMobile && (
          <SectionNav active={activeSection} onSelect={setActiveSection} filter={filter} matchingSections={matchingSections} isMobile={false} />
        )}

        <div ref={scrollRef} className="flex-1" style={{ overflow: "auto", padding: isMobile ? 12 : 20, maxWidth: 800, width: "100%" }}>

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
                <LlmModelDropdown
                  value={draft.model}
                  selectedProviderId={draft.model_provider_id}
                  onChange={(v, pid) => update({ model: v, model_provider_id: pid ?? null })}
                />
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
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>System Prompt</div>
                <GenerateButton
                  fieldType="system_prompt"
                  botId={botId}
                  value={draft.system_prompt || ""}
                  onChange={(v) => update({ system_prompt: v })}
                />
                {!draft.system_prompt_workspace_file && (
                  <PromptTemplateSelector
                    textareaRef={systemPromptRef}
                    value={draft.system_prompt || ""}
                    onChange={(v) => update({ system_prompt: v })}
                    workspaceId={draft.shared_workspace_id ?? undefined}
                  />
                )}
              </div>
              {draft.shared_workspace_id && (
                <Toggle
                  value={draft.system_prompt_workspace_file ?? false}
                  onChange={(v) => {
                    update({ system_prompt_workspace_file: v });
                    if (!v) update({ system_prompt_write_protected: false });
                  }}
                  label="Use workspace file"
                  description={`Source system prompt from bots/${draft.id || "bot-id"}/system_prompt.md in the workspace`}
                />
              )}
              {draft.system_prompt_workspace_file && draft.shared_workspace_id ? (
                <>
                  <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 10, color: t.textDim, background: t.accentSubtle, padding: "2px 8px", borderRadius: 4 }}>
                      workspace file
                    </span>
                    <span style={{ fontSize: 11 }}>
                      <code style={{ color: t.warningMuted }}>bots/{draft.id}/system_prompt.md</code>
                    </span>
                  </div>
                  <a
                    href={`/admin/workspaces/${draft.shared_workspace_id}`}
                    style={{
                      display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
                      fontSize: 11, fontWeight: 600, color: t.accent,
                      textDecoration: "none", alignSelf: "flex-start",
                    }}
                  >
                    Open Workspace &rarr;
                  </a>
                  <Toggle
                    value={draft.system_prompt_write_protected ?? false}
                    onChange={(v) => update({ system_prompt_write_protected: v })}
                    label="Write-protect this file"
                    description="Prevents the bot from modifying this file via exec_command"
                  />
                </>
              ) : (
                <BigTextarea
                  ref={systemPromptRef}
                  value={draft.system_prompt || ""}
                  onChange={(v) => update({ system_prompt: v })}
                  placeholder="Enter system prompt..."
                  minRows={28}
                />
              )}
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
                  <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 10, color: t.textDim, background: t.accentSubtle, padding: "2px 8px", borderRadius: 4 }}>
                      workspace file
                    </span>
                    <span style={{ fontSize: 11, color: t.accent }}>
                      <code style={{ color: t.warningMuted }}>bots/{editorData.bot.id}/persona.md</code>
                    </span>
                  </div>
                  {editorData.bot.shared_workspace_id && (
                    <a
                      href={`/admin/workspaces/${editorData.bot.shared_workspace_id}`}
                      style={{
                        display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
                        fontSize: 11, fontWeight: 600, color: t.accent,
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
                      Tip: Create <code style={{ color: t.warningMuted }}>bots/{draft.id || "bot-id"}/persona.md</code> in the workspace to manage persona as a file.
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
              <SkillsSection editorData={editorData} draft={draft} update={update} onNavigateToLearning={() => setActiveSection("learning")} />
              {draft.api_permissions && draft.api_permissions.length > 0 && (
                <div style={{ marginTop: 20 }}>
                  <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: t.accent }}>API Access Tools</span>
                    <span style={{ fontSize: 10, color: t.textDim, background: t.accentSubtle, padding: "2px 8px", borderRadius: 4 }}>
                      from permissions
                    </span>
                  </div>
                  <div style={{
                    padding: 8, borderRadius: 6,
                    background: t.accentSubtle,
                    border: `1px solid ${t.accentBorder}`,
                  }}>
                    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <span style={{ fontSize: 12, fontWeight: 500, color: t.accent }}>list_api_endpoints + call_api</span>
                      <span style={{
                        fontSize: 9, padding: "1px 6px", borderRadius: 3,
                        background: t.accentSubtle, color: t.accent,
                      }}>pinned</span>
                    </div>
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
                      Direct API access filtered to this bot's {draft.api_permissions.length} scope{draft.api_permissions.length !== 1 ? "s" : ""}.
                      No sandbox or CLI needed.
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeSection === "learning" && draft.id && (
            <LearningSection botId={draft.id} />
          )}

          {activeSection === "carapaces" && (
            <CarapacesSection draft={draft} update={update} />
          )}

          {activeSection === "memory" && (
            <MemorySection draft={draft} update={update} botId={botId} />
          )}


          {activeSection === "attachments" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Attachment Summarization</div>
              <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
                Pre-processes incoming attachments before the agent loop begins.
                Override the global defaults here, or{" "}
                <a href="/settings#Attachments" style={{ color: t.accent, textDecoration: "none" }}>
                  edit global attachment settings &rarr;
                </a>
              </div>

              <div style={{
                background: t.surfaceRaised, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6, padding: 14,
                display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>How It Works</div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6 }}>
                  <strong style={{ color: t.text }}>Images</strong> are sent to the summary model below to generate a short
                  text description, which is stored with the attachment. <strong style={{ color: t.text }}>Text files</strong>{" "}
                  (code, markdown, PDF text, etc.) are extracted and truncated to the max-chars limit. Multiple
                  vision requests run concurrently up to the concurrency cap. All summarization happens before
                  the first LLM call.
                </div>
              </div>

              <div style={{
                background: `rgb(var(--color-accent) / 0.06)`, border: `1px solid rgb(var(--color-accent) / 0.15)`, borderRadius: 6, padding: 14,
                display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>Interaction with Agent Vision</div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6 }}>
                  This is <strong style={{ color: t.text }}>separate from the bot&apos;s own vision capability</strong>.
                  If the bot&apos;s model supports vision, the raw image is sent directly to the model as a native
                  image input — the model sees the actual pixels. The pre-generated summary is included alongside
                  it as additional context. If the model does <em>not</em> support vision, the summary is the only
                  way the model can understand the image.
                </div>
              </div>

              <div style={{
                background: t.surfaceRaised, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6, padding: 14,
                display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>Supported Types</div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.7, fontFamily: "monospace" }}>
                  <div><span style={{ color: "#6b9" }}>Images</span> — JPEG, PNG, GIF, WebP (summarized + sent natively if model has vision)</div>
                  <div><span style={{ color: "#6b9" }}>Text</span> — .txt, .md, .csv, .json, .py, .js, .ts, etc. (extracted &amp; truncated)</div>
                  <div><span style={{ color: "#6b9" }}>PDF</span> — text extracted, then truncated to max-chars</div>
                  <div><span style={{ color: "#e66" }}>Audio/Video</span> — not supported (ignored)</div>
                </div>
              </div>

              <div style={{
                background: t.surfaceRaised, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6, padding: 14,
                display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>Config Resolution</div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6 }}>
                  Settings resolve with priority: <strong style={{ color: t.text }}>Bot</strong> &gt;{" "}
                  <strong style={{ color: t.text }}>Global (.env / Settings)</strong>. There is no channel-level override
                  for attachment settings. Set to "Inherit" to use the global value.
                </div>
              </div>

              <SelectInput
                value={draft.attachment_summarization_enabled === true ? "true" : draft.attachment_summarization_enabled === false ? "false" : ""}
                onChange={(v) => update({ attachment_summarization_enabled: v === "true" ? true : v === "false" ? false : null })}
                options={[{ label: `Inherit (${globalAttach.enabled ? "Enabled" : "Disabled"})`, value: "" }, { label: "Enabled", value: "true" }, { label: "Disabled", value: "false" }]}
                style={{ maxWidth: 300 }}
              />
              <Row>
                <Col>
                  <FormRow label="Summary Model">
                    <LlmModelDropdown
                      value={draft.attachment_summary_model ?? ""}
                      selectedProviderId={draft.attachment_summary_model_provider_id ?? undefined}
                      onChange={(v, pid) => update({ attachment_summary_model: v || undefined, attachment_summary_model_provider_id: pid ?? undefined })}
                      placeholder={globalAttach.model ? `inherit (${globalAttach.model.split("/").pop()})` : "inherit"}
                      allowClear
                    />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Text Max Chars">
                    <TextInput value={String(draft.attachment_text_max_chars ?? "")}
                      onChangeText={(v) => update({ attachment_text_max_chars: v ? parseInt(v) : null })} placeholder={globalAttach.maxChars} type="number" />
                  </FormRow>
                </Col>
              </Row>
              <div style={{ maxWidth: 300 }}>
                <FormRow label="Summary Concurrency">
                  <TextInput value={String(draft.attachment_vision_concurrency ?? "")}
                    onChangeText={(v) => update({ attachment_vision_concurrency: v ? parseInt(v) : null })} placeholder={globalAttach.concurrency} type="number" />
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
              <div style={{ fontSize: 11, color: t.textDim }}>Allow this bot to delegate work to other bots.</div>
              {editorData.all_bots.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 4, textTransform: "uppercase" }}>Delegate-to Bots</div>
                  <div style={{ fontSize: 10, color: t.textDim, marginBottom: 6 }}>@-tagged bots in messages bypass this list.</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 2 }}>
                    {editorData.all_bots.map((b) => {
                      const on = (draft.delegation_config?.delegate_bots || draft.delegate_bots || []).includes(b.id);
                      return (
                        <label key={b.id} style={{
                          display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "4px 8px",
                          borderRadius: 4, cursor: "pointer", fontSize: 11,
                          background: on ? t.purpleSubtle : "transparent",
                        }}>
                          <input type="checkbox" checked={on} style={{ accentColor: t.purple }}
                            onChange={() => {
                              const dc = { ...draft.delegation_config };
                              const cur: string[] = dc.delegate_bots || draft.delegate_bots || [];
                              dc.delegate_bots = on ? cur.filter((x: string) => x !== b.id) : [...cur, b.id];
                              update({ delegation_config: dc });
                            }} />
                          <span style={{ color: on ? t.purple : t.textDim }}>{b.name}</span>
                          <span style={{ color: t.textDim, fontFamily: "monospace", fontSize: 10 }}>{b.id}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
              {editorData.all_bots.length === 0 && (
                <div style={{ color: t.textDim, fontSize: 12 }}>No other bots configured.</div>
              )}
            </div>
          )}

          {activeSection === "permissions" && (
            <BotPermissionsSection
              permissions={draft.api_permissions || []}
              onChange={(p) => update({ api_permissions: p })}
            />
          )}

          {activeSection === "tool_policies" && draft.id && (
            <BotToolPoliciesSection botId={draft.id} />
          )}

          {activeSection === "hooks" && draft.id && (
            <BotHooksSection botId={draft.id} />
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
              <FormRow label="Workspace-Files Memory" description="Enable workspace-files memory scheme (MEMORY.md, logs, reference). Required for dreaming.">
                <Toggle
                  value={draft.memory_scheme === "workspace-files"}
                  onChange={(v) => update({ memory_scheme: v ? "workspace-files" : null })}
                />
              </FormRow>
              <FormRow label="Audio Input">
                <SelectInput value={draft.audio_input || "transcribe"} onChange={(v) => update({ audio_input: v })}
                  options={[{ label: "transcribe (Whisper STT)", value: "transcribe" }, { label: "native (multimodal)", value: "native" }]}
                />
              </FormRow>
              <HistoryModeSection draft={draft} update={update} />
            </div>
          )}

          {/* Danger Zone — only for existing non-system bots */}
          {!isNew && draft.source_type !== "system" && (
            <div style={{
              marginTop: 32,
              border: `1px solid ${t.dangerBorder}`,
              borderRadius: 8,
              overflow: "hidden",
            }}>
              <div style={{
                padding: "10px 14px",
                background: t.dangerSubtle,
                borderBottom: `1px solid ${t.dangerBorder}`,
              }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: t.danger }}>Danger Zone</div>
              </div>
              <div style={{ padding: 16 }}>
                {!showDeleteConfirm ? (
                  <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
                    <div style={{ flex: 1, minWidth: 180 }}>
                      <div style={{ fontSize: 13, color: t.text, fontWeight: 600 }}>Delete this bot</div>
                      <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
                        Permanently removes the bot and its associated data (persona, tasks, tool policies, filesystem index).
                      </div>
                    </div>
                    <button
                      onClick={() => setShowDeleteConfirm(true)}
                      style={{
                        display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                        padding: "8px 16px", fontSize: 12, fontWeight: 600,
                        border: `1px solid ${t.dangerBorder}`, borderRadius: 6,
                        background: "transparent", color: t.danger, cursor: "pointer",
                        flexShrink: 0,
                      }}
                    >
                      <Trash2 size={13} color={t.danger} />
                      Delete Bot
                    </button>
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <div style={{
                      display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                      padding: "10px 14px", background: t.dangerSubtle, borderRadius: 6,
                    }}>
                      <AlertTriangle size={16} color={t.danger} />
                      <div style={{ fontSize: 12, color: t.danger, fontWeight: 600 }}>
                        This action cannot be undone.
                      </div>
                    </div>
                    <div style={{ fontSize: 12, color: t.textMuted }}>
                      Type <span style={{ fontFamily: "monospace", color: t.danger, fontWeight: 600 }}>delete</span> to confirm:
                    </div>
                    <input
                      type="text"
                      value={deleteConfirmText}
                      onChange={(e: any) => setDeleteConfirmText(e.target.value)}
                      placeholder="delete"
                      style={{
                        padding: "8px 12px", fontSize: 13,
                        background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                        color: t.text, outline: "none",
                      }}
                    />
                    <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
                      <button
                        onClick={async () => {
                          try {
                            // Try without force first; if 409, show channel warning and retry with force
                            if (!deleteChannelWarning) {
                              try {
                                await deleteMutation.mutateAsync({ botId: botId! });
                                navigate("/admin/bots", { replace: true });
                                return;
                              } catch (err: any) {
                                if (err?.status === 409 || err?.message?.includes("active channel")) {
                                  let detail = "Bot has active channels.";
                                  try { detail = JSON.parse(err?.body)?.detail || detail; } catch {}
                                  setDeleteChannelWarning(detail);
                                  return;
                                }
                                throw err;
                              }
                            }
                            await deleteMutation.mutateAsync({ botId: botId!, force: true });
                            navigate("/admin/bots", { replace: true });
                          } catch (_) { /* handled by mutation state */ }
                        }}
                        disabled={deleteConfirmText !== "delete" || deleteMutation.isPending}
                        style={{
                          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                          padding: "8px 20px", fontSize: 12, fontWeight: 700,
                          border: "none", borderRadius: 6, cursor: "pointer",
                          background: deleteConfirmText === "delete" ? t.danger : t.surfaceBorder,
                          color: deleteConfirmText === "delete" ? "#fff" : t.textDim,
                          opacity: deleteMutation.isPending ? 0.6 : 1,
                        }}
                      >
                        <Trash2 size={13} />
                        {deleteMutation.isPending ? "Deleting..." : deleteChannelWarning ? "Force Delete (including channels)" : "Permanently Delete"}
                      </button>
                      <button
                        onClick={() => { setShowDeleteConfirm(false); setDeleteConfirmText(""); setDeleteChannelWarning(null); }}
                        style={{
                          padding: "8px 16px", fontSize: 12, fontWeight: 500,
                          border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                          background: "transparent", color: t.textMuted, cursor: "pointer",
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                    {deleteChannelWarning && (
                      <div style={{
                        display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                        padding: "8px 12px", background: t.dangerSubtle, borderRadius: 6,
                      }}>
                        <AlertTriangle size={14} color={t.danger} />
                        <div style={{ fontSize: 11, color: t.danger }}>
                          {deleteChannelWarning} Click "Force Delete" to proceed anyway.
                        </div>
                      </div>
                    )}
                    {deleteMutation.isError && !deleteChannelWarning && (
                      <div style={{ fontSize: 11, color: t.danger }}>
                        {deleteMutation.error instanceof Error ? deleteMutation.error.message : "Failed to delete bot"}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
          {!isNew && draft.source_type === "system" && (
            <div style={{
              marginTop: 32, padding: "10px 14px",
              background: t.surfaceOverlay, borderRadius: 8,
              display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
            }}>
              <div style={{ fontSize: 11, color: t.textDim, fontWeight: 600 }}>
                System bot — cannot be deleted
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}

