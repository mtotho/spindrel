import { useCallback, useMemo, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { ExternalLink, FolderKanban, Terminal, Trash2, AlertTriangle, X } from "lucide-react";

import { useIsMobile } from "@/src/hooks/useIsMobile";
import { useDeleteChannel, useChannelCategories } from "@/src/api/hooks/useChannels";
import { useProjects } from "@/src/api/hooks/useProjects";
import { useWidgetThemes } from "@/src/api/hooks/useWidgetThemes";
import { useAdminUsers } from "@/src/api/hooks/useAdminUsers";
import { useIsAdmin } from "@/src/hooks/useScope";
import { useAuthStore } from "@/src/stores/auth";
import { useToolResultCompact } from "@/src/stores/toolResultPref";
import { useSessionResumePrefs } from "@/src/stores/sessionResumePref";
import {
  Section,
  FormRow,
  TextInput,
  SelectInput,
  Toggle,
  Row,
  Col,
} from "@/src/components/shared/FormControls";
import { ActionButton, InfoBanner, QuietPill, SettingsControlRow } from "@/src/components/shared/SettingsControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { UserSelect } from "@/src/components/shared/UserSelect";
import { BotPicker } from "@/src/components/shared/BotPicker";
import type { ChannelSettings } from "@/src/types/api";

function TagEditor({
  tags,
  onChange,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
}) {
  const [input, setInput] = useState("");

  const addTag = (raw: string) => {
    const tag = raw.trim().toLowerCase();
    if (tag && !tags.includes(tag)) onChange([...tags, tag]);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(input);
    }
    if (e.key === "Backspace" && !input && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  };

  return (
    <div className="flex flex-row flex-wrap items-center gap-2 min-h-[40px]">
      {tags.map((tag) => (
        <div
          key={tag}
          className="inline-flex items-center gap-1 rounded-full bg-surface-overlay px-2.5 py-0.5 text-[11px] text-text-muted"
        >
          <span>{tag}</span>
          <button
            type="button"
            onClick={() => onChange(tags.filter((x) => x !== tag))}
            aria-label={`Remove tag ${tag}`}
            className="inline-flex items-center justify-center w-4 h-4 rounded-full border-none bg-transparent p-0 text-text-dim hover:text-text transition-colors"
          >
            <X size={11} />
          </button>
        </div>
      ))}
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          if (input.trim()) addTag(input);
        }}
        placeholder={tags.length === 0 ? "Add tags..." : ""}
        className="flex-1 min-w-[80px] border-none outline-none bg-transparent text-text text-xs py-1"
      />
    </div>
  );
}

