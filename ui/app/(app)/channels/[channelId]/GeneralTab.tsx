import { useCallback, useState } from "react";
import { View, Text, Pressable } from "react-native";
import { useRouter } from "expo-router";
import { Trash2, AlertTriangle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useDeleteChannel } from "@/src/api/hooks/useChannels";
import {
  Section, FormRow, TextInput, SelectInput, Toggle,
  Row, Col,
} from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
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
  const router = useRouter();
  const deleteMutation = useDeleteChannel();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  const handleDelete = useCallback(async () => {
    await deleteMutation.mutateAsync(channelId);
    router.replace("/channels" as any);
  }, [channelId, deleteMutation, router]);

  return (
    <>
      <Section title="General">
        <Row>
          <Col>
            <FormRow label="Display Name" description="Label shown in sidebar. Does not affect routing.">
              <TextInput
                value={form.name ?? ""}
                onChangeText={(v) => patch("name", v)}
                placeholder="Channel name"
              />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Bot">
              <SelectInput
                value={form.bot_id ?? ""}
                onChange={(v) => patch("bot_id", v)}
                options={bots?.map((b) => ({ label: `${b.name} (${b.id})`, value: b.id })) ?? []}
              />
            </FormRow>
          </Col>
        </Row>
        {form.bot_id && settings.bot_id && form.bot_id !== settings.bot_id && (
          <div style={{
            padding: "10px 14px", background: "#1a1400", border: "1px solid #92400e",
            borderRadius: 8, fontSize: 11, color: "#ca8a04", lineHeight: "1.5",
            display: "flex", gap: 8, alignItems: "flex-start",
          }}>
            <AlertTriangle size={14} color="#f59e0b" style={{ flexShrink: 0, marginTop: 1 }} />
            <div>
              <strong>Switching bots.</strong> Existing conversation history sections (transcripts on disk)
              belong to the previous bot's workspace and won't be accessible to the new bot. The new bot
              will only see recent messages still in the context window. To rebuild history for the new bot,
              go to the <strong>History</strong> tab and re-run <strong>Backfill Sections</strong> after saving.
            </div>
          </div>
        )}
      </Section>

      <Section title="Channel Prompt" description="A short prompt injected as a system message right before each user message. Useful for per-channel instructions or reminders.">
        <LlmPrompt
          value={form.channel_prompt ?? ""}
          onChange={(v) => patch("channel_prompt", v || undefined)}
          label="Channel Prompt"
          placeholder="Leave blank for no channel-level prompt..."
          helpText="Inserted after all context (skills, memories, knowledge, tools) but before the user's message."
          rows={4}
          generateContext="A system-level prompt injected into every request in this channel. Used for persistent instructions, personality, behavioral guidelines, or domain-specific context for the AI."
        />
      </Section>

      <Section title="Model Override" description="Override the bot's default model for this channel. Leave empty to inherit.">
        <FormRow label="Model" description="All messages in this channel will use this model instead of the bot default.">
          <LlmModelDropdown
            value={form.model_override ?? ""}
            onChange={(v) => {
              patch("model_override", v || undefined);
              if (!v) patch("model_provider_id_override", undefined);
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

      <Section title="Behavior">
        <Toggle
          value={form.require_mention ?? true}
          onChange={(v) => patch("require_mention", v)}
          label="Require @mention"
          description="Only @mentions trigger the bot; other messages stored as context."
        />
        <Toggle
          value={form.passive_memory ?? true}
          onChange={(v) => patch("passive_memory", v)}
          label="Passive memory"
          description="Include passive messages in memory compaction."
        />
        <Toggle
          value={form.allow_bot_messages ?? false}
          onChange={(v) => patch("allow_bot_messages", v)}
          label="Allow bot messages"
          description="Process messages from other bots (e.g. GitHub) and trigger the agent."
        />
        <Toggle
          value={form.workspace_rag ?? true}
          onChange={(v) => patch("workspace_rag", v)}
          label="Workspace RAG"
          description="Auto-inject relevant workspace files into context each turn."
        />
        <Row>
          <Col>
            <FormRow label="Max iterations">
              <TextInput
                value={form.max_iterations?.toString() ?? ""}
                onChangeText={(v) => patch("max_iterations", v ? parseInt(v) || undefined : undefined)}
                placeholder="default"
                type="number"
              />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Max task run time (seconds)">
              <TextInput
                value={form.task_max_run_seconds?.toString() ?? ""}
                onChangeText={(v) => patch("task_max_run_seconds", v ? parseInt(v) || undefined : undefined)}
                placeholder="1200 (default)"
                type="number"
              />
            </FormRow>
          </Col>
        </Row>
      </Section>

      {/* Metadata */}
      <div style={{ opacity: 0.4, fontSize: 11, color: t.textDim, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <span>ID: {settings.id}</span>
        {settings.client_id && <span>client_id: {settings.client_id}</span>}
        {settings.integration && <span>integration: {settings.integration}</span>}
      </div>

      {/* Danger Zone */}
      <div style={{
        marginTop: 32,
        border: "1px solid rgba(239,68,68,0.25)",
        borderRadius: 8,
        overflow: "hidden",
      }}>
        <div style={{
          padding: "10px 14px",
          background: "#7f1d1d33",
          borderBottom: "1px solid #7f1d1d",
        }}>
          <Text style={{ fontSize: 13, fontWeight: "700", color: "#dc2626" }}>Danger Zone</Text>
        </div>
        <div style={{ padding: 16 }}>
          {!showDeleteConfirm ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
              <div style={{ flex: 1, minWidth: 180 }}>
                <Text style={{ fontSize: 13, color: t.text, fontWeight: "600" }}>Delete this channel</Text>
                <Text style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
                  Permanently removes the channel, its integrations, and heartbeat config. Sessions and tasks will be unlinked.
                </Text>
              </div>
              <button
                onClick={() => setShowDeleteConfirm(true)}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "8px 16px", fontSize: 12, fontWeight: 600,
                  border: "1px solid #991b1b", borderRadius: 6,
                  background: "transparent", color: "#dc2626", cursor: "pointer",
                  flexShrink: 0,
                }}
              >
                <Trash2 size={13} color="#dc2626" />
                Delete Channel
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "10px 14px", background: "#7f1d1d44", borderRadius: 6,
              }}>
                <AlertTriangle size={16} color="#dc2626" />
                <Text style={{ fontSize: 12, color: "#dc2626", fontWeight: "600" }}>
                  This action cannot be undone.
                </Text>
              </div>
              <Text style={{ fontSize: 12, color: t.textMuted }}>
                Type <Text style={{ fontFamily: "monospace", color: "#dc2626", fontWeight: "600" }}>delete</Text> to confirm:
              </Text>
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
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  onClick={handleDelete}
                  disabled={deleteConfirmText !== "delete" || deleteMutation.isPending}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "8px 20px", fontSize: 12, fontWeight: 700,
                    border: "none", borderRadius: 6, cursor: "pointer",
                    background: deleteConfirmText === "delete" ? "#dc2626" : t.surfaceBorder,
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
                <Text style={{ fontSize: 11, color: "#dc2626" }}>
                  {deleteMutation.error instanceof Error ? deleteMutation.error.message : "Failed to delete channel"}
                </Text>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
