import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Bot, Brain, FileText, MessageSquare, Save, Shield, Trash2, Wrench, Zap } from "lucide-react";

import { ApiError } from "@/src/api/client";
import { useBotEditorData, useCreateBot, useDeleteBot, useUpdateBot } from "@/src/api/hooks/useBots";
import { useSettings } from "@/src/api/hooks/useSettings";
import { useUsageLogs, useUsageSummary } from "@/src/api/hooks/useUsage";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Col, FormRow, Row, SelectInput, TextInput, Toggle } from "@/src/components/shared/FormControls";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { GenerateButton, LlmPrompt } from "@/src/components/shared/LlmPrompt";
import {
  ActionButton,
  EmptyState,
  InfoBanner,
  QuietPill,
  SaveStatusPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSearchBox,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { SourceTextEditor } from "@/src/components/shared/SourceTextEditor";
import { Spinner } from "@/src/components/shared/Spinner";
import { TraceActionButton } from "@/src/components/shared/TraceActionButton";
import { UserSelect } from "@/src/components/shared/UserSelect";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { buildBotSavePayload } from "@/src/lib/botEditorPayload";
import { buildRecentHref } from "@/src/lib/recentPages";
import { useUIStore } from "@/src/stores/ui";
import type { BotConfig, BotEditorData } from "@/src/types/api";

import { BotHooksSection } from "./BotHooksSection";
import { BotPermissionsSection } from "./BotPermissionsSection";
import { BotToolPoliciesSection } from "./BotToolPoliciesSection";
import { GrantsSection } from "./GrantsSection";
import { HistoryModeSection } from "./HistoryModeSection";
import { LearningSection } from "./LearningSection";
import { MemorySection } from "./MemoryKnowledgeSections";
import { ModelParamsSection } from "./ModelParamsSection";
import { SectionNav } from "./SectionNav";
import { SkillsSection } from "./SkillsSection";
import { ToolsSection } from "./ToolsSection";
import { WorkspaceSection } from "./WorkspaceSection";
import { BOT_GROUPS, LEGACY_SECTION_TO_GROUP, MOBILE_NAV_BREAKPOINT, type BotGroupKey } from "./constants";

function fmtTokens(n: number | undefined | null): string {
  if (!n) return "--";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function activeFromHash(hash: string): BotGroupKey {
  const key = decodeURIComponent(hash.replace(/^#/, "") || "overview");
  return LEGACY_SECTION_TO_GROUP[key] ?? "overview";
}

function SectionFrame({ title, description, children, action }: {
  title: string;
  description?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[14px] font-semibold text-text">{title}</h2>
          {description && <p className="mt-1 max-w-[70ch] text-[12px] leading-relaxed text-text-dim">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function BotSourceBadges({ bot }: { bot: BotConfig }) {
  const workspace = bot.workspace ?? {};
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {bot.source_type && <QuietPill label={bot.source_type} />}
      {bot.system_prompt_workspace_file && <StatusBadge label="prompt file" variant="info" />}
      {bot.persona_from_workspace && <StatusBadge label="persona file" variant="info" />}
      {workspace.cross_workspace_access && <StatusBadge label="cross workspace" variant="warning" />}
      {!!bot.api_permissions?.length && <StatusBadge label={`${bot.api_permissions.length} api scopes`} variant="warning" />}
    </div>
  );
}

function OverviewSection({ draft, usage, logs, setGroup }: {
  draft: BotConfig;
  usage: ReturnType<typeof useUsageSummary>["data"];
  logs: ReturnType<typeof useUsageLogs>["data"];
  setGroup: (group: BotGroupKey) => void;
}) {
  const toolCount = (draft.local_tools?.length ?? 0) + (draft.client_tools?.length ?? 0) + (draft.pinned_tools?.length ?? 0);
  const delegateCount = (draft.delegation_config?.delegate_bots as string[] | undefined)?.length ?? draft.delegate_bots?.length ?? 0;
  const recent = logs?.entries ?? [];

  return (
    <div className="flex flex-col gap-6">
      <SectionFrame title="Operational snapshot" description="The fast read on what this bot is, how it is sourced, and what it has been doing recently.">
        <SettingsStatGrid
          items={[
            { label: "30d calls", value: usage?.total_calls?.toLocaleString() ?? "--" },
            { label: "30d tokens", value: fmtTokens(usage?.total_tokens) },
            { label: "30d cost", value: fmtCost(usage?.total_cost), tone: usage?.total_cost ? "accent" : "default" },
            { label: "Recent traces", value: recent.filter((entry) => entry.correlation_id).length },
          ]}
        />
        <div className="grid gap-2 md:grid-cols-2">
          <SettingsControlRow leading={<Bot size={15} />} title={draft.name || "Unnamed bot"} description={draft.id} meta={<BotSourceBadges bot={draft} />} action={<ActionButton label="Edit" variant="secondary" size="small" onPress={() => setGroup("identity")} />} />
          <SettingsControlRow leading={<Zap size={15} />} title={draft.model || "No model selected"} description={`${draft.fallback_models?.length ?? 0} fallback model${(draft.fallback_models?.length ?? 0) === 1 ? "" : "s"}`} action={<ActionButton label="Edit" variant="secondary" size="small" onPress={() => setGroup("identity")} />} />
          <SettingsControlRow leading={<Wrench size={15} />} title={`${toolCount} tools, ${draft.skills?.length ?? 0} skills`} description={`${draft.mcp_servers?.length ?? 0} MCP servers · ${delegateCount} delegates`} action={<ActionButton label="Edit" variant="secondary" size="small" onPress={() => setGroup("tools")} />} />
          <SettingsControlRow leading={<Brain size={15} />} title={draft.memory_scheme === "workspace-files" ? "Workspace-files memory" : draft.memory?.enabled ? "Memory enabled" : "Memory not enabled"} description={draft.shared_workspace_id ? `Workspace ${draft.shared_workspace_id}` : "No shared workspace linked"} action={<ActionButton label="Edit" variant="secondary" size="small" onPress={() => setGroup("memory")} />} />
        </div>
      </SectionFrame>

      {(draft.workspace?.cross_workspace_access || draft.api_permissions?.length || draft.system_prompt_workspace_file || draft.persona_from_workspace) && (
        <InfoBanner variant="warning" icon={<Shield size={14} />}>
          This bot has elevated or file-backed configuration. Review workspace access, prompt/persona source files, and API scopes before sharing it broadly.
        </InfoBanner>
      )}

      <SectionFrame title="Recent calls" description="Open traces directly from this bot surface when a correlation id exists." action={<Link to={`/admin/usage?bot_id=${encodeURIComponent(draft.id)}`} className="text-[12px] font-semibold text-accent">Open usage</Link>}>
        {recent.length === 0 ? (
          <EmptyState message="No recent usage is available for this bot in the selected 30-day window." />
        ) : (
          <div className="flex flex-col gap-2">
            {recent.slice(0, 6).map((entry) => (
              <SettingsControlRow
                key={entry.id}
                leading={<MessageSquare size={14} />}
                title={entry.channel_name || entry.channel_id || "Direct call"}
                description={`${new Date(entry.created_at).toLocaleString()} · ${entry.model || "unknown model"} · ${fmtTokens(entry.prompt_tokens + entry.completion_tokens)} tokens · ${fmtCost(entry.cost)}`}
                meta={entry.has_cost_data ? undefined : <QuietPill label="plan" />}
                action={entry.correlation_id ? <TraceActionButton correlationId={entry.correlation_id} size="small" /> : <QuietPill label="no trace" />}
              />
            ))}
          </div>
        )}
      </SectionFrame>
    </div>
  );
}

function IdentitySection({ draft, editorData, isNew, update }: {
  draft: BotConfig;
  editorData: BotEditorData;
  isNew: boolean;
  update: (patch: Partial<BotConfig>) => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <SectionFrame title="Identity" description="Name, ownership, and the model chain used for this bot.">
        <Row>
          <Col>
            <FormRow label="Bot ID" description={isNew ? "Stable route and config id." : "Bot IDs are immutable after creation."}>
              <TextInput value={draft.id || ""} onChangeText={(v) => update({ id: v })} disabled={!isNew} placeholder="qa-bot" />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Name"><TextInput value={draft.name || ""} onChangeText={(v) => update({ name: v })} placeholder="QA Bot" /></FormRow>
          </Col>
        </Row>
        <Row>
          <Col>
            <FormRow label="Primary model">
              <LlmModelDropdown value={draft.model || ""} selectedProviderId={draft.model_provider_id ?? undefined} onChange={(model, providerId) => update({ model, model_provider_id: providerId ?? null })} />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Owner"><UserSelect value={draft.user_id ?? null} onChange={(v) => update({ user_id: v })} /></FormRow>
          </Col>
        </Row>
        <FormRow label="Fallback models">
          <FallbackModelList value={draft.fallback_models ?? []} onChange={(fallback_models) => update({ fallback_models })} />
        </FormRow>
      </SectionFrame>
      <SectionFrame title="Display" description="How this bot appears in Spindrel surfaces and integrations.">
        <Row>
          <Col><FormRow label="Display name"><TextInput value={draft.display_name || ""} onChangeText={(v) => update({ display_name: v || undefined })} placeholder={draft.name} /></FormRow></Col>
          <Col><EmojiAvatarPicker value={draft.avatar_emoji || ""} onChange={(avatar_emoji) => update({ avatar_emoji: avatar_emoji || null })} /></Col>
        </Row>
        <FormRow label="Slack icon emoji" description="Overrides the integration default in Slack when chat:write.customize is available.">
          <TextInput value={draft.integration_config?.slack?.icon_emoji || ""} onChangeText={(v) => {
            const integration_config = { ...(draft.integration_config ?? {}) };
            integration_config.slack = { ...(integration_config.slack || {}), icon_emoji: v || undefined };
            update({ integration_config });
          }} placeholder=":robot_face:" />
        </FormRow>
      </SectionFrame>
      {editorData.model_param_definitions?.length > 0 && (
        <SectionFrame title="Model parameters" description="Overrides for model-specific controls when this provider exposes them.">
          <ModelParamsSection definitions={editorData.model_param_definitions} support={editorData.model_param_support} reasoningCapableModels={editorData.reasoning_capable_models} model={draft.model} params={draft.model_params || {}} onChange={(p) => update({ model_params: p })} />
        </SectionFrame>
      )}
      <SectionFrame title="Agent harness" description="Delegate this bot's turn to an external agent harness instead of the Spindrel RAG loop. See /admin/harnesses.">
        <Row>
          <Col>
            <FormRow label="Runtime" description="Pick a harness to make this bot a window onto Claude Code. Leave blank for a normal Spindrel bot.">
              <SelectInput
                value={draft.harness_runtime ?? ""}
                onChange={(v) => update({ harness_runtime: v || null })}
                options={[
                  { label: "None (Spindrel agent loop)", value: "" },
                  { label: "Claude Code", value: "claude-code" },
                ]}
              />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Workspace path" description="Absolute path on the Spindrel host. The harness runs with this as its cwd.">
              <TextInput
                value={draft.harness_workdir ?? ""}
                onChangeText={(v) => update({ harness_workdir: v || null })}
                placeholder="/data/harness/my-workspace"
                disabled={!draft.harness_runtime}
              />
            </FormRow>
          </Col>
        </Row>
        {draft.harness_runtime && (
          <InfoBanner variant="info">
            This bot is a harness bot. Model, system prompt, skills, tools, memory, and capabilities settings are not used — the harness owns its own context. Auth comes from <code className="text-warning-muted">claude login</code> on the Spindrel host (see /admin/harnesses).
          </InfoBanner>
        )}
        {draft.harness_runtime && draft.harness_session_state && typeof draft.harness_session_state === "object" && (draft.harness_session_state as any).session_id && (
          <div className="text-[12px] text-text-dim">
            Last harness session: <code className="rounded bg-surface-overlay/40 px-1 py-0.5 text-[11px]">{(draft.harness_session_state as any).session_id}</code>
            {typeof (draft.harness_session_state as any).cost_total === "number" && (
              <> · cost so far: ${((draft.harness_session_state as any).cost_total).toFixed(4)}</>
            )}
          </div>
        )}
      </SectionFrame>
    </div>
  );
}

function PromptPersonaSection({ draft, editorData, botId, update }: {
  draft: BotConfig;
  editorData: BotEditorData;
  botId: string | undefined;
  update: (patch: Partial<BotConfig>) => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <SectionFrame title="System prompt" description="Primary instructions injected into every agent turn." action={!draft.system_prompt_workspace_file ? <GenerateButton fieldType="system_prompt" botId={botId} value={draft.system_prompt || ""} onChange={(v) => update({ system_prompt: v })} /> : undefined}>
        {draft.shared_workspace_id && (
          <Toggle value={draft.system_prompt_workspace_file ?? false} onChange={(v) => update({ system_prompt_workspace_file: v, system_prompt_write_protected: v ? draft.system_prompt_write_protected : false })} label="Use workspace file" description={`Source from bots/${draft.id || "bot-id"}/system_prompt.md in the shared workspace.`} />
        )}
        {draft.system_prompt_workspace_file && draft.shared_workspace_id ? (
          <div className="flex flex-col gap-2">
            <SettingsControlRow leading={<FileText size={14} />} title={`bots/${draft.id}/system_prompt.md`} description="The prompt is sourced from this workspace file." meta={<StatusBadge label="workspace file" variant="info" />} action={<Link to={`/admin/workspaces/${draft.shared_workspace_id}`} className="text-[12px] font-semibold text-accent">Open workspace</Link>} />
            <Toggle value={draft.system_prompt_write_protected ?? false} onChange={(v) => update({ system_prompt_write_protected: v })} label="Write-protect this file" description="Prevents this bot from modifying its own prompt file via command tools." />
          </div>
        ) : (
          <LlmPrompt value={draft.system_prompt || ""} onChange={(v) => update({ system_prompt: v })} placeholder="Enter system prompt..." rows={22} fieldType="system_prompt" botId={botId} />
        )}
      </SectionFrame>
      <SectionFrame title="Persona" description="Optional persistent tone and personality, separate from the system prompt.">
        {editorData.bot.persona_from_workspace ? (
          <div className="flex flex-col gap-2">
            <SettingsControlRow leading={<FileText size={14} />} title={`bots/${editorData.bot.id}/persona.md`} description="Persona is sourced from the workspace and shown read-only here." meta={<StatusBadge label="workspace file" variant="info" />} action={editorData.bot.shared_workspace_id ? <Link to={`/admin/workspaces/${editorData.bot.shared_workspace_id}`} className="text-[12px] font-semibold text-accent">Open workspace</Link> : undefined} />
            <SourceTextEditor value={editorData.bot.workspace_persona_content || ""} readOnly language="markdown" minHeight={260} />
          </div>
        ) : (
          <>
            <Toggle value={draft.persona ?? false} onChange={(v) => update({ persona: v })} label="Enable persona" />
            {draft.persona && <LlmPrompt value={draft.persona_content || ""} onChange={(v) => update({ persona_content: v })} placeholder="Describe the bot's personality, tone, and style..." rows={16} fieldType="persona" botId={botId} />}
            {draft.shared_workspace_id && <div className="text-[12px] leading-relaxed text-text-dim">Create <code className="text-warning-muted">bots/{draft.id || "bot-id"}/persona.md</code> in the workspace to manage persona as a file.</div>}
          </>
        )}
      </SectionFrame>
    </div>
  );
}

function ToolsSkillsSection({ editorData, draft, update, setGroup }: {
  editorData: BotEditorData;
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
  setGroup: (group: BotGroupKey) => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <SectionFrame title="Tools" description="Pinned tools, retrieval, MCP, client tools, and result behavior.">
        <ToolsSection editorData={editorData} draft={draft} update={update} />
      </SectionFrame>
      <SectionFrame title="Skills" description="Structured skill enrollments for this bot.">
        <SkillsSection editorData={editorData} draft={draft} update={update} onNavigateToLearning={() => setGroup("memory")} />
        {!!draft.api_permissions?.length && <InfoBanner variant="info">API access tools are available from this bot's {draft.api_permissions.length} API scope{draft.api_permissions.length === 1 ? "" : "s"}.</InfoBanner>}
      </SectionFrame>
      <SectionFrame title="Delegation" description="Allow this bot to delegate work to selected bots.">
        {editorData.all_bots.length === 0 ? (
          <EmptyState message="No other bots are configured." />
        ) : (
          <div className="flex flex-col gap-2">
            <SettingsGroupLabel label="Delegate-to bots" count={editorData.all_bots.length} />
            {editorData.all_bots.map((bot) => {
              const current = (draft.delegation_config?.delegate_bots || draft.delegate_bots || []) as string[];
              const enabled = current.includes(bot.id);
              return (
                <SettingsControlRow key={bot.id} active={enabled} leading={<Bot size={14} />} title={bot.name} description={bot.id} action={<Toggle value={enabled} onChange={() => {
                  const delegation_config = { ...(draft.delegation_config ?? {}) };
                  delegation_config.delegate_bots = enabled ? current.filter((id) => id !== bot.id) : [...current, bot.id];
                  update({ delegation_config });
                }} />} />
              );
            })}
          </div>
        )}
      </SectionFrame>
    </div>
  );
}

function WorkspaceFilesSection({ draft, editorData, globalAttach, update }: {
  draft: BotConfig;
  editorData: BotEditorData;
  globalAttach: { enabled: boolean; model: string; maxChars: string; concurrency: string };
  update: (patch: Partial<BotConfig>) => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <SectionFrame title="Workspace" description="Shared workspace, sandbox, filesystem index, and bot knowledge files.">
        <WorkspaceSection editorData={editorData} draft={draft} update={update} />
      </SectionFrame>
      <SectionFrame title="Attachment summarization" description="Bot-level overrides for incoming attachment preprocessing.">
        <SelectInput value={draft.attachment_summarization_enabled === true ? "true" : draft.attachment_summarization_enabled === false ? "false" : ""} onChange={(v) => update({ attachment_summarization_enabled: v === "true" ? true : v === "false" ? false : null })} options={[{ label: `Inherit (${globalAttach.enabled ? "Enabled" : "Disabled"})`, value: "" }, { label: "Enabled", value: "true" }, { label: "Disabled", value: "false" }]} style={{ maxWidth: 300 }} />
        <Row>
          <Col><FormRow label="Summary model"><LlmModelDropdown value={draft.attachment_summary_model ?? ""} selectedProviderId={draft.attachment_summary_model_provider_id ?? undefined} onChange={(v, pid) => update({ attachment_summary_model: v || undefined, attachment_summary_model_provider_id: pid ?? undefined })} placeholder={globalAttach.model ? `inherit (${globalAttach.model.split("/").pop()})` : "inherit"} allowClear /></FormRow></Col>
          <Col><FormRow label="Text max chars"><TextInput value={String(draft.attachment_text_max_chars ?? "")} onChangeText={(v) => update({ attachment_text_max_chars: v ? parseInt(v, 10) : null })} placeholder={globalAttach.maxChars} type="number" /></FormRow></Col>
        </Row>
        <FormRow label="Summary concurrency"><TextInput value={String(draft.attachment_vision_concurrency ?? "")} onChangeText={(v) => update({ attachment_vision_concurrency: v ? parseInt(v, 10) : null })} placeholder={globalAttach.concurrency} type="number" /></FormRow>
      </SectionFrame>
    </div>
  );
}

function AdvancedSection({ draft, isNew, deleteMutation, showDeleteConfirm, setShowDeleteConfirm, deleteConfirmText, setDeleteConfirmText, deleteChannelWarning, setDeleteChannelWarning, update, onDeleted }: {
  draft: BotConfig;
  isNew: boolean;
  deleteMutation: ReturnType<typeof useDeleteBot>;
  showDeleteConfirm: boolean;
  setShowDeleteConfirm: (value: boolean) => void;
  deleteConfirmText: string;
  setDeleteConfirmText: (value: string) => void;
  deleteChannelWarning: string | null;
  setDeleteChannelWarning: (value: string | null) => void;
  update: (patch: Partial<BotConfig>) => void;
  onDeleted: () => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <SectionFrame title="Runtime defaults" description="Memory scheme, audio input, and history mode.">
        <FormRow label="Workspace-files memory" description="Required for dreaming and workspace-backed memory files."><Toggle value={draft.memory_scheme === "workspace-files"} onChange={(v) => update({ memory_scheme: v ? "workspace-files" : null })} /></FormRow>
        <FormRow label="Audio input"><SelectInput value={draft.audio_input || "transcribe"} onChange={(v) => update({ audio_input: v })} options={[{ label: "transcribe (Whisper STT)", value: "transcribe" }, { label: "native (multimodal)", value: "native" }]} /></FormRow>
        <HistoryModeSection draft={draft} update={update} />
      </SectionFrame>
      {!isNew && draft.source_type !== "system" && (
        <SectionFrame title="Danger zone" description="Permanent destructive actions for this bot.">
          {!showDeleteConfirm ? (
            <SettingsControlRow leading={<Trash2 size={14} />} title="Delete this bot" description="Permanently removes the bot and associated data. Active channels may require force delete confirmation." action={<ActionButton label="Delete bot" variant="danger" size="small" onPress={() => setShowDeleteConfirm(true)} />} />
          ) : (
            <div className="flex flex-col gap-3 rounded-md bg-danger/10 p-4">
              <InfoBanner variant="danger" icon={<AlertTriangle size={14} />}>This action cannot be undone. Type delete to confirm.</InfoBanner>
              <TextInput value={deleteConfirmText} onChangeText={setDeleteConfirmText} placeholder="delete" />
              <div className="flex flex-wrap gap-2">
                <ActionButton label={deleteMutation.isPending ? "Deleting..." : deleteChannelWarning ? "Force delete" : "Permanently delete"} variant="danger" disabled={deleteConfirmText !== "delete" || deleteMutation.isPending} onPress={async () => {
                  try {
                    if (!deleteChannelWarning) {
                      try {
                        await deleteMutation.mutateAsync({ botId: draft.id });
                        onDeleted();
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
                    await deleteMutation.mutateAsync({ botId: draft.id, force: true });
                    onDeleted();
                  } catch (_) {}
                }} />
                <ActionButton label="Cancel" variant="secondary" onPress={() => { setShowDeleteConfirm(false); setDeleteConfirmText(""); setDeleteChannelWarning(null); }} />
              </div>
              {deleteChannelWarning && <InfoBanner variant="danger">{deleteChannelWarning}</InfoBanner>}
              {deleteMutation.isError && !deleteChannelWarning && <div className="text-[12px] text-danger">{deleteMutation.error instanceof Error ? deleteMutation.error.message : "Failed to delete bot"}</div>}
            </div>
          )}
        </SectionFrame>
      )}
      {!isNew && draft.source_type === "system" && <InfoBanner>System bots cannot be deleted.</InfoBanner>}
    </div>
  );
}

const BOT_AVATAR_EMOJI = [
  "🤖", "🧠", "🧭", "🛰️", "📡", "🛠️", "🧰", "🧪",
  "🌱", "🍞", "🏡", "🎛️", "🧵", "📝", "🔍", "⚙️",
  "🗂️", "🎨", "💡", "🔥", "✨", "🧬", "🧮", "🗺️",
];

function EmojiAvatarPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <FormRow label="Bot avatar emoji" description="Shown on the spatial canvas and bot lists.">
      <div className="flex flex-wrap gap-1.5">
        {BOT_AVATAR_EMOJI.map((emoji) => (
          <button
            key={emoji}
            type="button"
            onClick={() => onChange(value === emoji ? "" : emoji)}
            className={`flex h-9 w-9 items-center justify-center rounded-md border text-[18px] transition-colors ${
              value === emoji
                ? "border-accent bg-accent/12"
                : "border-input-border bg-input hover:border-accent/50"
            }`}
            aria-label={`Use ${emoji} as bot avatar`}
          >
            {emoji}
          </button>
        ))}
      </div>
    </FormRow>
  );
}

export default function BotEditorScreen() {
  const { botId } = useParams<{ botId: string }>();
  const isNew = botId === "new";
  const navigate = useNavigate();
  const location = useLocation();
  const { width: windowWidth } = useWindowSize();
  const isMobile = windowWidth < MOBILE_NAV_BREAKPOINT;
  const { data: editorData, isLoading } = useBotEditorData(botId);
  const updateMutation = useUpdateBot(isNew ? undefined : botId);
  const createMutation = useCreateBot();
  const deleteMutation = useDeleteBot();
  const saveMutation = isNew ? createMutation : updateMutation;
  const { data: usageSummary } = useUsageSummary({ after: "30d", bot_id: isNew ? undefined : botId });
  const { data: usageLogs } = useUsageLogs({ after: "30d", bot_id: isNew ? undefined : botId, page_size: 6 });
  const { data: settingsData } = useSettings();
  const [activeGroup, setActiveGroupState] = useState<BotGroupKey>(() => activeFromHash(location.hash));
  const [filter, setFilter] = useState("");
  const [draft, setDraft] = useState<BotConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleteChannelWarning, setDeleteChannelWarning] = useState<string | null>(null);
  const [loadedBotId, setLoadedBotId] = useState<string | undefined>(undefined);
  const enrichRecentPage = useUIStore((s) => s.enrichRecentPage);
  const recentPages = useUIStore((s) => s.recentPages);

  const backTarget = useMemo(() => {
    const stateBack = (location.state as { backTo?: string } | null)?.backTo;
    if (stateBack) return stateBack;
    const currentKey = `${location.pathname}${location.search}`;
    const previous = recentPages.find((page) => {
      const [pathAndSearch] = page.href.split("#", 1);
      return pathAndSearch && pathAndSearch !== currentKey;
    });
    return previous?.href ?? "/admin/bots";
  }, [location.pathname, location.search, location.state, recentPages]);

  useEffect(() => {
    if (editorData?.bot?.name) enrichRecentPage(buildRecentHref(location.pathname, location.search, location.hash), editorData.bot.name);
  }, [editorData?.bot?.name, location.pathname, location.search, location.hash, enrichRecentPage]);

  useEffect(() => setActiveGroupState(activeFromHash(location.hash)), [location.hash]);

  const setActiveGroup = useCallback((group: BotGroupKey) => {
    setActiveGroupState(group);
    navigate({ hash: group }, { replace: true });
  }, [navigate]);

  useEffect(() => {
    if (editorData?.bot && loadedBotId !== botId) {
      setDraft({ ...editorData.bot });
      setDirty(isNew);
      setSaved(false);
      setFilter("");
      setShowDeleteConfirm(false);
      setDeleteConfirmText("");
      setDeleteChannelWarning(null);
      setLoadedBotId(botId);
    }
  }, [botId, editorData, isNew, loadedBotId]);

  const globalAttach = useMemo(() => {
    if (!settingsData) return { enabled: true, model: "", maxChars: "40000", concurrency: "3" };
    const all = settingsData.groups.flatMap((g) => g.settings);
    const get = (key: string) => all.find((s) => s.key === key);
    return {
      enabled: Boolean(get("ATTACHMENT_SUMMARY_ENABLED")?.value ?? true),
      model: String(get("ATTACHMENT_SUMMARY_MODEL")?.value ?? ""),
      maxChars: String(get("ATTACHMENT_TEXT_MAX_CHARS")?.value ?? "40000"),
      concurrency: String(get("ATTACHMENT_VISION_CONCURRENCY")?.value ?? "3"),
    };
  }, [settingsData]);

  const update = useCallback((patch: Partial<BotConfig>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
    setDirty(true);
    setSaved(false);
  }, []);

  const handleSave = useCallback(async () => {
    if (!draft || !editorData) return;
    const payload = buildBotSavePayload({ draft, original: editorData.bot, isNew });
    try {
      if (isNew) {
        const id = typeof payload.id === "string" ? payload.id : "";
        const name = typeof payload.name === "string" ? payload.name : "";
        const model = typeof payload.model === "string" ? payload.model : "";
        if (!id || !name || !model) return;
        await createMutation.mutateAsync({ ...payload, id, name, model } as Partial<BotConfig> & { id: string; name: string; model: string });
        navigate(`/admin/bots/${id}`);
      } else {
        await updateMutation.mutateAsync(payload as Partial<BotConfig>);
      }
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (_) {}
  }, [createMutation, draft, editorData, isNew, navigate, updateMutation]);

  const saveErrorMessage = useMemo(() => {
    const err = saveMutation.error;
    if (!err) return null;
    if (err instanceof ApiError) return err.detail || err.message;
    return (err as Error)?.message || "Failed to save";
  }, [saveMutation.error]);

  const saveTone = saveMutation.isPending ? "pending" : saveMutation.isError ? "error" : saved ? "saved" : dirty ? "dirty" : "idle";
  const saveLabel = saveMutation.isPending ? "Saving" : saveMutation.isError ? "Save failed" : saved ? "Saved" : dirty ? "Unsaved" : "";

  const matchingGroups = useMemo(() => {
    if (!filter.trim()) return new Set<BotGroupKey>(BOT_GROUPS.map((g) => g.key));
    const q = filter.toLowerCase();
    const keywords: Record<BotGroupKey, string[]> = {
      overview: ["overview", "usage", "trace", "status", "summary"],
      identity: ["identity", "id", "name", "display", "avatar", "emoji", "slack", "model", "owner", "fallback", "parameter"],
      prompt: ["prompt", "persona", "instruction", "tone", "workspace file"],
      tools: ["tool", "skill", "mcp", "client", "delegate", "retrieval", "discovery"],
      memory: ["memory", "learning", "hygiene", "knowledge", "dreaming", "review"],
      workspace: ["workspace", "file", "attachment", "sandbox", "docker", "host", "index"],
      access: ["permission", "grant", "api", "policy", "hook", "automation"],
      advanced: ["audio", "history", "delete", "danger"],
    };
    return new Set<BotGroupKey>(Object.entries(keywords).filter(([, words]) => words.some((word) => word.includes(q) || q.includes(word))).map(([key]) => key as BotGroupKey));
  }, [filter]);

  if (isLoading || !editorData || !draft) {
    return <div className="flex flex-1 items-center justify-center bg-surface"><Spinner size={18} /></div>;
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="detail"
        parentLabel="Bots"
        backTo={backTarget}
        title={isNew ? "New Bot" : draft.name}
        subtitle={isNew ? "Create a bot profile" : draft.id}
        right={
          <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
            {!isMobile && <SettingsSearchBox value={filter} onChange={setFilter} placeholder="Find setting..." className="w-48" />}
            <SaveStatusPill tone={saveTone} label={saveLabel} />
            <ActionButton label={saveMutation.isPending ? "Saving" : isNew ? "Create" : "Save"} icon={<Save size={13} />} disabled={!dirty || saveMutation.isPending} onPress={handleSave} />
          </div>
        }
      />
      {isMobile && <div className="border-b border-surface-raised/60 px-4 py-2"><SettingsSearchBox value={filter} onChange={setFilter} placeholder="Find setting..." /></div>}
      {saveMutation.isError && <div className="bg-danger/10 px-4 py-2 text-[12px] text-danger">{saveErrorMessage}</div>}
      {isMobile && <SectionNav active={activeGroup} onSelect={setActiveGroup} filter={filter} matchingSections={matchingGroups} isMobile />}
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        {!isMobile && <SectionNav active={activeGroup} onSelect={setActiveGroup} filter={filter} matchingSections={matchingGroups} isMobile={false} />}
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-5xl flex-col gap-7 px-4 py-5 md:px-6">
            {activeGroup === "overview" && <OverviewSection draft={draft} usage={usageSummary} logs={usageLogs} setGroup={setActiveGroup} />}
            {activeGroup === "identity" && <IdentitySection draft={draft} editorData={editorData} isNew={isNew} update={update} />}
            {activeGroup === "prompt" && <PromptPersonaSection draft={draft} editorData={editorData} botId={botId} update={update} />}
            {activeGroup === "tools" && <ToolsSkillsSection editorData={editorData} draft={draft} update={update} setGroup={setActiveGroup} />}
            {activeGroup === "memory" && (
              <div className="flex flex-col gap-6">
                <SectionFrame title="Memory" description="Memory configuration and maintenance jobs for this bot."><MemorySection draft={draft} update={update} botId={botId} /></SectionFrame>
                {draft.id && <SectionFrame title="Learning" description="Bot-authored skills and knowledge review."><LearningSection botId={draft.id} /></SectionFrame>}
              </div>
            )}
            {activeGroup === "workspace" && <WorkspaceFilesSection draft={draft} editorData={editorData} globalAttach={globalAttach} update={update} />}
            {activeGroup === "access" && (
              <div className="flex flex-col gap-6">
                <SectionFrame title="API permissions" description="Direct API scopes available to this bot."><BotPermissionsSection permissions={draft.api_permissions || []} onChange={(p) => update({ api_permissions: p })} /></SectionFrame>
                <SectionFrame title="Grants" description="User and access grants for this bot."><GrantsSection botId={isNew ? undefined : draft.id} ownerUserId={draft.user_id} /></SectionFrame>
                {draft.id && (
                  <>
                    <SectionFrame title="Tool policies" description="Approval and policy rules scoped to this bot."><BotToolPoliciesSection botId={draft.id} /></SectionFrame>
                    <SectionFrame title="Hooks" description="Automation hooks scoped to this bot."><BotHooksSection botId={draft.id} /></SectionFrame>
                  </>
                )}
              </div>
            )}
            {activeGroup === "advanced" && <AdvancedSection draft={draft} isNew={isNew} deleteMutation={deleteMutation} showDeleteConfirm={showDeleteConfirm} setShowDeleteConfirm={setShowDeleteConfirm} deleteConfirmText={deleteConfirmText} setDeleteConfirmText={setDeleteConfirmText} deleteChannelWarning={deleteChannelWarning} setDeleteChannelWarning={setDeleteChannelWarning} update={update} onDeleted={() => navigate("/admin/bots", { replace: true })} />}
          </div>
        </main>
      </div>
    </div>
  );
}