function DangerZoneSection({
  form,
  channelId,
}: {
  form: Partial<ChannelSettings>;
  channelId: string;
}) {
  const navigate = useNavigate();
  const deleteMutation = useDeleteChannel();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  const isAdmin = useIsAdmin();
  const currentUserId = useAuthStore((s) => s.user?.id);
  const isOwner = !!form.user_id && form.user_id === currentUserId;
  const canMutateOwnership = isAdmin || isOwner;

  const handleDelete = useCallback(async () => {
    await deleteMutation.mutateAsync(channelId);
    navigate("/channels", { replace: true });
  }, [channelId, deleteMutation, navigate]);

  if (!canMutateOwnership) return null;

  return (
    <Section
      title="Danger Zone"
      description="Destructive channel actions live here."
    >
      <InfoBanner variant="danger">
        {!showDeleteConfirm ? (
          <div className="flex flex-row items-center justify-between flex-wrap gap-3">
            <div className="flex-1 min-w-[180px]">
              <span className="block text-[13px] font-semibold text-text">Delete this channel</span>
              <span className="block text-[11px] text-text-muted mt-0.5 leading-snug">
                Permanently removes the channel, its integrations, and heartbeat config. Sessions and tasks will be unlinked.
              </span>
            </div>
            <ActionButton
              label="Delete Channel"
              onPress={() => setShowDeleteConfirm(true)}
              variant="danger"
              size="small"
              icon={<Trash2 size={13} />}
            />
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-row items-center gap-2 text-danger">
              <AlertTriangle size={16} className="text-danger" />
              <span className="text-xs font-semibold text-danger">
                This action cannot be undone.
              </span>
            </div>
            <span className="text-xs text-text-muted">
              Type <span className="font-mono font-semibold text-danger">delete</span> to confirm:
            </span>
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="delete"
              className={
                "rounded-md bg-input px-3 py-2 text-[13px] text-text outline-none border "
                + (deleteConfirmText === "delete"
                  ? "border-danger/40"
                  : "border-surface-border")
              }
            />
            <div className="flex flex-row flex-wrap gap-2">
              <ActionButton
                label={deleteMutation.isPending ? "Deleting..." : "Permanently Delete"}
                onPress={handleDelete}
                disabled={deleteConfirmText !== "delete" || deleteMutation.isPending}
                variant="danger"
                size="small"
                icon={<Trash2 size={13} />}
              />
              <ActionButton
                label="Cancel"
                onPress={() => {
                  setShowDeleteConfirm(false);
                  setDeleteConfirmText("");
                }}
                variant="secondary"
                size="small"
              />
            </div>
            {deleteMutation.isError && (
              <span className="text-[11px] text-danger">
                {deleteMutation.error instanceof Error ? deleteMutation.error.message : "Failed to delete channel"}
              </span>
            )}
          </div>
        )}
      </InfoBanner>
    </Section>
  );
}

export function ChannelIdentitySection({
  form,
  patch,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
}) {
  const isMobile = useIsMobile();
  const { data: existingCategories } = useChannelCategories();

  const categoryValue = (form.category as string | undefined | null) ?? "";
  const categorySuggestions = (existingCategories ?? []).filter(
    (c) => c.toLowerCase().includes(categoryValue.toLowerCase()) && c !== categoryValue,
  );

  return (
    <Section title="Channel">
      <Row stack={isMobile}>
        <Col minWidth={isMobile ? 0 : 220}>
          <FormRow label="Display Name" description="Label shown in the sidebar. Does not affect routing.">
            <TextInput
              value={form.name ?? ""}
              onChangeText={(v) => patch("name", v)}
              placeholder="Channel name"
            />
          </FormRow>
        </Col>
        <Col minWidth={isMobile ? 0 : 220}>
          <FormRow label="Category" description="Groups channels in the sidebar.">
            <TextInput
              value={categoryValue}
              onChangeText={(v) => patch("category", (v || undefined) as ChannelSettings["category"])}
              placeholder="e.g. Work, Personal"
            />
            {categorySuggestions.length > 0 && categoryValue.length > 0 && (
              <div className="flex flex-row flex-wrap gap-1 mt-1">
                {categorySuggestions.slice(0, 4).map((cat) => (
                  <button
                    type="button"
                    key={cat}
                    onClick={() => patch("category", cat as ChannelSettings["category"])}
                    className="rounded-full bg-surface-overlay px-2 py-0.5 text-[10px] text-text-muted hover:bg-surface-overlay/80 transition-colors"
                  >
                    {cat}
                  </button>
                ))}
              </div>
            )}
          </FormRow>
        </Col>
      </Row>

      <FormRow label="Tags" description="Categorize with tags. Press Enter or comma to add.">
        <TagEditor
          tags={(form.tags as string[]) ?? []}
          onChange={(v) => patch("tags", v as ChannelSettings["tags"])}
        />
      </FormRow>
    </Section>
  );
}

