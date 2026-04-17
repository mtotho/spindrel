import { useCallback, useState } from "react";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import { useNavigate } from "react-router-dom";
import { Trash2, AlertTriangle, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useDeleteChannel, useChannelCategories } from "@/src/api/hooks/useChannels";
import {
  Section, FormRow, TextInput, SelectInput, Toggle,
  Row, Col,
} from "@/src/components/shared/FormControls";
import { AdvancedSection, InfoBanner } from "@/src/components/shared/SettingsControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { apiFetch } from "@/src/api/client";
import { useQuery } from "@tanstack/react-query";
import type { ChannelSettings } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Channel owner select (fetches users for dropdown)
// ---------------------------------------------------------------------------
function ChannelOwnerSelect({ value, onChange }: { value: string | null; onChange: (v: string | null) => void }) {
  const { data: users } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => apiFetch<{ id: string; display_name: string; email: string }[]>("/api/v1/admin/users"),
  });
  const options = [
    { label: "None", value: "" },
    ...(users?.map((u) => ({ label: `${u.display_name} (${u.email})`, value: u.id })) ?? []),
  ];
  return (
    <SelectInput
      value={value ?? ""}
      onChange={(v) => onChange(v || null)}
      options={options}
    />
  );
}

// ---------------------------------------------------------------------------
// Tag editor — chip input for channel tags
// ---------------------------------------------------------------------------
function TagEditor({
  tags,
  onChange,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
}) {
  const t = useThemeTokens();
  const [input, setInput] = useState("");

  const addTag = (raw: string) => {
    const tag = raw.trim().toLowerCase();
    if (tag && !tags.includes(tag)) onChange([...tags, tag]);
    setInput("");
  };

  const handleKeyDown = (e: any) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(input);
    }
    if (e.key === "Backspace" && !input && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
      {tags.map((tag) => (
        <div
          key={tag}
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 4,
            padding: "3px 8px",
            borderRadius: 4,
            backgroundColor: t.surfaceOverlay,
            border: `1px solid ${t.surfaceBorder}`,
          }}
        >
          <span style={{ fontSize: 11, color: t.textMuted }}>{tag}</span>
          <button type="button" onClick={() => onChange(tags.filter((x) => x !== tag))}>
            <X size={11} color={t.textDim} />
          </button>
        </div>
      ))}
      <input
        value={input}
        onChange={(e: any) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => { if (input.trim()) addTag(input); }}
        placeholder={tags.length === 0 ? "Add tags..." : ""}
        style={{
          flex: 1,
          minWidth: 80,
          border: "none",
          outline: "none",
          background: "transparent",
          color: t.text,
          fontSize: 12,
          padding: "4px 0",
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Advanced — collapsible section for rarely-changed settings
// ---------------------------------------------------------------------------
function GeneralAdvancedSection({
  form,
  patch,
  settings,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  settings: ChannelSettings;
}) {
  const t = useThemeTokens();
  const isMobile = useIsMobile();

  return (
    <AdvancedSection>
      <Section title="Behavior">
        <Toggle
          value={form.passive_memory ?? true}
          onChange={(v) => patch("passive_memory", v)}
          label="Passive memory"
          description="Include passive messages in memory compaction."
        />
        <Toggle
          value={form.workspace_rag ?? true}
          onChange={(v) => patch("workspace_rag", v)}
          label="Workspace RAG"
          description="Auto-inject relevant workspace files into context each turn."
        />
        <FormRow label="Thinking display" description="How intermediate thinking is shown in integrations (Slack, etc.)">
          <SelectInput
            value={form.thinking_display ?? "append"}
            onChange={(v) => patch("thinking_display", v)}
            options={[
              { label: "Hidden (just 'thinking...')", value: "hidden" },
              { label: "Replace (single updating message)", value: "replace" },
              { label: "Append all", value: "append" },
            ]}
          />
        </FormRow>
        <FormRow label="Tool output" description="How tool-call results are rendered in integrations (Slack, etc.). Web UI always shows the full widget.">
          <SelectInput
            value={form.tool_output_display ?? "compact"}
            onChange={(v) => patch("tool_output_display", v)}
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
                onChangeText={(v) => { const n = parseInt(v); patch("max_iterations", isNaN(n) ? undefined : n); }}
                placeholder="default"
                type="number"
              />
            </FormRow>
          </Col>
          <Col minWidth={isMobile ? 0 : 200}>
            <FormRow label="Max task run time (seconds)">
              <TextInput
                value={form.task_max_run_seconds?.toString() ?? ""}
                onChangeText={(v) => { const n = parseInt(v); patch("task_max_run_seconds", isNaN(n) ? undefined : n); }}
                placeholder="1200 (default)"
                type="number"
              />
            </FormRow>
          </Col>
        </Row>
      </Section>

      <Section title="Privacy">
        <Toggle
          value={form.private ?? false}
          onChange={(v) => patch("private", v)}
          label="Private channel"
          description="Private channels are only visible to the assigned user."
        />
        <FormRow label="Owner" description="User who owns this channel. Private channels require an owner.">
          <ChannelOwnerSelect
            value={form.user_id ?? null}
            onChange={(v) => patch("user_id", v || undefined)}
          />
        </FormRow>
      </Section>

      <Section title="Automation">
        <FormRow
          label="Pipeline mode"
          description="Controls whether the pipeline launchpad and Findings panel are visible in this channel."
        >
          <SelectInput
            value={(form.pipeline_mode ?? "auto") as string}
            onChange={(v) => patch("pipeline_mode", v as "auto" | "on" | "off")}
            options={[
              { label: "Auto — show when pipelines are subscribed", value: "auto" },
              { label: "Always on", value: "on" },
              { label: "Off", value: "off" },
            ]}
          />
        </FormRow>
      </Section>

      {/* Metadata */}
      <div style={{ opacity: 0.4, fontSize: 11, color: t.textDim, display: "flex", flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
        <span>ID: {settings.id}</span>
        {settings.client_id && <span>client_id: {settings.client_id}</span>}
        {settings.integration && <span>integration: {settings.integration}</span>}
      </div>
    </AdvancedSection>
  );
}

// ---------------------------------------------------------------------------
// General Tab — settings form
// ---------------------------------------------------------------------------
export function GeneralTab({ form, patch, bots, settings, workspaceId, channelId }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  bots: any[] | undefined;
  settings: ChannelSettings;
  workspaceId?: string | null;
  channelId: string;
}) {
  const t = useThemeTokens();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const deleteMutation = useDeleteChannel();
  const { data: existingCategories } = useChannelCategories();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  const categoryValue = (form.category as string | undefined | null) ?? "";
  const categorySuggestions = (existingCategories ?? []).filter(
    (c) => c.toLowerCase().includes(categoryValue.toLowerCase()) && c !== categoryValue,
  );

  const handleDelete = useCallback(async () => {
    await deleteMutation.mutateAsync(channelId);
    navigate("/channels", { replace: true });
  }, [channelId, deleteMutation, navigate]);

  return (
    <>
      <Section title="General">
        <Row stack={isMobile}>
          <Col minWidth={isMobile ? 0 : 200}>
            <FormRow label="Display Name" description="Label shown in sidebar. Does not affect routing.">
              <TextInput
                value={form.name ?? ""}
                onChangeText={(v) => patch("name", v)}
                placeholder="Channel name"
              />
            </FormRow>
          </Col>
          <Col minWidth={isMobile ? 0 : 200}>
            <FormRow label="Bot">
              <SelectInput
                value={form.bot_id ?? ""}
                onChange={(v) => patch("bot_id", v)}
                options={bots?.map((b) => ({ label: `${b.name} (${b.id})`, value: b.id })) ?? []}
              />
            </FormRow>
          </Col>
        </Row>
        <Row stack={isMobile}>
          <Col minWidth={isMobile ? 0 : 200}>
            <FormRow label="Tags" description="Categorize with tags. Press Enter or comma to add.">
              <TagEditor
                tags={(form.tags as string[]) ?? []}
                onChange={(v) => patch("tags", v)}
              />
            </FormRow>
          </Col>
          <Col minWidth={isMobile ? 0 : 200}>
            <FormRow label="Category" description="Groups channels in the sidebar.">
              <TextInput
                value={categoryValue}
                onChangeText={(v) => patch("category", v || undefined)}
                placeholder="e.g. Work, Personal"
              />
              {categorySuggestions.length > 0 && categoryValue.length > 0 && (
                <div className="flex flex-row flex-wrap gap-1" style={{ marginTop: 4 }}>
                  {categorySuggestions.slice(0, 4).map((cat) => (
                    <button type="button"
                      key={cat}
                      onClick={() => patch("category", cat)}
                      style={{
                        backgroundColor: t.surfaceOverlay,
                        padding: "2px 6px",
                        borderRadius: 4,
                        border: `1px solid ${t.surfaceBorder}`,
                        cursor: "pointer",
                      }}
                    >
                      <span style={{ fontSize: 10, color: t.textMuted }}>{cat}</span>
                    </button>
                  ))}
                </div>
              )}
            </FormRow>
          </Col>
        </Row>
        {form.bot_id && settings.bot_id && form.bot_id !== settings.bot_id && (
          <InfoBanner variant="warning" icon={<AlertTriangle size={14} color="#f59e0b" />}>
            <strong>Switching bots.</strong> Existing conversation history sections (transcripts on disk)
            belong to the previous bot's workspace and won't be accessible to the new bot. The new bot
            will only see recent messages still in the context window. To rebuild history for the new bot,
            go to the <strong>History</strong> tab and re-run <strong>Backfill Sections</strong> after saving.
          </InfoBanner>
        )}
      </Section>

      <Section title="Channel Prompt" description="A short prompt injected as a system message right before each user message. Useful for per-channel instructions or reminders.">
        <WorkspaceFilePrompt
          workspaceId={form.channel_prompt_workspace_id ?? workspaceId}
          filePath={form.channel_prompt_workspace_file_path ?? null}
          onLink={(path, wsId) => {
            patch("channel_prompt_workspace_file_path", path);
            patch("channel_prompt_workspace_id", wsId);
          }}
          onUnlink={() => {
            patch("channel_prompt_workspace_file_path", undefined);
            patch("channel_prompt_workspace_id", undefined);
          }}
        />
        {!form.channel_prompt_workspace_file_path && (
          <LlmPrompt
            value={form.channel_prompt ?? ""}
            onChange={(v) => patch("channel_prompt", v || undefined)}
            label="Channel Prompt"
            placeholder="Leave blank for no channel-level prompt..."
            helpText="Inserted after all context (skills, memories, knowledge, tools) but before the user's message."
            rows={4}
            fieldType="channel_prompt"
            botId={settings.bot_id}
            channelId={channelId}
          />
        )}
      </Section>

      <Section title="Message Routing" description="Controls when inbound messages trigger the bot vs. get stored passively.">
        <Toggle
          value={form.require_mention ?? true}
          onChange={(v) => patch("require_mention", v)}
          label="Require @mention"
          description="Only @mentions or wake words trigger the bot; other messages stored as context. For integrations like Slack or BlueBubbles, this controls whether every message runs the agent or only ones that mention the bot."
        />
        <Toggle
          value={form.allow_bot_messages ?? false}
          onChange={(v) => patch("allow_bot_messages", v)}
          label="Allow bot messages"
          description="Process messages from other bots (e.g. GitHub webhooks) and trigger the agent. Has no effect on iMessage (BlueBubbles)."
        />
      </Section>

      <Section title="Model Override" description="Override the bot's default model for this channel. Leave empty to inherit.">
        <FormRow label="Model" description="All messages in this channel will use this model instead of the bot default.">
          <LlmModelDropdown
            value={form.model_override ?? ""}
            selectedProviderId={form.model_provider_id_override}
            onChange={(v, providerId) => {
              patch("model_override", v || null);
              patch("model_provider_id_override", v ? (providerId ?? null) : null);
            }}
            placeholder={`inherit (${bots?.find((b) => b.id === settings.bot_id)?.model ?? "bot default"})`}
            allowClear
          />
        </FormRow>
        <FormRow label="Fallback Models" description="Ordered list tried when primary fails. Empty inherits from bot. Global list appended as catch-all.">
          <FallbackModelList
            value={form.fallback_models ?? []}
            onChange={(v) => patch("fallback_models", v)}
          />
        </FormRow>
      </Section>

      {/* Collapsible advanced section */}
      <GeneralAdvancedSection form={form} patch={patch} settings={settings} />

      {/* Danger Zone */}
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
          <span style={{ fontSize: 13, fontWeight: "700", color: t.danger }}>Danger Zone</span>
        </div>
        <div style={{ padding: 16 }}>
          {!showDeleteConfirm ? (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
              <div style={{ flex: 1, minWidth: 180 }}>
                <span style={{ fontSize: 13, color: t.text, fontWeight: "600" }}>Delete this channel</span>
                <span style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
                  Permanently removes the channel, its integrations, and heartbeat config. Sessions and tasks will be unlinked.
                </span>
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
                Delete Channel
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                padding: "10px 14px", background: t.dangerSubtle, borderRadius: 6,
              }}>
                <AlertTriangle size={16} color={t.danger} />
                <span style={{ fontSize: 12, color: t.danger, fontWeight: "600" }}>
                  This action cannot be undone.
                </span>
              </div>
              <span style={{ fontSize: 12, color: t.textMuted }}>
                Type <span style={{ fontFamily: "monospace", color: t.danger, fontWeight: "600" }}>delete</span> to confirm:
              </span>
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
                  onClick={handleDelete}
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
                  {deleteMutation.isPending ? "Deleting..." : "Permanently Delete"}
                </button>
                <button
                  onClick={() => { setShowDeleteConfirm(false); setDeleteConfirmText(""); }}
                  style={{
                    padding: "8px 16px", fontSize: 12, fontWeight: 500,
                    border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                    background: "transparent", color: t.textMuted, cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </div>
              {deleteMutation.isError && (
                <span style={{ fontSize: 11, color: t.danger }}>
                  {deleteMutation.error instanceof Error ? deleteMutation.error.message : "Failed to delete channel"}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