export function PrivacyOwnershipSection({
  form,
  patch,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
}) {
  const isAdmin = useIsAdmin();
  const currentUserId = useAuthStore((s) => s.user?.id);
  const isOwner = !!form.user_id && form.user_id === currentUserId;
  const { data: users } = useAdminUsers(isAdmin);
  const ownerName = useMemo(() => {
    if (!form.user_id) return null;
    const user = users?.find((x) => x.id === form.user_id);
    return user ? user.display_name : null;
  }, [form.user_id, users]);

  return (
    <Section title="Privacy">
      <Toggle
        value={form.private ?? false}
        onChange={(v) => patch("private", v as ChannelSettings["private"])}
        label="Private channel"
        description="Only the owner and admins can see this channel."
      />
      {isAdmin ? (
        <FormRow label="Owner" description="Set who owns this channel. Admins can reassign; non-admins own what they create.">
          <UserSelect
            value={form.user_id ?? null}
            onChange={(v) => patch("user_id", (v ?? undefined) as ChannelSettings["user_id"])}
          />
        </FormRow>
      ) : form.user_id ? (
        <FormRow label="Owner">
          <div className="text-xs text-text-muted">
            {ownerName ?? (isOwner ? "You" : form.user_id)}
          </div>
        </FormRow>
      ) : null}
    </Section>
  );
}

export function AgentIdentitySection({
  form,
  patch,
  bots,
  settings,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  bots: any[] | undefined;
  settings: ChannelSettings;
}) {
  return (
    <Section title="Agent">
      <FormRow label="Bot" description="Select which bot owns this channel conversation.">
        <BotPicker
          value={form.bot_id ?? ""}
          onChange={(v) => patch("bot_id", v as ChannelSettings["bot_id"])}
          bots={bots ?? []}
          placeholder="Select bot..."
        />
      </FormRow>
      {form.bot_id && settings.bot_id && form.bot_id !== settings.bot_id && (
        <InfoBanner variant="warning" icon={<AlertTriangle size={14} className="text-warning-muted" />}>
          <strong>Switching bots.</strong> Existing conversation history sections belong to the previous bot&apos;s workspace and won&apos;t be accessible to the new bot. To rebuild history for the new bot, go to <strong>Memory</strong> and re-run <strong>Backfill</strong> after saving.
        </InfoBanner>
      )}
    </Section>
  );
}

export function ChannelPromptSection({
  form,
  patch,
  workspaceId,
  settings,
  channelId,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  workspaceId?: string | null;
  settings: ChannelSettings;
  channelId: string;
}) {
  return (
    <Section title="Channel Prompt" description="A short prompt injected as a system message right before each user message. Useful for per-channel instructions or reminders.">
      <WorkspaceFilePrompt
        workspaceId={form.channel_prompt_workspace_id ?? workspaceId}
        filePath={form.channel_prompt_workspace_file_path ?? null}
        onLink={(path, wsId) => {
          patch("channel_prompt_workspace_file_path", path as ChannelSettings["channel_prompt_workspace_file_path"]);
          patch("channel_prompt_workspace_id", wsId as ChannelSettings["channel_prompt_workspace_id"]);
        }}
        onUnlink={() => {
          patch("channel_prompt_workspace_file_path", undefined as ChannelSettings["channel_prompt_workspace_file_path"]);
          patch("channel_prompt_workspace_id", undefined as ChannelSettings["channel_prompt_workspace_id"]);
        }}
      />
      {!form.channel_prompt_workspace_file_path && (
        <LlmPrompt
          value={form.channel_prompt ?? ""}
          onChange={(v) => patch("channel_prompt", (v || undefined) as ChannelSettings["channel_prompt"])}
          label="Channel Prompt"
          placeholder="Leave blank for no channel-level prompt..."
          helpText="Inserted after all context layers but before the user's message."
          rows={4}
          fieldType="channel_prompt"
          botId={settings.bot_id}
          channelId={channelId}
        />
      )}
    </Section>
  );
}

export function MessageRoutingSection({
  form,
  patch,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
}) {
  return (
    <Section title="Message Routing" description="Controls active replies. Messages that do not trigger a reply can still be stored as passive channel context.">
      <Toggle
        value={form.require_mention ?? true}
        onChange={(v) => patch("require_mention", v as ChannelSettings["require_mention"])}
        label="Require @mention"
        description="Only @mentions or wake words create active turns. Other messages are stored as passive context and may feed memory/learning when Passive memory is on."
      />
      <Toggle
        value={form.allow_bot_messages ?? false}
        onChange={(v) => patch("allow_bot_messages", v as ChannelSettings["allow_bot_messages"])}
        label="Allow bot messages"
        description="Let messages from other bots and webhooks trigger active turns. Passive storage rules still apply to non-triggering messages."
      />
    </Section>
  );
}

export function ModelOverrideSection({
  form,
  patch,
  bots,
  settings,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  bots: any[] | undefined;
  settings: ChannelSettings;
}) {
  return (
    <Section title="Model Override" description="Override the primary bot's default model for this channel. Leave empty to inherit.">
      <FormRow label="Model" description="Active turns for the primary/default bot use this model instead of the bot default. Member bots can have their own override in Participants.">
        <LlmModelDropdown
          value={form.model_override ?? ""}
          selectedProviderId={form.model_provider_id_override}
          onChange={(v, providerId) => {
            patch("model_override", (v || null) as ChannelSettings["model_override"]);
            patch("model_provider_id_override", (v ? (providerId ?? null) : null) as ChannelSettings["model_provider_id_override"]);
          }}
          placeholder={`inherit (${bots?.find((b) => b.id === settings.bot_id)?.model ?? "bot default"})`}
          allowClear
        />
      </FormRow>
      <FormRow label="Fallback Models" description="Ordered list tried when primary fails. Empty inherits from bot. Global list is appended as a catch-all.">
        <FallbackModelList
          value={form.fallback_models ?? []}
          onChange={(v) => patch("fallback_models", v as ChannelSettings["fallback_models"])}
        />
      </FormRow>
    </Section>
  );
}

export function AgentBehaviorSection({
  form,
  patch,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
}) {
  const isMobile = useIsMobile();
  const nativePolicy = (
    form.native_context_policy && form.native_context_policy !== "default"
      ? form.native_context_policy
      : form.effective_native_context_policy
  ) ?? "standard";
  const workspaceRagEffective = nativePolicy !== "lean";

  return (
    <Section title="Behavior">
      <Toggle
        value={form.passive_memory ?? true}
        onChange={(v) => patch("passive_memory", v as ChannelSettings["passive_memory"])}
        label="Passive memory"
        description="Include non-triggering channel messages in compaction and dreaming/learning. This can apply to member bots too because they are channel participants."
      />
      <Toggle
        value={form.workspace_rag ?? true}
        onChange={(v) => patch("workspace_rag", v as ChannelSettings["workspace_rag"])}
        label="Workspace RAG gate"
        description={
          workspaceRagEffective
            ? "Allows the active native context policy to auto-inject relevant workspace files. Turn this off to suppress workspace RAG even in Standard or Rich."
            : "Currently inactive because the Lean native context policy disables workspace RAG. Switch the History tab policy to Standard or Rich to use this gate."
        }
      />
      {!workspaceRagEffective && (
        <InfoBanner variant="info">
          Workspace RAG is a lower-level gate. Lean policy wins over it so normal chat stays on-demand.
        </InfoBanner>
      )}
      <Toggle
        value={form.pinned_widget_context_enabled ?? true}
        onChange={(v) => patch("pinned_widget_context_enabled", v as ChannelSettings["pinned_widget_context_enabled"])}
        label="Pinned widget context"
        description="Allow pinned channel widgets to contribute summaries and action hints to chat context."
      />
      <FormRow label="Integration thinking display" description="How intermediate thinking is shown in integrations like Slack or Discord. Web chat uses the built-in transcript layout.">
        <SelectInput
          value={form.thinking_display ?? "append"}
          onChange={(v) => patch("thinking_display", v as ChannelSettings["thinking_display"])}
          options={[
            { label: "Hidden (just 'thinking...')", value: "hidden" },
            { label: "Replace (single updating message)", value: "replace" },
            { label: "Append all", value: "append" },
          ]}
        />
      </FormRow>
      <FormRow label="Tool output" description="How tool-call results are rendered in integrations. The web UI always shows the full widget.">
        <SelectInput
          value={form.tool_output_display ?? "compact"}
          onChange={(v) => patch("tool_output_display", v as ChannelSettings["tool_output_display"])}
          options={[
            { label: "Compact (one-line badge)", value: "compact" },
            { label: "Full (rich Block Kit)", value: "full" },
            { label: "Hidden", value: "none" },
          ]}
        />
      </FormRow>
      <Row stack={isMobile}>
        <Col minWidth={isMobile ? 0 : 200}>
          <FormRow label="Max iterations">
            <TextInput
              value={form.max_iterations?.toString() ?? ""}
              onChangeText={(v) => {
                const n = parseInt(v, 10);
                patch("max_iterations", (Number.isNaN(n) ? undefined : n) as ChannelSettings["max_iterations"]);
              }}
              placeholder="default"
              type="number"
            />
          </FormRow>
        </Col>
        <Col minWidth={isMobile ? 0 : 200}>
          <FormRow label="Max task run time (seconds)">
            <TextInput
              value={form.task_max_run_seconds?.toString() ?? ""}
              onChangeText={(v) => {
                const n = parseInt(v, 10);
                patch("task_max_run_seconds", (Number.isNaN(n) ? undefined : n) as ChannelSettings["task_max_run_seconds"]);
              }}
              placeholder="1200 (default)"
              type="number"
            />
          </FormRow>
        </Col>
      </Row>
    </Section>
  );
}

export function PresentationSection({
  form,
  patch,
  channelId,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
}) {
  const isMobile = useIsMobile();
  const [compactToolResults, setCompactToolResults] = useToolResultCompact(channelId);
  const sessionResumePrefs = useSessionResumePrefs(channelId, null, null);
  const { data: widgetThemes } = useWidgetThemes();

  return (
    <>
      <Section title="Chat Presentation">
        <FormRow label="Chat theme" description="Choose how this channel's chat feed and composer are presented.">
          <SelectInput
            value={(form.chat_mode ?? "default") as string}
            onChange={(v) => patch("chat_mode", v as ChannelSettings["chat_mode"])}
            options={[
              { label: "Default", value: "default" },
              { label: "Terminal", value: "terminal" },
            ]}
          />
        </FormRow>
        <FormRow
          label="Chat screen layout"
          description="Controls whether chat includes the channel workbench. Chat shelf artifacts are chosen explicitly from the workbench."
        >
          <SelectInput
            value={(form.layout_mode ?? "full") as string}
            onChange={(v) => patch("layout_mode", v as ChannelSettings["layout_mode"])}
            options={[
              { label: "Workbench + chat", value: "full" },
              { label: "Workbench + chat, compact", value: "rail-header-chat" },
              { label: "Chat with workbench", value: "rail-chat" },
              { label: "Dashboard only — chat replaced by dashboard link", value: "dashboard-only" },
            ]}
          />
        </FormRow>
        <Toggle
          value={sessionResumePrefs.globalEnabled}
          onChange={sessionResumePrefs.setGlobalEnabled}
          label="Session resume cards"
          description="Local browser preference. Show a compact session info card above the composer when a chat has been idle for two hours."
        />
        <Toggle
          value={sessionResumePrefs.channelEnabled}
          onChange={sessionResumePrefs.setChannelEnabled}
          label="Resume cards in this channel"
          description="Local channel override for the idle resume card. Re-enable it here if it was hidden from a card menu."
        />
        <FormRow
          label="Plan control"
          description="Controls the always-visible plan button in the composer. The /plan command remains available."
        >
          <SelectInput
            value={(form.plan_mode_control ?? "auto") as string}
            onChange={(v) => patch("plan_mode_control", v as ChannelSettings["plan_mode_control"])}
            options={[
              { label: "Auto — hidden unless this is a harness channel", value: "auto" },
              { label: "Show", value: "show" },
              { label: "Hide", value: "hide" },
            ]}
          />
        </FormRow>
      </Section>

      <Section title="Dashboard Presentation">
        <Row stack={isMobile}>
          <Col minWidth={isMobile ? 0 : 240}>
            <FormRow
              label="Widget theme"
              description="Choose the shared HTML widget SDK theme for this channel. Leave on Default to inherit the global widget theme."
            >
              <SelectInput
                value={(form.widget_theme_ref ?? "builtin/default") as string}
                onChange={(v) => patch("widget_theme_ref", (v === "builtin/default" ? null : v) as ChannelSettings["widget_theme_ref"])}
                options={[
                  { label: "Default (inherit global)", value: "builtin/default" },
                  ...((widgetThemes ?? [])
                    .filter((theme) => theme.ref !== "builtin/default")
                    .map((theme) => ({
                      label: theme.is_builtin ? `${theme.name} (builtin)` : theme.name,
                      value: theme.ref,
                    }))),
                ]}
              />
            </FormRow>
          </Col>
        </Row>
        <Toggle
          value={compactToolResults}
          onChange={setCompactToolResults}
          label="Compact tool results"
          description="Local chat preference. Collapse tool-call output to a one-line badge in this channel's chat."
        />
      </Section>
    </>
  );
}

export function PipelineModeSection({
  form,
  patch,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
}) {
  return (
    <Section title="Pipeline Visibility" noDivider>
      <FormRow
        label="Pipeline mode"
        description="Controls whether the pipeline launchpad and Findings panel are visible in this channel."
      >
        <SelectInput
          value={(form.pipeline_mode ?? "auto") as string}
          onChange={(v) => patch("pipeline_mode", v as ChannelSettings["pipeline_mode"])}
          options={[
            { label: "Auto — show when pipelines are subscribed", value: "auto" },
            { label: "Always on", value: "on" },
            { label: "Off", value: "off" },
          ]}
        />
      </FormRow>
    </Section>
  );
}

export function ChannelMetadataFooter({
  settings,
}: {
  settings: ChannelSettings;
}) {
  return (
    <div className="flex flex-row flex-wrap gap-2 text-[11px] text-text-dim opacity-40">
      <span>ID: {settings.id}</span>
      {settings.client_id && <span>client_id: {settings.client_id}</span>}
      {settings.integration && <span>integration: {settings.integration}</span>}
    </div>
  );
}

export function ChannelTabSections({
  form,
  patch,
  channelId,
  settings,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
  settings: ChannelSettings;
}) {
  return (
    <>
      <ChannelIdentitySection form={form} patch={patch} />
      <PrivacyOwnershipSection form={form} patch={patch} />
      <ChannelMetadataFooter settings={settings} />
      <DangerZoneSection form={form} channelId={channelId} />
    </>
  );
}

function ProjectSection({
  form,
  patch,
  workspaceId,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  workspaceId?: string | null;
}) {
  const { data: projects } = useProjects();
  const selectedProject = projects?.find((project) => project.id === form.project_id) ?? form.project ?? null;
  const projectOptions = useMemo(() => {
    const rows = (projects ?? []).map((project) => ({
      label: `${project.name} · /${project.root_path}`,
      value: project.id,
    }));
    if (selectedProject && !rows.some((project) => project.value === selectedProject.id)) {
      rows.push({
        label: `${selectedProject.name} · /${selectedProject.root_path}`,
        value: selectedProject.id,
      });
    }
    return [
      { label: "No Project", value: "" },
      ...rows,
    ];
  }, [projects, selectedProject]);
  const projectPath = (selectedProject?.root_path ?? "").replace(/^\/+/, "");
  const effectiveWorkspaceId = selectedProject?.workspace_id ?? workspaceId ?? null;
  const terminalHref = effectiveWorkspaceId && projectPath
    ? `/admin/terminal?cwd=${encodeURIComponent(`workspace://${effectiveWorkspaceId}/${projectPath}`)}`
    : null;
  return (
    <Section
      title="Project"
      description="Optional shared Project root used by this channel's file browser, bot working surface, terminal, and harness CWD."
    >
      <div data-testid="project-workspace-channel-picker">
        <FormRow
          label="Primary Project"
          description="Choose a Project to share the same working root across channels."
        >
          <SelectInput
            value={form.project_id ?? ""}
            onChange={(value) => patch("project_id", (value || null) as ChannelSettings["project_id"])}
            options={projectOptions}
          />
        </FormRow>
      </div>
      <div data-testid="project-workspace-channel-summary" className="flex flex-col gap-2">
        {projectPath ? (
          <SettingsControlRow
            leading={<FolderKanban size={14} />}
            title={selectedProject?.name ?? "Project root"}
            description={
              <>
                File explorer, terminal, search, and run cwd use <span className="font-mono">/{projectPath}</span>. Bot memory uses the dedicated memory tool.
              </>
            }
            meta={
              <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
                <QuietPill label="cwd" />
                <QuietPill label="memory separate" maxWidthClass="max-w-none" />
              </span>
            }
            action={
              <div className="flex flex-wrap items-center justify-end gap-1">
                {selectedProject && (
                  <Link to={`/admin/projects/${selectedProject.id}`} className="inline-flex min-h-[30px] items-center gap-1.5 rounded-md px-2 text-[12px] font-semibold text-accent no-underline transition-colors hover:bg-accent/[0.08]">
                    <FolderKanban size={12} />
                    Open Project
                  </Link>
                )}
                {effectiveWorkspaceId && (
                  <Link
                    to={`/admin/workspaces/${effectiveWorkspaceId}/files?path=${encodeURIComponent(`/${projectPath}`)}`}
                    className="inline-flex min-h-[30px] items-center gap-1.5 rounded-md px-2 text-[12px] font-semibold text-text-muted no-underline transition-colors hover:bg-surface-overlay/50 hover:text-text"
                  >
                    <ExternalLink size={12} />
                    Open location
                  </Link>
                )}
                {terminalHref && (
                  <Link to={terminalHref} className="inline-flex min-h-[30px] items-center gap-1.5 rounded-md px-2 text-[12px] font-semibold text-text-muted no-underline transition-colors hover:bg-surface-overlay/50 hover:text-text">
                    <Terminal size={12} />
                    Open terminal
                  </Link>
                )}
              </div>
            }
          />
        ) : (
          <SettingsControlRow
            leading={<FolderKanban size={14} />}
            title="No Project selected"
            description="This channel uses its normal channel workspace and bot workspace defaults."
            meta={<QuietPill label="channel workspace" maxWidthClass="max-w-none" />}
          />
        )}
      </div>
    </Section>
  );
}

export function AgentTabSections({
  form,
  patch,
  bots,
  settings,
  workspaceId,
  channelId,
  currentBot,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  bots: any[] | undefined;
  settings: ChannelSettings;
  workspaceId?: string | null;
  channelId: string;
  currentBot?: any;
}) {
  const harnessRuntime = currentBot?.harness_runtime as string | undefined;
  if (harnessRuntime) {
    return (
      <>
        <AgentIdentitySection form={form} patch={patch} bots={bots} settings={settings} />
        <Section
          title="Harness Runtime"
          description="This channel's primary bot runs an external agent harness. Session-scoped runtime controls live in the chat header."
        >
          <div className="rounded-md bg-surface-overlay p-3 text-xs text-text-muted">
            <div className="font-semibold text-text mb-1">
              {currentBot?.name || settings.bot_id || "Harness bot"} · {harnessRuntime}
            </div>
            <div className="leading-snug">
              Model, approval mode, native resume, and compact state are bound to the current session, not the channel's primary pointer. The channel prompt still enters harness turns as a host instruction. Normal-loop model override, passive memory, RAG, knowledge, memory, and context controls stay hidden until harness-native behavior exists. Tool and skill enrollment remains available as the harness bridge source.
            </div>
          </div>
        </Section>
        <ProjectSection form={form} patch={patch} workspaceId={workspaceId} />
        <ChannelPromptSection form={form} patch={patch} workspaceId={workspaceId} settings={settings} channelId={channelId} />
        <Section
          title="Harness Context"
          description="Native compaction stays inside the harness. Spindrel can prompt or trigger native compact when context pressure is visible."
        >
          <FormRow
            label="Auto-compaction prompts"
            description="Prompt when remaining native context drops below the soft threshold; hard threshold makes the prompt urgent but still requires an explicit compact action."
          >
            <Toggle
              value={form.harness_auto_compaction_enabled ?? true}
              onChange={(v) => patch("harness_auto_compaction_enabled", v as ChannelSettings["harness_auto_compaction_enabled"])}
            />
          </FormRow>
          <Row stack={false}>
            <Col minWidth={160}>
              <FormRow label="Prompt below remaining %" description="Default 60.">
                <TextInput
                  value={String(form.harness_auto_compaction_soft_remaining_pct ?? 60)}
                  onChangeText={(v) => patch("harness_auto_compaction_soft_remaining_pct", Number(v || 60) as ChannelSettings["harness_auto_compaction_soft_remaining_pct"])}
                />
              </FormRow>
            </Col>
            <Col minWidth={160}>
              <FormRow label="Auto-compact below remaining %" description="Default 10.">
                <TextInput
                  value={String(form.harness_auto_compaction_hard_remaining_pct ?? 10)}
                  onChangeText={(v) => patch("harness_auto_compaction_hard_remaining_pct", Number(v || 10) as ChannelSettings["harness_auto_compaction_hard_remaining_pct"])}
                />
              </FormRow>
            </Col>
          </Row>
          <div className="rounded-md bg-surface-overlay p-3 text-xs leading-snug text-text-muted">
            `/compact` uses native harness compaction when the SDK supports it. Each run records a harness trace with source, native session id, before/after context estimates, usage, and error details. The ctx badge shows the latest compact trace; `/new` and `/clear` open a fresh session without deleting or rewriting the current one.
          </div>
        </Section>
        <MessageRoutingSection form={form} patch={patch} />
      </>
    );
  }
  return (
    <>
      <AgentIdentitySection form={form} patch={patch} bots={bots} settings={settings} />
      <ProjectSection form={form} patch={patch} workspaceId={workspaceId} />
      <ChannelPromptSection form={form} patch={patch} workspaceId={workspaceId} settings={settings} channelId={channelId} />
      <MessageRoutingSection form={form} patch={patch} />
      <ModelOverrideSection form={form} patch={patch} bots={bots} settings={settings} />
      <AgentBehaviorSection form={form} patch={patch} />
    </>
  );
}

export function PresentationTabSections({
  form,
  patch,
  channelId,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
}) {
  return (
    <>
      <div className="rounded-md bg-surface-overlay p-3 text-xs text-text-muted">
        Widget grid layout moved to the{" "}
        <a href="#dashboard" className="text-accent hover:underline">
          Dashboard
        </a>{" "}
        tab.
      </div>
      <PresentationSection form={form} patch={patch} channelId={channelId} />
    </>
  );
}

export function AutomationTabSections({
  form,
  patch,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
}) {
  return <PipelineModeSection form={form} patch={patch} />;
}

export function DashboardSettingsLink({
  channelId,
  label = "Presentation settings",
}: {
  channelId: string;
  label?: string;
}) {
  return (
    <Link
      to={`/channels/${channelId}/settings?from=dashboard#presentation`}
      className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1.5 text-[12px] font-medium text-text-muted no-underline transition-colors hover:bg-surface-overlay hover:text-text"
    >
      {label}
    </Link>
  );
}
