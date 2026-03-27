import { useCallback, useState, useEffect, useMemo } from "react";
import { View, Text, Pressable, ScrollView, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft, Check, RotateCw, Play, ExternalLink, Plus, Search, X, Trash2, AlertTriangle } from "lucide-react";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useDeleteChannel,
  useChannel,
  useChannelEffectiveTools,
  useChannelIntegrations,
  useBindIntegration,
  useUnbindIntegration,
  useAvailableIntegrations,
  useChannelContextBreakdown,
} from "@/src/api/hooks/useChannels";
import { useBots, useBotEditorData } from "@/src/api/hooks/useBots";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import {
  Section, FormRow, TextInput, SelectInput, Toggle,
  Row, Col, TabBar, EmptyState,
  triStateOptions, triStateValue, triStateParse,
} from "@/src/components/shared/FormControls";
import { apiFetch } from "@/src/api/client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { ChannelSettings, BotEditorData, ToolGroup, ContextBreakdown } from "@/src/types/api";
import { useLogs, type LogRow } from "@/src/api/hooks/useLogs";
import { useChannelElevation } from "@/src/api/hooks/useElevation";
import { TaskEditor as TaskEditorShared } from "@/src/components/shared/TaskEditor";
import { PromptTemplateLink } from "@/src/components/shared/PromptTemplateLink";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";

// ---------------------------------------------------------------------------
// Interval options for heartbeat
// ---------------------------------------------------------------------------
const INTERVAL_OPTIONS = [
  { label: "5 minutes", value: "5" },
  { label: "15 minutes", value: "15" },
  { label: "30 minutes", value: "30" },
  { label: "1 hour", value: "60" },
  { label: "2 hours", value: "120" },
  { label: "4 hours", value: "240" },
  { label: "8 hours", value: "480" },
  { label: "12 hours", value: "720" },
  { label: "24 hours", value: "1440" },
];

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------
const BASE_TABS = [
  { key: "general", label: "General" },
  { key: "history", label: "History" },
  { key: "context", label: "Context" },
  { key: "tools", label: "Tools" },
  { key: "integrations", label: "Integrations" },
  { key: "sessions", label: "Sessions" },
  { key: "heartbeat", label: "Heartbeat" },
  { key: "tasks", label: "Tasks" },
  { key: "compression", label: "Compression" },
  { key: "logs", label: "Logs" },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function ChannelSettingsScreen() {
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const goBack = useGoBack(`/channels/${channelId}`);
  const queryClient = useQueryClient();
  const { data: channel } = useChannel(channelId);
  const { data: settings, isLoading } = useChannelSettings(channelId);
  const { data: bots } = useBots();
  const updateMutation = useUpdateChannelSettings(channelId!);
  const { data: elevationData } = useChannelElevation(channelId);

  // Check if the channel's bot is in a workspace
  const currentBot = bots?.find((b: any) => b.id === settings?.bot_id);
  const hasWorkspace = !!currentBot?.shared_workspace_id;
  const TABS = useMemo(() => {
    if (hasWorkspace) {
      const idx = BASE_TABS.findIndex((t) => t.key === "context");
      const tabs = [...BASE_TABS];
      tabs.splice(idx + 1, 0, { key: "workspace", label: "Workspace" });
      return tabs;
    }
    return BASE_TABS;
  }, [hasWorkspace]);

  const [tab, setTab] = useState("general");
  const [form, setForm] = useState<Partial<ChannelSettings>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setForm({
        name: settings.name,
        bot_id: settings.bot_id,
        require_mention: settings.require_mention,
        passive_memory: settings.passive_memory,
        allow_bot_messages: settings.allow_bot_messages,
        workspace_rag: settings.workspace_rag,
        max_iterations: settings.max_iterations,
        context_compaction: settings.context_compaction,
        compaction_interval: settings.compaction_interval,
        compaction_keep_turns: settings.compaction_keep_turns,
        memory_knowledge_compaction_prompt: settings.memory_knowledge_compaction_prompt,
        compaction_prompt_template_id: settings.compaction_prompt_template_id,
        compaction_workspace_file_path: settings.compaction_workspace_file_path,
        compaction_workspace_id: settings.compaction_workspace_id,
        history_mode: settings.history_mode,
        compaction_model: settings.compaction_model,
        compaction_skip_memory_phase: settings.compaction_skip_memory_phase,
        context_compression: settings.context_compression,
        compression_model: settings.compression_model,
        compression_threshold: settings.compression_threshold,
        compression_keep_turns: settings.compression_keep_turns,
        compression_prompt: settings.compression_prompt,
        response_condensing_enabled: settings.response_condensing_enabled,
        response_condensing_threshold: settings.response_condensing_threshold,
        response_condensing_keep_exact: settings.response_condensing_keep_exact,
        response_condensing_model: settings.response_condensing_model,
        response_condensing_prompt: settings.response_condensing_prompt,
        elevation_enabled: settings.elevation_enabled,
        elevation_threshold: settings.elevation_threshold,
        elevated_model: settings.elevated_model,
        model_override: settings.model_override,
        model_provider_id_override: settings.model_provider_id_override,
        fallback_model: settings.fallback_model,
        fallback_model_provider_id: settings.fallback_model_provider_id,
        channel_prompt: settings.channel_prompt,
        workspace_skills_enabled: settings.workspace_skills_enabled,
        workspace_base_prompt_enabled: settings.workspace_base_prompt_enabled,
      });
    }
  }, [settings]);

  const patch = useCallback(
    <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => {
      setForm((f) => ({ ...f, [key]: value }));
      setSaved(false);
    },
    []
  );

  const handleSave = useCallback(async () => {
    await updateMutation.mutateAsync(form);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }, [form, updateMutation]);

  if (isLoading || !settings) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View className="flex-row items-center gap-3 px-4 py-3 border-b border-surface-border" style={{ flexShrink: 0 }}>
        <Pressable
          onPress={goBack}
          className="items-center justify-center rounded-md hover:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
        >
          <ArrowLeft size={20} color="#999" />
        </Pressable>
        <View className="flex-1 min-w-0">
          <Text className="text-text font-semibold text-sm" numberOfLines={1}>
            {channel?.display_name || channel?.name || channel?.client_id || "Channel"}
          </Text>
          <Text className="text-text-dim text-xs" numberOfLines={1}>
            Channel Settings
          </Text>
        </View>
        {(tab === "general" || tab === "history" || tab === "compression" || tab === "workspace") && (
          <Pressable
            onPress={handleSave}
            disabled={updateMutation.isPending}
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
              paddingHorizontal: 14,
              minHeight: 44,
              borderRadius: 8,
              backgroundColor: saved ? "rgba(34,197,94,0.15)" : "#3b82f6",
            }}
          >
            {saved ? (
              <>
                <Check size={14} color="#22c55e" />
                <Text style={{ color: "#22c55e", fontSize: 13, fontWeight: "600" }}>Saved</Text>
              </>
            ) : (
              <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>
                {updateMutation.isPending ? "Saving..." : "Save"}
              </Text>
            )}
          </Pressable>
        )}
      </View>

      {/* Tabs */}
      <View className="px-4 pt-2">
        <TabBar tabs={TABS} active={tab} onChange={setTab} />
      </View>

      {/* Tab content */}
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ padding: 20, gap: 20, maxWidth: 680 }}
        key={tab}
      >
        {tab === "general" && (
          <GeneralTab form={form} patch={patch} bots={bots} settings={settings} elevationData={elevationData} workspaceId={currentBot?.shared_workspace_id} channelId={channelId!} />
        )}
        {tab === "history" && (
          <HistoryTab form={form} patch={patch} channelId={channelId!} workspaceId={currentBot?.shared_workspace_id} />
        )}
        {tab === "context" && <ContextTab channelId={channelId!} />}
        {tab === "workspace" && (
          <WorkspaceOverrideTab
            form={form}
            patch={patch}
            workspaceId={currentBot?.shared_workspace_id}
            channelId={channelId!}
            onSave={handleSave}
            saving={updateMutation.isPending}
            saved={saved}
          />
        )}
        {tab === "tools" && <ToolsOverrideTab channelId={channelId!} botId={channel?.bot_id} />}
        {tab === "integrations" && <IntegrationsTab channelId={channelId!} />}
        {tab === "sessions" && <SessionsTab channelId={channelId!} />}
        {tab === "heartbeat" && <HeartbeatTab channelId={channelId!} workspaceId={currentBot?.shared_workspace_id} />}
        {tab === "tasks" && <TasksTab channelId={channelId!} botId={channel?.bot_id} />}
        {tab === "compression" && <CompressionTab channelId={channelId!} form={form} patch={patch} />}
        {tab === "logs" && <LogsTab channelId={channelId!} />}
      </ScrollView>
    </View>
  );
}

// ===========================================================================
// History Mode section — visual mode selector with contextual details
// ===========================================================================

const HISTORY_MODES: ReadonlyArray<{
  value: string; label: string; icon: string; color: string;
  bg: string; border: string; summary: string; detail: string | null;
  recommended?: boolean;
}> = [
  {
    value: "",
    label: "Inherit",
    icon: "↓",
    color: "#666",
    bg: "#222",
    border: "#333",
    summary: "Use the bot's default history mode.",
    detail: null,
  },
  {
    value: "summary",
    label: "Summary",
    icon: "📝",
    color: "#93c5fd",
    bg: "#0c1929",
    border: "#1e3a5f",
    summary: "Flat rolling summary — simple and efficient.",
    detail:
      "Each compaction replaces the previous summary with a new one covering the full conversation. " +
      "The bot sees only a single summary block plus recent messages. Best for straightforward conversations " +
      "where historical detail isn't important.",
  },
  {
    value: "structured",
    label: "Structured",
    icon: "🔍",
    color: "#c084fc",
    bg: "#1a0a2e",
    border: "#3b0764",
    summary: "Semantic retrieval — automatically surfaces relevant history.",
    detail:
      "Conversation is archived into titled sections with embeddings. Each turn, the system automatically " +
      "retrieves sections most relevant to the current query via cosine similarity and injects them into context. " +
      "The bot doesn't need to do anything — relevant history appears automatically. Best for long-running " +
      "channels where past context matters but you don't want the bot spending tool calls to find it.",
  },
  {
    value: "file",
    label: "File",
    icon: "📂",
    color: "#fcd34d",
    bg: "#1a1400",
    border: "#92400e",
    summary: "Tool-based navigation — the bot browses history on demand.",
    detail:
      "Conversation is archived into titled sections. The bot gets an executive summary plus a section " +
      "index, and can use the read_conversation_history tool to open any section and read its full transcript. " +
      "This gives the bot agency to decide what to look up. Best for knowledge-heavy channels where the bot " +
      "needs to reference specific past discussions.",
    recommended: true,
  },
];

function HistoryModeSection({ form, patch }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
}) {
  const selected = form.history_mode ?? "";
  const mode = HISTORY_MODES.find((m) => m.value === selected) || HISTORY_MODES[0];

  return (
    <Section title="History Mode">
      {/* Mode selector cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8 }}>
        {HISTORY_MODES.map((m) => {
          const isSelected = selected === m.value;
          return (
            <button
              key={m.value}
              onClick={() => patch("history_mode", m.value || null)}
              style={{
                display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
                padding: "14px 10px", borderRadius: 8, cursor: "pointer",
                background: isSelected ? m.bg : "#111",
                border: `2px solid ${isSelected ? m.color : "#2a2a2a"}`,
                transition: "all 0.15s ease",
              }}
            >
              <span style={{ fontSize: 22 }}>{m.icon}</span>
              <span style={{
                fontSize: 12, fontWeight: 700,
                color: isSelected ? m.color : "#888",
              }}>
                {m.label}
              </span>
              {m.recommended && (
                <span style={{ fontSize: 9, fontWeight: 700, color: "#f59e0b", letterSpacing: "0.03em" }}>
                  Recommended
                </span>
              )}
              <span style={{
                fontSize: 10, color: isSelected ? "#999" : "#555",
                textAlign: "center", lineHeight: "1.3",
              }}>
                {m.summary}
              </span>
            </button>
          );
        })}
      </div>

      {/* Detail panel for selected mode */}
      {mode.detail && (
        <div style={{
          marginTop: 10, padding: "12px 14px",
          background: mode.bg, border: `1px solid ${mode.border}`,
          borderRadius: 8, fontSize: 12, lineHeight: "1.5", color: "#bbb",
        }}>
          {mode.detail}
        </div>
      )}
    </Section>
  );
}

// ===========================================================================
// Backfill sections button
// ===========================================================================
function BackfillButton({ channelId, historyMode }: { channelId: string; historyMode: string }) {
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ section: number; total: number; title?: string } | null>(null);
  const [result, setResult] = useState<{ sections: number; error?: string } | null>(null);
  const queryClient = useQueryClient();
  const { data: sectionsData } = useQuery({
    queryKey: ["channel-sections", channelId],
    queryFn: () => apiFetch<{ total: number }>(`/api/v1/admin/channels/${channelId}/sections`),
  });
  const existingSections = sectionsData?.total ?? 0;

  const handleBackfill = useCallback(async () => {
    if (existingSections > 0 && !window.confirm(
      `This will delete all ${existingSections} existing section${existingSections !== 1 ? "s" : ""} and re-chunk everything from scratch using the compaction model. Continue?`
    )) return;

    setRunning(true);
    setProgress(null);
    setResult(null);
    try {
      // Fire-and-forget: POST returns a task_id, then we poll
      const { task_id } = await apiFetch<{ task_id: string }>(
        `/api/v1/admin/channels/${channelId}/backfill-sections`,
        { method: "POST", body: JSON.stringify({
          history_mode: historyMode,
          clear_existing: existingSections > 0,
        }) },
      );

      // Poll every 2s until complete or failed
      const poll = async () => {
        while (true) {
          await new Promise((r) => setTimeout(r, 2000));
          const job = await apiFetch<{
            status: string; sections_created: number; total_chunks: number;
            current_title?: string; error?: string;
          }>(`/api/v1/admin/channels/${channelId}/backfill-status/${task_id}`);

          if (job.status === "running") {
            setProgress({ section: job.sections_created, total: job.total_chunks, title: job.current_title });
          } else if (job.status === "complete") {
            setResult({ sections: job.sections_created });
            break;
          } else if (job.status === "failed") {
            setResult({ sections: job.sections_created, error: job.error || "Backfill failed" });
            break;
          }
        }
      };
      await poll();
    } catch (e) {
      setResult({ sections: 0, error: e instanceof Error ? e.message : "Unknown error" });
    } finally {
      setRunning(false);
      queryClient.invalidateQueries({ queryKey: ["channel-sections", channelId] });
    }
  }, [channelId, historyMode, queryClient, existingSections]);

  return (
    <div style={{ padding: "10px 0" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button
          onClick={handleBackfill}
          disabled={running}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 14px", fontSize: 12, fontWeight: 600,
            border: "none", cursor: running ? "default" : "pointer", borderRadius: 6,
            background: running ? "#333" : "#92400e",
            color: running ? "#666" : "#fcd34d",
            opacity: running ? 0.7 : 1,
          }}
        >
          <Play size={12} color={running ? "#666" : "#fcd34d"} />
          {running ? "Backfilling..." : existingSections > 0 ? "Re-chunk Sections" : "Backfill Sections"}
        </button>
        <span style={{ fontSize: 11, color: "#777", flex: 1, minWidth: 200 }}>
          {existingSections > 0
            ? "Deletes all existing sections and re-chunks everything through the compaction model. Use if you switched modes, changed models, or sections are low quality."
            : "Run initial backfill to chunk existing messages into navigable sections via the compaction model. Only needed once when switching to file/structured mode."
          }
        </span>
      </div>
      {progress && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#999" }}>
          Section {progress.section}/{progress.total}: {progress.title}
        </div>
      )}
      {result && !result.error && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#86efac" }}>
          Done — {result.sections} section{result.sections !== 1 ? "s" : ""} created
        </div>
      )}
      {result?.error && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#fca5a5" }}>
          {result.error}
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// Sections viewer — shows existing conversation sections
// ===========================================================================
function SectionsViewer({ channelId }: { channelId: string }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["channel-sections", channelId],
    queryFn: () => apiFetch<{ sections: Array<{
      id: string; sequence: number; title: string; summary: string;
      transcript: string; message_count: number;
      period_start: string | null; period_end: string | null;
      created_at: string | null; view_count: number;
      last_viewed_at: string | null; tags: string[];
    }>; total: number }>(`/api/v1/admin/channels/${channelId}/sections`),
  });

  if (isLoading) return <ActivityIndicator size="small" color="#666" style={{ marginTop: 8 }} />;
  if (!data?.sections?.length) return (
    <div style={{ fontSize: 11, color: "#555", padding: "8px 0" }}>
      No sections yet. Use backfill or let compaction create them automatically.
    </div>
  );

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#999", marginBottom: 6 }}>
        Archived Sections ({data.total})
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 600, minHeight: 0, overflowY: "auto" }}>
        {data.sections.map((s) => {
          const isOpen = expandedId === s.id;
          const dateStr = s.period_start
            ? new Date(s.period_start).toLocaleDateString(undefined, { month: "short", day: "numeric" })
            : "";
          return (
            <div key={s.id} style={{
              background: "#111", border: "1px solid #2a2a2a", borderRadius: 6,
              overflow: "hidden", flexShrink: 0,
            }}>
              <button
                onClick={() => setExpandedId(isOpen ? null : s.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%",
                  padding: "8px 12px", background: "none", border: "none",
                  cursor: "pointer", textAlign: "left", minHeight: 36,
                }}
              >
                <span style={{ fontSize: 10, color: "#555", minWidth: 20 }}>#{s.sequence}</span>
                <span style={{ fontSize: 12, color: "#ccc", flex: 1 }}>{s.title}</span>
                {s.tags?.length > 0 && (
                  <span style={{ display: "flex", gap: 3, flexShrink: 0 }}>
                    {s.tags.slice(0, 3).map((tag, i) => (
                      <span key={i} style={{
                        fontSize: 9, color: "#93c5fd", background: "#1e3a5f",
                        padding: "1px 5px", borderRadius: 8, whiteSpace: "nowrap",
                      }}>{tag}</span>
                    ))}
                  </span>
                )}
                <span style={{ fontSize: 10, color: "#666", flexShrink: 0 }}>{s.message_count} msgs</span>
                {s.view_count > 0 && (
                  <span style={{
                    fontSize: 9, color: "#a78bfa", background: "#2e1065",
                    padding: "1px 5px", borderRadius: 8, fontWeight: 600, flexShrink: 0,
                  }}>{s.view_count}x viewed</span>
                )}
                {dateStr && <span style={{ fontSize: 10, color: "#555", flexShrink: 0 }}>{dateStr}</span>}
                <span style={{ fontSize: 10, color: "#555", transform: isOpen ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s", flexShrink: 0 }}>▼</span>
              </button>
              {isOpen && (
                <div style={{ padding: "0 12px 10px", borderTop: "1px solid #222" }}>
                  <div style={{ fontSize: 11, color: "#999", padding: "8px 0 4px", fontWeight: 600 }}>Summary</div>
                  <div style={{ fontSize: 11, color: "#888", lineHeight: "1.5", whiteSpace: "pre-wrap" }}>{s.summary}</div>
                  {s.tags?.length > 0 && (
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6 }}>
                      {s.tags.map((tag, i) => (
                        <span key={i} style={{
                          fontSize: 10, color: "#93c5fd", background: "#1e3a5f",
                          padding: "2px 8px", borderRadius: 10,
                        }}>{tag}</span>
                      ))}
                    </div>
                  )}
                  <details style={{ marginTop: 8 }}>
                    <summary style={{ fontSize: 11, color: "#666", cursor: "pointer", userSelect: "none" }}>
                      View transcript
                    </summary>
                    <pre style={{
                      fontSize: 10, color: "#777", lineHeight: "1.4",
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                      maxHeight: 300, overflow: "auto",
                      background: "#0a0a0a", padding: 8, borderRadius: 4, marginTop: 4,
                    }}>{s.transcript}</pre>
                  </details>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ===========================================================================
// History Tab — history mode, compaction settings, backfill, response condensing
// ===========================================================================
function HistoryTab({ form, patch, channelId, workspaceId }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
  workspaceId?: string | null;
}) {
  const selected = form.history_mode ?? "";
  const isFileOrStructured = selected === "file" || selected === "structured";

  return (
    <>
      {/* 1. History Mode cards — always visible at top */}
      <HistoryModeSection form={form} patch={patch} />

      {/* 2. Compaction settings — conditional on mode */}
      {isFileOrStructured ? (
        <Section title="Compaction" description="Manages long conversations by archiving old turns into titled sections.">
          {/* Locked banner */}
          <div style={{
            padding: "10px 14px", background: "#1a1400", border: "1px solid #92400e",
            borderRadius: 8, fontSize: 12, color: "#fcd34d", fontWeight: 600,
          }}>
            Auto-compaction is always on in {selected} mode — it creates the archived sections the bot navigates.
          </div>

          {/* File-mode guidance */}
          <div style={{
            padding: "12px 14px", background: "#0d1117", border: "1px solid #1e3a5f",
            borderRadius: 8, fontSize: 11, color: "#8b949e", lineHeight: "1.6",
          }}>
            After every <strong style={{ color: "#e5e5e5" }}>Interval</strong> user turns, the oldest messages are
            archived into a titled, summarized section. The bot keeps the last <strong style={{ color: "#e5e5e5" }}>Keep Turns</strong> verbatim,
            plus an executive summary and section index. It can open any section with the <code style={{ color: "#c9d1d9" }}>read_conversation_history</code> tool.
            <div style={{ marginTop: 8, color: "#f59e0b" }}>
              Recommended: Interval 20, Keep Turns 6 — lower interval = more granular sections.
              The bot can always read full transcripts, so aggressive archival is safe.
            </div>
          </div>

          <Row>
            <Col>
              <FormRow label="Interval (user turns)" description="Compaction triggers after this many user messages. Lower = more frequent archival.">
                <TextInput
                  value={form.compaction_interval?.toString() ?? ""}
                  onChangeText={(v) => patch("compaction_interval", v ? parseInt(v) || undefined : undefined)}
                  placeholder="recommended (20)"
                  type="number"
                />
              </FormRow>
            </Col>
            <Col>
              <FormRow label="Keep Turns" description="Recent turns always kept verbatim — never archived.">
                <TextInput
                  value={form.compaction_keep_turns?.toString() ?? ""}
                  onChangeText={(v) => patch("compaction_keep_turns", v ? parseInt(v) || undefined : undefined)}
                  placeholder="recommended (6)"
                  type="number"
                />
              </FormRow>
            </Col>
          </Row>

          <LlmModelDropdown
            label="Compaction Model"
            value={form.compaction_model ?? ""}
            onChange={(v) => patch("compaction_model", v || undefined)}
            placeholder="inherit (bot model)"
          />
          <div style={{ fontSize: 10, color: "#666", marginTop: -4, marginBottom: 4 }}>
            Used for section generation, executive summaries, and backfill. A cheap/fast model works well here — the prompts are straightforward summarization.
          </div>

          {/* Memory phase toggle + prompt */}
          <Toggle
            value={!!form.compaction_skip_memory_phase}
            onChange={(v) => patch("compaction_skip_memory_phase", v || undefined)}
            label="Skip memory phase"
          />
          <div style={{ fontSize: 10, color: "#666", marginTop: -4, marginBottom: 4 }}>
            Skips the extra LLM call that lets the bot save memories/knowledge before archival.
            Enable this if you use heartbeat or another mechanism to persist memories — the memory phase becomes redundant.
          </div>

          {!form.compaction_skip_memory_phase && (
            <>
              <WorkspaceFilePrompt
                workspaceId={(form.compaction_workspace_id as string) ?? workspaceId}
                filePath={form.compaction_workspace_file_path ?? null}
                onLink={(path) => { patch("compaction_workspace_file_path", path); patch("compaction_workspace_id", workspaceId); }}
                onUnlink={() => { patch("compaction_workspace_file_path", undefined); patch("compaction_workspace_id", undefined); }}
              />
              {!form.compaction_workspace_file_path && (
                <>
                  <PromptTemplateLink
                    templateId={form.compaction_prompt_template_id ?? null}
                    onLink={(id) => patch("compaction_prompt_template_id", id)}
                    onUnlink={() => patch("compaction_prompt_template_id", undefined)}
                  />
                  <LlmPrompt
                    value={form.memory_knowledge_compaction_prompt ?? ""}
                    onChange={(v) => patch("memory_knowledge_compaction_prompt", v || undefined)}
                    label="Memory Phase Prompt"
                    placeholder={form.compaction_prompt_template_id ? "Using linked template..." : "Leave blank to use the global default..."}
                    helpText="REPLACES the default prompt. Before each compaction, the bot gets this prompt with the conversation and can use tools (save_memory, save_knowledge, etc.) to preserve important info before archival. Tags like @tool:save_memory auto-pin tools. Default: 'Decide if there is anything to store in memory, knowledge, or persona.'"
                    rows={5}
                    generateContext="A prompt that runs before context compaction. The AI reviews the conversation and decides what to save to long-term memory, knowledge base, or persona using tools (save_memory, save_knowledge, etc.) before old messages are archived."
                  />
                </>
              )}
            </>
          )}

          {/* Backfill subsection */}
          <div style={{
            marginTop: 8, padding: "10px 14px", background: "#1a1117",
            border: "1px solid #5b2333", borderRadius: 8,
            fontSize: 11, color: "#d4a0a0", lineHeight: "1.5",
          }}>
            <AlertTriangle size={12} color="#f59e0b" style={{ display: "inline", verticalAlign: "middle", marginRight: 6 }} />
            Backfill makes one LLM call per chunk of messages plus one for the executive summary. For example,
            500 messages at chunk size 50 = ~11 LLM calls using your compaction model. Set your interval and keep
            turns first. Re-running will delete existing sections and re-chunk from scratch.
          </div>
          <BackfillButton channelId={channelId} historyMode={selected} />
          <SectionsViewer channelId={channelId} />
        </Section>
      ) : (
        <Section title="Compaction" description="Manages long conversations by periodically summarizing old turns.">
          <Toggle
            value={form.context_compaction ?? true}
            onChange={(v) => patch("context_compaction", v)}
            label="Enable auto-compaction"
          />
          {form.context_compaction && (
            <>
              <div style={{
                padding: "14px 16px", background: "#0d1117", border: "1px solid #1e3a5f",
                borderRadius: 8, marginBottom: 4,
              }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#93c5fd", marginBottom: 8 }}>How Compaction Works</div>
                <div style={{ fontSize: 11, color: "#8b949e", lineHeight: "1.6" }}>
                  After every <strong style={{ color: "#e5e5e5" }}>Interval</strong> user turns, the oldest messages
                  are archived and summarized by an LLM. The most recent <strong style={{ color: "#e5e5e5" }}>Keep Turns</strong> are
                  always preserved verbatim. If memory/knowledge/persona is enabled, the bot gets a "last chance" pass
                  to save important information before summarization.
                </div>
                <div style={{ fontSize: 11, color: "#8b949e", lineHeight: "1.6", marginTop: 8 }}>
                  <strong style={{ color: "#e5e5e5" }}>Example:</strong> Interval=30, Keep Turns=10 → after 30 user messages,
                  the oldest 20 are summarized. The bot always sees the last 10 turns plus the summary.
                </div>
              </div>

              <Row>
                <Col>
                  <FormRow label="Interval (user turns)" description="Compaction triggers after this many user messages accumulate. Lower = more frequent, tighter context. Default: 30.">
                    <TextInput
                      value={form.compaction_interval?.toString() ?? ""}
                      onChangeText={(v) => patch("compaction_interval", v ? parseInt(v) || undefined : undefined)}
                      placeholder="default (30)"
                      type="number"
                    />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Keep Turns" description="Recent turns always kept verbatim — never summarized. Higher = more immediate context but less room for RAG/tools. Default: 10.">
                    <TextInput
                      value={form.compaction_keep_turns?.toString() ?? ""}
                      onChangeText={(v) => patch("compaction_keep_turns", v ? parseInt(v) || undefined : undefined)}
                      placeholder="default (10)"
                      type="number"
                    />
                  </FormRow>
                </Col>
              </Row>

              <div style={{
                padding: "12px 14px", background: "#111", border: "1px solid #333",
                borderRadius: 8, display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "#999" }}>Quick Guide</div>
                <div style={{ fontSize: 11, color: "#777", lineHeight: "1.5" }}>
                  <strong style={{ color: "#bbb" }}>Casual chatbot:</strong> Interval 20, Keep 6 — compacts often, keeps things lean.
                </div>
                <div style={{ fontSize: 11, color: "#777", lineHeight: "1.5" }}>
                  <strong style={{ color: "#bbb" }}>Project assistant:</strong> Interval 30, Keep 10 — balanced, good for task tracking.
                </div>
                <div style={{ fontSize: 11, color: "#777", lineHeight: "1.5" }}>
                  <strong style={{ color: "#bbb" }}>Long-running agent:</strong> Interval 40+, Keep 12 — more raw context, fewer compaction LLM calls.
                </div>
                <div style={{ fontSize: 11, color: "#f59e0b", lineHeight: "1.5", marginTop: 4 }}>
                  Keep Turns must be less than Interval — otherwise nothing gets summarized.
                </div>
              </div>

              <LlmModelDropdown
                label="Compaction Model"
                value={form.compaction_model ?? ""}
                onChange={(v) => patch("compaction_model", v || undefined)}
                placeholder="inherit (bot model)"
              />
              <div style={{ fontSize: 10, color: "#666", marginTop: -4, marginBottom: 4 }}>
                Used for summarization. A cheap/fast model works well — the prompts are straightforward.
              </div>

              {/* Memory phase toggle + prompt */}
              <Toggle
                value={!!form.compaction_skip_memory_phase}
                onChange={(v) => patch("compaction_skip_memory_phase", v || undefined)}
                label="Skip memory phase"
              />
              <div style={{ fontSize: 10, color: "#666", marginTop: -4, marginBottom: 4 }}>
                Skips the extra LLM call that lets the bot save memories/knowledge before summarization.
                Enable this if you use heartbeat or another mechanism to persist memories.
              </div>

              {!form.compaction_skip_memory_phase && (
                <>
                  <WorkspaceFilePrompt
                    workspaceId={(form.compaction_workspace_id as string) ?? workspaceId}
                    filePath={form.compaction_workspace_file_path ?? null}
                    onLink={(path) => { patch("compaction_workspace_file_path", path); patch("compaction_workspace_id", workspaceId); }}
                    onUnlink={() => { patch("compaction_workspace_file_path", undefined); patch("compaction_workspace_id", undefined); }}
                  />
                  {!form.compaction_workspace_file_path && (
                    <>
                      <PromptTemplateLink
                        templateId={form.compaction_prompt_template_id ?? null}
                        onLink={(id) => patch("compaction_prompt_template_id", id)}
                        onUnlink={() => patch("compaction_prompt_template_id", undefined)}
                      />
                      <LlmPrompt
                        value={form.memory_knowledge_compaction_prompt ?? ""}
                        onChange={(v) => patch("memory_knowledge_compaction_prompt", v || undefined)}
                        label="Memory Phase Prompt"
                        placeholder={form.compaction_prompt_template_id ? "Using linked template..." : "Leave blank to use the global default..."}
                        helpText="REPLACES the default prompt. Before each compaction, the bot gets this prompt and can use tools to preserve important info before summarization. Default: 'Decide if there is anything to store in memory, knowledge, or persona.'"
                        rows={5}
                        generateContext="A prompt that runs before context compaction. The AI reviews the conversation and decides what to save to long-term memory, knowledge base, or persona using tools (save_memory, save_knowledge, etc.) before old messages are archived."
                      />
                    </>
                  )}
                </>
              )}
            </>
          )}
        </Section>
      )}

      {/* 3. Response Condensing — always visible */}
      <Section title="Response Condensing" description="Condense verbose assistant responses to save context. Values here override the global defaults in Settings.">
        <Toggle
          value={!!form.response_condensing_enabled}
          onChange={(v) => patch("response_condensing_enabled", v)}
          label="Enable response condensing"
        />
        {form.response_condensing_enabled && (
          <>
            <div style={{
              padding: "10px 14px", background: "#0d1117", border: "1px solid #1e3a5f",
              borderRadius: 8, fontSize: 11, color: "#8b949e", lineHeight: "1.6", marginBottom: 4,
            }}>
              Condensing runs in the background after each response.
              User messages are never modified. The bot sees condensed versions
              of older assistant messages, but full versions of the most recent ones.
            </div>
            <Row>
              <Col>
                <FormRow label="Threshold (chars)" description="Responses above this length are condensed.">
                  <TextInput
                    value={form.response_condensing_threshold?.toString() ?? ""}
                    onChangeText={(v) => patch("response_condensing_threshold", v ? parseInt(v) || undefined : undefined)}
                    placeholder="inherit from global settings"
                    type="number"
                  />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="Keep Exact" description="Recent messages shown at full fidelity.">
                  <TextInput
                    value={form.response_condensing_keep_exact?.toString() ?? ""}
                    onChangeText={(v) => patch("response_condensing_keep_exact", v ? parseInt(v) || undefined : undefined)}
                    placeholder="inherit from global settings"
                    type="number"
                  />
                </FormRow>
              </Col>
            </Row>
            <LlmModelDropdown
              label="Condensing Model"
              value={form.response_condensing_model ?? ""}
              onChange={(v) => patch("response_condensing_model", v || undefined)}
              placeholder="inherit from global settings"
            />
            <LlmPrompt
              value={form.response_condensing_prompt ?? ""}
              onChange={(v) => patch("response_condensing_prompt", v || undefined)}
              label="Custom Condensing Prompt"
              placeholder="Leave blank to inherit from global settings..."
              helpText="Overrides the global default prompt. Leave empty to use the prompt set in Settings > Response Condensing."
              rows={3}
              generateContext="A system prompt for condensing verbose assistant responses. Should preserve specific values, decisions, code, file paths, commands, and action items while removing verbose explanations and filler. Target ~30% of original length."
            />
          </>
        )}
      </Section>

    </>
  );
}

// ===========================================================================
// General Tab — settings form
// ===========================================================================
function GeneralTab({ form, patch, bots, settings, elevationData, workspaceId, channelId }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  bots: any[] | undefined;
  settings: ChannelSettings;
  elevationData: any;
  workspaceId?: string | null;
  channelId: string;
}) {
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
        <FormRow label="Fallback Model" description="Used when the primary model fails after retries. Leave empty to inherit from bot.">
          <LlmModelDropdown
            value={form.fallback_model ?? ""}
            onChange={(v) => {
              patch("fallback_model", v || undefined);
              if (!v) patch("fallback_model_provider_id", undefined);
            }}
            placeholder="inherit (from bot)"
            allowClear
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
        <FormRow label="Max iterations">
          <TextInput
            value={form.max_iterations?.toString() ?? ""}
            onChangeText={(v) => patch("max_iterations", v ? parseInt(v) || undefined : undefined)}
            placeholder="default"
            type="number"
          />
        </FormRow>
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

      <Section title="Model Elevation" description="Per-channel elevation overrides. Leave blank to inherit.">
        <Row>
          <Col>
            <FormRow label="Enable Elevation">
              <SelectInput
                value={triStateValue(form.elevation_enabled)}
                onChange={(v) => patch("elevation_enabled", triStateParse(v))}
                options={triStateOptions}
              />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Threshold (0.0–1.0)">
              <TextInput
                value={form.elevation_threshold?.toString() ?? ""}
                onChangeText={(v) => patch("elevation_threshold", v ? parseFloat(v) || undefined : undefined)}
                placeholder="inherit"
                type="number"
              />
            </FormRow>
          </Col>
        </Row>
        <LlmModelDropdown
          label="Elevated Model"
          value={form.elevated_model ?? ""}
          onChange={(v) => patch("elevated_model", v || undefined)}
          placeholder="inherit"
        />

        {/* Elevation observability */}
        {elevationData && (
          <>
            <div style={{
              display: "flex", gap: 16, flexWrap: "wrap", marginTop: 12,
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

            <div style={{ fontSize: 13, fontWeight: 600, color: "#ccc", marginTop: 8 }}>Recent Decisions</div>
            {elevationData.recent.length === 0 ? (
              <div style={{ fontSize: 12, color: "#666", fontStyle: "italic" }}>No elevation decisions recorded yet.</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {elevationData.recent.map((entry: any) => (
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
      </Section>

      {/* Metadata */}
      <div style={{ opacity: 0.4, fontSize: 11, color: "#666", display: "flex", gap: 16 }}>
        <span>ID: {settings.id}</span>
        {settings.client_id && <span>client_id: {settings.client_id}</span>}
        {settings.integration && <span>integration: {settings.integration}</span>}
      </div>

      {/* Danger Zone */}
      <div style={{
        marginTop: 32,
        border: "1px solid #7f1d1d",
        borderRadius: 8,
        overflow: "hidden",
      }}>
        <div style={{
          padding: "10px 14px",
          background: "#7f1d1d33",
          borderBottom: "1px solid #7f1d1d",
        }}>
          <Text style={{ fontSize: 13, fontWeight: "700", color: "#fca5a5" }}>Danger Zone</Text>
        </div>
        <div style={{ padding: 16 }}>
          {!showDeleteConfirm ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <Text style={{ fontSize: 13, color: "#e5e5e5", fontWeight: "600" }}>Delete this channel</Text>
                <Text style={{ fontSize: 11, color: "#888", marginTop: 2 }}>
                  Permanently removes the channel, its integrations, and heartbeat config. Sessions and tasks will be unlinked.
                </Text>
              </div>
              <button
                onClick={() => setShowDeleteConfirm(true)}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "8px 16px", fontSize: 12, fontWeight: 600,
                  border: "1px solid #991b1b", borderRadius: 6,
                  background: "transparent", color: "#fca5a5", cursor: "pointer",
                  flexShrink: 0, marginLeft: 16,
                }}
              >
                <Trash2 size={13} color="#fca5a5" />
                Delete Channel
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "10px 14px", background: "#7f1d1d44", borderRadius: 6,
              }}>
                <AlertTriangle size={16} color="#fca5a5" />
                <Text style={{ fontSize: 12, color: "#fca5a5", fontWeight: "600" }}>
                  This action cannot be undone.
                </Text>
              </div>
              <Text style={{ fontSize: 12, color: "#999" }}>
                Type <Text style={{ fontFamily: "monospace", color: "#fca5a5", fontWeight: "600" }}>delete</Text> to confirm:
              </Text>
              <input
                type="text"
                value={deleteConfirmText}
                onChange={(e: any) => setDeleteConfirmText(e.target.value)}
                placeholder="delete"
                style={{
                  padding: "8px 12px", fontSize: 13,
                  background: "#111", border: "1px solid #333", borderRadius: 6,
                  color: "#e5e5e5", outline: "none",
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
                    background: deleteConfirmText === "delete" ? "#dc2626" : "#333",
                    color: deleteConfirmText === "delete" ? "#fff" : "#666",
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
                    border: "1px solid #333", borderRadius: 6,
                    background: "transparent", color: "#999", cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </div>
              {deleteMutation.isError && (
                <Text style={{ fontSize: 11, color: "#fca5a5" }}>
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

// ===========================================================================
// Integrations Tab
// ===========================================================================
function IntegrationsTab({ channelId }: { channelId: string }) {
  const { data: bindings, isLoading } = useChannelIntegrations(channelId);
  const { data: availableTypes } = useAvailableIntegrations();
  const bindMutation = useBindIntegration(channelId);
  const unbindMutation = useUnbindIntegration(channelId);

  const [showAdd, setShowAdd] = useState(false);
  const [newType, setNewType] = useState("");
  const [newClientId, setNewClientId] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");

  const handleBind = async () => {
    if (!newType || !newClientId.trim()) return;
    await bindMutation.mutateAsync({
      integration_type: newType,
      client_id: newClientId.trim(),
      display_name: newDisplayName.trim() || undefined,
    });
    setShowAdd(false);
    setNewType("");
    setNewClientId("");
    setNewDisplayName("");
  };

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;

  return (
    <>
      <Section title="Integration Bindings">
        {(!bindings || bindings.length === 0) ? (
          <EmptyState message="No integrations bound to this channel" />
        ) : (
          <View className="gap-2">
            {bindings.map((b) => (
              <View key={b.id} className="flex-row items-center gap-3 bg-surface-raised border border-surface-border rounded-lg px-3 py-2">
                <Text className="text-accent text-xs font-semibold bg-accent/15 px-2 py-0.5 rounded">
                  {b.integration_type}
                </Text>
                <View className="flex-1 min-w-0">
                  <Text className="text-text text-sm" numberOfLines={1}>{b.client_id}</Text>
                  {b.display_name && (
                    <Text className="text-text-muted text-xs" numberOfLines={1}>{b.display_name}</Text>
                  )}
                </View>
                <Pressable
                  onPress={() => unbindMutation.mutate(b.id)}
                  className="p-1 rounded hover:bg-surface-overlay"
                >
                  <X size={14} color="#ef4444" />
                </Pressable>
              </View>
            ))}
          </View>
        )}
      </Section>

      {!showAdd ? (
        <Pressable
          onPress={() => {
            setShowAdd(true);
            if (availableTypes?.length && !newType) setNewType(availableTypes[0]);
          }}
          className="flex-row items-center gap-2 px-3 py-2"
        >
          <Plus size={14} color="#3b82f6" />
          <Text className="text-accent text-sm font-medium">Add Integration</Text>
        </Pressable>
      ) : (
        <Section title="Add Integration">
          <View className="gap-3">
            <FormRow label="Type">
              <SelectInput
                value={newType}
                onChange={setNewType}
                options={(availableTypes ?? []).map((t) => ({ label: t, value: t }))}
              />
            </FormRow>
            <FormRow label="Client ID">
              <TextInput
                value={newClientId}
                onChangeText={setNewClientId}
                placeholder="slack:C01ABC123"
              />
            </FormRow>
            <FormRow label="Display Name (optional)">
              <TextInput
                value={newDisplayName}
                onChangeText={setNewDisplayName}
                placeholder="#general"
              />
            </FormRow>
            <View className="flex-row gap-2">
              <Pressable
                onPress={handleBind}
                disabled={!newType || !newClientId.trim() || bindMutation.isPending}
                style={{
                  backgroundColor: newType && newClientId.trim() ? "#3b82f6" : "#333",
                  paddingHorizontal: 14,
                  paddingVertical: 7,
                  borderRadius: 8,
                }}
              >
                <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>
                  {bindMutation.isPending ? "Binding..." : "Bind"}
                </Text>
              </Pressable>
              <Pressable
                onPress={() => setShowAdd(false)}
                className="px-3 py-1.5 rounded-lg hover:bg-surface-overlay"
              >
                <Text className="text-text-muted text-sm">Cancel</Text>
              </Pressable>
            </View>
            {bindMutation.isError && (
              <Text className="text-red-400 text-xs">
                {bindMutation.error instanceof Error ? bindMutation.error.message : "Failed to bind"}
              </Text>
            )}
          </View>
        </Section>
      )}
    </>
  );
}


// ===========================================================================
// Sessions Tab
// ===========================================================================
function SessionsTab({ channelId }: { channelId: string }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-sessions", channelId],
    queryFn: async () => {
      const res = await apiFetch<{ sessions: any[] }>(`/api/v1/admin/channels/${channelId}/sessions`);
      return res.sessions;
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/channels/${channelId}/reset`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-sessions", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });

  const switchMutation = useMutation({
    mutationFn: (sessionId: string) =>
      apiFetch(`/api/v1/channels/${channelId}/switch-session`, {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-sessions", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;

  return (
    <>
      {/* Actions bar */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button
          onClick={() => resetMutation.mutate()}
          disabled={resetMutation.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 14px", fontSize: 12, fontWeight: 600,
            border: "none", cursor: "pointer", borderRadius: 6,
            background: "#3b82f6", color: "#fff",
          }}
        >
          <RotateCw size={12} />
          {resetMutation.isPending ? "Resetting..." : "New Session"}
        </button>
        <span style={{ fontSize: 11, color: "#555", alignSelf: "center" }}>
          {data?.length ?? 0} session{data?.length !== 1 ? "s" : ""}
        </span>
      </div>

      {!data?.length ? (
        <EmptyState message="No sessions yet." />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {data.map((s: any) => (
            <div key={s.id} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "10px 12px", background: s.is_active ? "#0d1a0d" : "#1a1a1a",
              borderRadius: 8, border: `1px solid ${s.is_active ? "#1a3a1a" : "#2a2a2a"}`,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 12, color: "#e5e5e5", fontFamily: "monospace" }}>
                    {s.id?.substring(0, 12)}...
                  </span>
                  {s.title && (
                    <span style={{ fontSize: 12, color: "#999", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.title}
                    </span>
                  )}
                  {s.is_active && (
                    <span style={{ fontSize: 9, background: "#166534", color: "#86efac", padding: "1px 6px", borderRadius: 3, fontWeight: 700 }}>
                      ACTIVE
                    </span>
                  )}
                  {s.locked && (
                    <span style={{ fontSize: 9, background: "#7f1d1d", color: "#fca5a5", padding: "1px 6px", borderRadius: 3, fontWeight: 700 }}>
                      LOCKED
                    </span>
                  )}
                  {s.depth > 0 && (
                    <span style={{ fontSize: 9, background: "#333", color: "#999", padding: "1px 6px", borderRadius: 3 }}>
                      depth {s.depth}
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#666", marginTop: 3 }}>
                  <span>{s.message_count ?? 0} msgs</span>
                  {s.last_active && <span>{new Date(s.last_active).toLocaleString()}</span>}
                  {s.created_at && <span>created {new Date(s.created_at).toLocaleDateString()}</span>}
                </div>
              </div>
              <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                {!s.is_active && (
                  <button
                    onClick={() => switchMutation.mutate(s.id)}
                    disabled={switchMutation.isPending}
                    style={{
                      padding: "4px 10px", fontSize: 10, fontWeight: 600,
                      border: "1px solid #333", borderRadius: 4, cursor: "pointer",
                      background: "transparent", color: "#86efac",
                    }}
                    title="Switch to this session"
                  >
                    Activate
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ===========================================================================
// Heartbeat Tab
// ===========================================================================
function HeartbeatTab({ channelId, workspaceId }: { channelId: string; workspaceId?: string | null }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-heartbeat", channelId],
    queryFn: () => apiFetch<any>(`/api/v1/admin/channels/${channelId}/heartbeat`),
  });

  const [hbForm, setHbForm] = useState<any>(null);
  const [hbSaved, setHbSaved] = useState(false);

  useEffect(() => {
    if (data?.config) {
      setHbForm({
        interval_minutes: data.config.interval_minutes ?? 60,
        model: data.config.model ?? "",
        model_provider_id: data.config.model_provider_id ?? "",
        prompt: data.config.prompt ?? "",
        dispatch_results: data.config.dispatch_results ?? true,
        trigger_response: data.config.trigger_response ?? false,
        prompt_template_id: data.config.prompt_template_id ?? null,
        workspace_file_path: data.config.workspace_file_path ?? null,
        workspace_id: data.config.workspace_id ?? null,
      });
    } else if (data && !data.config) {
      setHbForm({
        interval_minutes: 60,
        model: "",
        model_provider_id: "",
        prompt: "",
        dispatch_results: true,
        trigger_response: false,
        prompt_template_id: null,
        workspace_file_path: null,
        workspace_id: null,
      });
    }
  }, [data]);

  const toggleMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat/toggle`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] }),
  });

  const saveMutation = useMutation({
    mutationFn: (body: any) => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] });
      setHbSaved(true);
      setTimeout(() => setHbSaved(false), 2500);
    },
  });

  const fireMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat/fire`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] }),
  });

  if (isLoading || !hbForm) return <ActivityIndicator color="#3b82f6" />;

  const enabled = data?.config?.enabled ?? false;

  return (
    <>
      {/* Enable toggle + save */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Section title="Heartbeat">
          <div />
        </Section>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => toggleMutation.mutate()}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", borderRadius: 8, fontSize: 13, fontWeight: 500, border: "none", cursor: "pointer",
              background: enabled ? "#166534" : "#333",
              color: enabled ? "#86efac" : "#999",
            }}
          >
            <span style={{
              width: 8, height: 8, borderRadius: 4,
              background: enabled ? "#86efac" : "#666",
            }} />
            {enabled ? "Enabled" : "Disabled"}
          </button>
        </div>
      </div>

      <div style={{ opacity: enabled ? 1 : 0.5 }}>
        <Row>
          <Col>
            <FormRow label="Interval">
              <SelectInput
                value={hbForm.interval_minutes?.toString() ?? "60"}
                onChange={(v) => setHbForm((f: any) => ({ ...f, interval_minutes: parseInt(v) }))}
                options={INTERVAL_OPTIONS}
              />
            </FormRow>
          </Col>
          <Col>
            <LlmModelDropdown
              label="Model"
              value={hbForm.model ?? ""}
              onChange={(v) => setHbForm((f: any) => ({ ...f, model: v }))}
              placeholder="Select model..."
            />
          </Col>
        </Row>

        <div style={{ marginTop: 16 }}>
          <WorkspaceFilePrompt
            workspaceId={hbForm.workspace_id ?? workspaceId}
            filePath={hbForm.workspace_file_path}
            onLink={(path) => setHbForm((f: any) => ({ ...f, workspace_file_path: path, workspace_id: workspaceId }))}
            onUnlink={() => setHbForm((f: any) => ({ ...f, workspace_file_path: null, workspace_id: null }))}
          />
          {!hbForm.workspace_file_path && (
            <>
              <PromptTemplateLink
                templateId={hbForm.prompt_template_id ?? null}
                onLink={(id) => setHbForm((f: any) => ({ ...f, prompt_template_id: id }))}
                onUnlink={() => setHbForm((f: any) => ({ ...f, prompt_template_id: null }))}
              />
              <LlmPrompt
                value={hbForm.prompt ?? ""}
                onChange={(v) => setHbForm((f: any) => ({ ...f, prompt: v }))}
                label="Heartbeat Prompt"
                placeholder={hbForm.prompt_template_id ? "Using linked template..." : "Enter the heartbeat prompt..."}
                helpText="This prompt runs on the configured interval. Use @-tags to reference skills or tools."
                rows={10}
                generateContext="A prompt for a scheduled/periodic AI task. Runs on a timer. The AI can check on things, perform maintenance, proactively engage, or run recurring workflows. Supports @-tags for tools and skills."
              />
            </>
          )}
        </div>

        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
          <Toggle
            value={hbForm.dispatch_results ?? true}
            onChange={(v) => setHbForm((f: any) => ({ ...f, dispatch_results: v }))}
            label="Post results to channel"
          />
          <Toggle
            value={hbForm.trigger_response ?? false}
            onChange={(v) => setHbForm((f: any) => ({ ...f, trigger_response: v }))}
            label="Trigger agent response after posting"
            description="After posting the heartbeat result, the bot will process it and respond again."
          />
        </div>

        <div style={{ marginTop: 20, display: "flex", gap: 8 }}>
          <button
            onClick={() => saveMutation.mutate(hbForm)}
            style={{
              padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer",
              background: hbSaved ? "rgba(34,197,94,0.15)" : "#3b82f6",
              color: hbSaved ? "#22c55e" : "#fff",
              fontSize: 13, fontWeight: 600,
            }}
          >
            {hbSaved ? "Saved!" : saveMutation.isPending ? "Saving..." : "Save Heartbeat"}
          </button>
          <button
            onClick={() => fireMutation.mutate()}
            disabled={!hbForm.prompt && !hbForm.prompt_template_id && !hbForm.workspace_file_path}
            style={{
              padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer",
              background: (hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path) ? "#92400e" : "#333",
              color: (hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path) ? "#fcd34d" : "#666",
              fontSize: 13, fontWeight: 500,
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            <Play size={12} color={(hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path) ? "#fcd34d" : "#666"} />
            Run Now
          </button>
        </div>
      </div>

      {/* Status + History */}
      {data?.config && (
        <div style={{ marginTop: 24, borderTop: "1px solid #333", paddingTop: 16 }}>
          <div style={{ fontSize: 12, color: "#666", display: "flex", gap: 16, marginBottom: 12 }}>
            {data.config.last_run_at && (
              <span>Last run: <span style={{ color: "#999" }}>{new Date(data.config.last_run_at).toLocaleString()}</span></span>
            )}
            {data.config.next_run_at && enabled && (
              <span>Next run: <span style={{ color: "#999" }}>{new Date(data.config.next_run_at).toLocaleString()}</span></span>
            )}
          </div>

          {data.history?.length > 0 && (
            <>
              <div style={{ fontSize: 10, fontWeight: 600, color: "#666", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 8 }}>
                Recent Runs
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {data.history.map((t: any) => (
                  <div key={t.id} style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "8px 12px", background: "#1a1a1a", borderRadius: 6, border: "1px solid #2a2a2a",
                  }}>
                    <div style={{ fontSize: 12, color: "#999" }}>
                      {new Date(t.created_at).toLocaleString()}
                    </div>
                    <span style={{
                      fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
                      background: t.status === "complete" ? "#166534" : t.status === "failed" ? "#7f1d1d" : "#333",
                      color: t.status === "complete" ? "#86efac" : t.status === "failed" ? "#fca5a5" : "#999",
                    }}>
                      {t.status}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}

// ===========================================================================
// Tasks Tab
// ===========================================================================
function TasksTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-tasks", channelId],
    queryFn: () => apiFetch<{ tasks: any[] }>(`/api/v1/admin/channels/${channelId}/tasks`),
  });
  const tasks = data?.tasks ?? [];

  type EditorState =
    | { mode: "closed" }
    | { mode: "create" }
    | { mode: "edit"; taskId: string };

  const [editorState, setEditorState] = useState<EditorState>({ mode: "closed" });

  const statusColors: Record<string, { bg: string; fg: string }> = {
    pending: { bg: "#333", fg: "#999" },
    running: { bg: "#1e3a5f", fg: "#93c5fd" },
    complete: { bg: "#166534", fg: "#86efac" },
    failed: { bg: "#7f1d1d", fg: "#fca5a5" },
    active: { bg: "#92400e", fg: "#fcd34d" },
    cancelled: { bg: "#333", fg: "#666" },
  };

  const handleEditorSaved = () => {
    setEditorState({ mode: "closed" });
    queryClient.invalidateQueries({ queryKey: ["channel-tasks", channelId] });
  };

  const editorOpen = editorState.mode !== "closed";
  const editorTaskId = editorState.mode === "edit" ? editorState.taskId : null;

  return (
    <>
      <Section title={`Tasks (${tasks.length})`} action={
        <button
          onClick={() => setEditorState({ mode: "create" })}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "4px 12px", fontSize: 11, fontWeight: 600,
            border: "none", cursor: "pointer", borderRadius: 6,
            background: "#3b82f6", color: "#fff",
          }}
        >
          <Plus size={12} />
          New Task
        </button>
      }>
        {isLoading ? (
          <ActivityIndicator color="#3b82f6" />
        ) : !tasks.length ? (
          <EmptyState message="No tasks yet." />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {tasks.map((t: any) => {
              const sc = statusColors[t.status] || statusColors.pending;
              return (
                <div
                  key={t.id}
                  onClick={() => setEditorState({ mode: "edit", taskId: t.id })}
                  style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "10px 12px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
                    cursor: "pointer",
                  }}
                >
                  <div>
                    <div style={{ fontSize: 12, color: "#e5e5e5", fontFamily: "monospace" }}>
                      {t.id?.substring(0, 12)}...
                    </div>
                    <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>
                      {t.dispatch_type || "none"} · {new Date(t.created_at).toLocaleString()}
                    </div>
                    {t.prompt && (
                      <div style={{ fontSize: 11, color: "#888", marginTop: 4, maxWidth: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {t.prompt.substring(0, 100)}
                      </div>
                    )}
                  </div>
                  <span style={{
                    fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
                    background: sc.bg, color: sc.fg,
                  }}>
                    {t.status}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {editorOpen && (
        <TaskEditorShared
          taskId={editorTaskId}
          onClose={() => setEditorState({ mode: "closed" })}
          onSaved={handleEditorSaved}
          defaultChannelId={channelId}
          defaultBotId={botId}
          extraQueryKeysToInvalidate={[["channel-tasks", channelId]]}
        />
      )}
    </>
  );
}

// ===========================================================================
// Context Tab
// ===========================================================================

const CATEGORY_COLORS: Record<string, { bar: string; dot: string }> = {
  static:       { bar: "#3b82f6", dot: "#60a5fa" },
  rag:          { bar: "#22c55e", dot: "#4ade80" },
  conversation: { bar: "#f59e0b", dot: "#fbbf24" },
  compaction:   { bar: "#a855f7", dot: "#c084fc" },
};

const SOURCE_BADGE_COLORS: Record<string, { bg: string; fg: string }> = {
  channel: { bg: "#1e3a5f", fg: "#93c5fd" },
  bot:     { bg: "#365314", fg: "#bef264" },
  global:  { bg: "#333",    fg: "#999"    },
};

// ---------------------------------------------------------------------------
// Workspace override tab
// ---------------------------------------------------------------------------
function WorkspaceOverrideTab({
  form,
  patch,
  workspaceId,
  channelId,
  onSave,
  saving,
  saved,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  workspaceId?: string | null;
  channelId: string;
  onSave: () => void;
  saving: boolean;
  saved: boolean;
}) {
  return (
    <>
      <Section title="Workspace Skills" description="Override the workspace-level skill injection setting for this channel.">
        <FormRow label="Skills injection" description="null = inherit from workspace, on/off = override">
          <SelectInput
            value={form.workspace_skills_enabled === null || form.workspace_skills_enabled === undefined ? "inherit" : form.workspace_skills_enabled ? "on" : "off"}
            options={[
              { label: "Inherit from workspace", value: "inherit" },
              { label: "Enabled", value: "on" },
              { label: "Disabled", value: "off" },
            ]}
            onChange={(v) => patch("workspace_skills_enabled" as any, v === "inherit" ? null : v === "on")}
          />
        </FormRow>
        <div style={{ fontSize: 11, color: "#666", padding: "4px 0" }}>
          When enabled, skill .md files from the workspace filesystem are discovered and injected into the bot's context by mode (pinned/rag/on-demand).
        </div>
        {workspaceId && (
          <div style={{ marginTop: 8 }}>
            <button
              onClick={async () => {
                try {
                  const data = await apiFetch<{ embedded?: number; unchanged?: number; errors?: number }>(
                    `/api/v1/workspaces/${workspaceId}/reindex-skills`,
                    { method: "POST" },
                  );
                  alert(`Reindexed: ${data.embedded || 0} embedded, ${data.unchanged || 0} unchanged, ${data.errors || 0} errors`);
                } catch (e) {
                  alert("Failed to reindex skills");
                }
              }}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "5px 12px", fontSize: 11, fontWeight: 600,
                border: "1px solid #333", borderRadius: 5,
                background: "transparent", color: "#999", cursor: "pointer",
              }}
            >
              <RotateCw size={11} /> Reindex Skills
            </button>
          </div>
        )}
      </Section>

      <Section title="Workspace Base Prompt" description="Override the workspace-level base prompt setting for this channel.">
        <FormRow label="Base prompt override" description="null = inherit from workspace, on/off = override">
          <SelectInput
            value={form.workspace_base_prompt_enabled === null || form.workspace_base_prompt_enabled === undefined ? "inherit" : form.workspace_base_prompt_enabled ? "on" : "off"}
            options={[
              { label: "Inherit from workspace", value: "inherit" },
              { label: "Enabled", value: "on" },
              { label: "Disabled", value: "off" },
            ]}
            onChange={(v) => patch("workspace_base_prompt_enabled" as any, v === "inherit" ? null : v === "on")}
          />
        </FormRow>
        <div style={{ fontSize: 11, color: "#666", padding: "4px 0" }}>
          When enabled, <code>common/prompts/base.md</code> from the workspace replaces the global base prompt. Per-bot additions from <code>bots/&lt;bot-id&gt;/prompts/base.md</code> are concatenated after.
        </div>
      </Section>
    </>
  );
}


function ContextTab({ channelId }: { channelId: string }) {
  const { data, isLoading } = useChannelContextBreakdown(channelId);

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;
  if (!data) return <EmptyState message="No context data available." />;

  const legend = [
    { key: "static", label: "Static", color: CATEGORY_COLORS.static.bar },
    { key: "rag", label: "RAG", color: CATEGORY_COLORS.rag.bar },
    { key: "conversation", label: "Conversation", color: CATEGORY_COLORS.conversation.bar },
    { key: "compaction", label: "Compaction", color: CATEGORY_COLORS.compaction.bar },
  ];

  return (
    <>
      {/* Summary card */}
      <Section title="Summary">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
          {[
            ["Total Tokens", `~${data.total_tokens_approx.toLocaleString()}`],
            ["Total Chars", data.total_chars.toLocaleString()],
            ["Bot", data.bot_id],
            ["Session", data.session_id ? data.session_id.slice(0, 8) + "..." : "none"],
          ].map(([label, val]) => (
            <div key={String(label)} style={{
              padding: "12px 14px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
            }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: "#e5e5e5" }}>{val}</div>
              <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      </Section>

      {/* Stacked bar */}
      <Section title="Proportions">
        <div style={{ display: "flex", height: 28, borderRadius: 6, overflow: "hidden", background: "#1a1a1a" }}>
          {data.categories
            .filter((c) => c.percentage > 0)
            .map((c) => (
              <div
                key={c.key}
                title={`${c.label}: ${c.percentage}%`}
                style={{
                  width: `${c.percentage}%`,
                  background: CATEGORY_COLORS[c.category]?.bar || "#555",
                  minWidth: c.percentage > 0.5 ? 3 : 0,
                }}
              />
            ))}
        </div>
        <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
          {legend.map((l) => (
            <div key={l.key} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "#999" }}>
              <div style={{ width: 8, height: 8, borderRadius: 4, background: l.color }} />
              {l.label}
            </div>
          ))}
        </div>
      </Section>

      {/* Category list */}
      <Section title="Components">
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {data.categories.map((c) => (
            <div key={c.key} style={{
              display: "flex", alignItems: "center", gap: 12,
              padding: "10px 12px", background: "#1a1a1a", borderRadius: 6, border: "1px solid #2a2a2a",
            }}>
              <div style={{
                width: 8, height: 8, borderRadius: 4, flexShrink: 0,
                background: CATEGORY_COLORS[c.category]?.dot || "#555",
              }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#e5e5e5" }}>{c.label}</div>
                <div style={{ fontSize: 11, color: "#666", marginTop: 1 }}>{c.description}</div>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#e5e5e5" }}>~{c.tokens_approx.toLocaleString()} tok</div>
                <div style={{ fontSize: 11, color: "#666" }}>{c.percentage}%</div>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* Compaction state */}
      {data.compaction && (
        <Section title="Compaction">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
            {[
              ["Enabled", data.compaction.enabled ? "Yes" : "No"],
              ["Has Summary", data.compaction.has_summary ? `Yes (${data.compaction.summary_chars.toLocaleString()} chars)` : "No"],
              ["Total Messages", data.compaction.total_messages],
              ["Since Watermark", data.compaction.messages_since_watermark],
              ["Interval", data.compaction.compaction_interval],
              ["Keep Turns", data.compaction.compaction_keep_turns],
              ["Turns Until Next", data.compaction.turns_until_next ?? "N/A"],
            ].map(([label, val]) => (
              <div key={String(label)} style={{
                padding: "10px 12px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
              }}>
                <div style={{ fontSize: 16, fontWeight: 600, color: "#e5e5e5" }}>{String(val)}</div>
                <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Context compression (ephemeral, per-turn) */}
      {data.compression && (
        <Section title="Context Compression">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
            {[
              ["Enabled", data.compression.enabled ? "Yes" : "No"],
              ["Model", data.compression.model || "—"],
              ["Threshold", `${data.compression.threshold.toLocaleString()} chars`],
              ["Keep Turns", data.compression.keep_turns],
              ["Conv. Chars", data.compression.conversation_chars.toLocaleString()],
              ["Would Compress", data.compression.would_compress ? "Yes" : "No"],
            ].map(([label, val]) => (
              <div key={String(label)} style={{
                padding: "10px 12px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
              }}>
                <div style={{
                  fontSize: 16, fontWeight: 600,
                  color: label === "Would Compress" && data.compression.would_compress ? "#4ade80" : "#e5e5e5",
                }}>{String(val)}</div>
                <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, color: "#555", fontStyle: "italic", marginTop: 8 }}>
            Compression is ephemeral — it summarises older conversation via a cheap model each turn without modifying stored messages.
          </div>
        </Section>
      )}

      {/* RAG Re-ranking */}
      {data.reranking && (
        <Section title="RAG Re-ranking">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
            {[
              ["Enabled", data.reranking.enabled ? "Yes" : "No"],
              ["Model", data.reranking.model || "—"],
              ["Threshold", `${data.reranking.threshold_chars.toLocaleString()} chars`],
              ["Max Chunks", data.reranking.max_chunks],
              ["RAG Chars", data.reranking.total_rag_chars.toLocaleString()],
              ["Would Rerank", data.reranking.would_rerank ? "Yes" : "No"],
            ].map(([label, val]) => (
              <div key={String(label)} style={{
                padding: "10px 12px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
              }}>
                <div style={{
                  fontSize: 16, fontWeight: 600,
                  color: label === "Would Rerank" && data.reranking.would_rerank ? "#4ade80" : "#e5e5e5",
                }}>{String(val)}</div>
                <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, color: "#555", fontStyle: "italic", marginTop: 8 }}>
            Re-ranking uses an LLM to filter RAG chunks across all sources, keeping only the most relevant for the query.
          </div>
        </Section>
      )}

      {/* Effective settings */}
      {data.effective_settings && (
        <Section title="Effective Settings">
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {Object.entries(data.effective_settings).map(([key, setting]) => {
              const badge = SOURCE_BADGE_COLORS[setting.source] || SOURCE_BADGE_COLORS.global;
              return (
                <div key={key} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "8px 12px", background: "#1a1a1a", borderRadius: 6, border: "1px solid #2a2a2a",
                }}>
                  <span style={{ fontSize: 12, color: "#999", fontFamily: "monospace" }}>{key}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 12, color: "#e5e5e5" }}>{String(setting.value)}</span>
                    <span style={{
                      fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 4,
                      background: badge.bg, color: badge.fg,
                    }}>
                      {setting.source}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* Disclaimer */}
      <div style={{ fontSize: 11, color: "#555", fontStyle: "italic", marginTop: 4 }}>
        {data.disclaimer}
      </div>
    </>
  );
}

// ===========================================================================
// Compression Tab
// ===========================================================================
function CompressionTab({ channelId, form, patch }: {
  channelId: string;
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["channel-compression", channelId],
    queryFn: () => apiFetch<any>(`/api/v1/admin/channels/${channelId}/compression`),
  });

  const isFileMode = form.history_mode === "file" || form.history_mode === "structured";

  return (
    <>
      {/* Settings (moved from General tab) */}
      <Section title="Settings" description="Summarises old turns via a cheap model before each LLM call. Separate from compaction.">
        {isFileMode && (
          <div style={{
            padding: "10px 14px", background: "#111", border: "1px solid #333",
            borderRadius: 8, fontSize: 11, color: "#999", lineHeight: "1.5", marginBottom: 8,
          }}>
            With file mode, context compression is usually unnecessary — old turns are archived into sections.
          </div>
        )}
        <Row>
          <Col>
            <FormRow label="Enable Compression">
              <SelectInput
                value={triStateValue(form.context_compression)}
                onChange={(v) => patch("context_compression", triStateParse(v))}
                options={triStateOptions}
              />
            </FormRow>
          </Col>
          <Col>
            <LlmModelDropdown
              label="Compression Model"
              value={form.compression_model ?? ""}
              onChange={(v) => patch("compression_model", v || undefined)}
              placeholder="inherit"
            />
          </Col>
        </Row>
        <Row>
          <Col>
            <FormRow label="Trigger Threshold (chars)">
              <TextInput
                value={form.compression_threshold?.toString() ?? ""}
                onChangeText={(v) => patch("compression_threshold", v ? parseInt(v) || undefined : undefined)}
                placeholder="inherit (20000)"
                type="number"
              />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Keep Turns (verbatim)">
              <TextInput
                value={form.compression_keep_turns?.toString() ?? ""}
                onChangeText={(v) => patch("compression_keep_turns", v ? parseInt(v) || undefined : undefined)}
                placeholder="inherit (2)"
                type="number"
              />
            </FormRow>
          </Col>
        </Row>
        <LlmPrompt
          value={form.compression_prompt ?? ""}
          onChange={(v) => patch("compression_prompt", v || undefined)}
          label="Compression Prompt"
          placeholder="Leave blank to use the built-in default prompt..."
          helpText="Custom system prompt for the compression LLM. Overrides the hardcoded default."
          rows={5}
          generateContext="A system prompt for compressing conversation history into a shorter form. Should preserve important context, decisions, and facts while significantly reducing token count."
        />
      </Section>

      {/* Observability sections (from API) */}
      {isLoading ? (
        <ActivityIndicator color="#3b82f6" />
      ) : data ? (
        <>
          {data.effective_config && (
            <Section title="Effective Config">
              <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
                {Object.entries(data.effective_config).map(([k, v]) => (
                  <div key={k} style={{ fontSize: 12 }}>
                    <span style={{ color: "#666" }}>{k}: </span>
                    <span style={{ color: "#999" }}>{String(v ?? "—")}</span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {data.stats && (
            <Section title="Stats">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
                {[
                  ["Compressions", data.stats.total_compressions],
                  ["Chars Saved", data.stats.total_chars_saved?.toLocaleString()],
                  ["Msgs Saved", data.stats.total_msgs_saved],
                  ["Avg Reduction", data.stats.avg_reduction_pct ? `${data.stats.avg_reduction_pct.toFixed(0)}%` : "—"],
                ].map(([label, val]) => (
                  <div key={String(label)} style={{
                    padding: "12px 14px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
                  }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: "#e5e5e5" }}>{val ?? 0}</div>
                    <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>{label}</div>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {data.events?.length > 0 && (
            <Section title={`Recent Events (${data.events.length})`}>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {data.events.map((e: any) => (
                  <div key={e.id} style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "8px 12px", background: "#1a1a1a", borderRadius: 6, border: "1px solid #2a2a2a",
                    fontSize: 12,
                  }}>
                    <span style={{ color: "#999" }}>{new Date(e.created_at).toLocaleString()}</span>
                    <span style={{ color: "#666" }}>
                      {e.data?.original_chars ?? "?"} → {e.data?.compressed_chars ?? "?"} chars
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </>
      ) : (
        <EmptyState message="No compression data." />
      )}
    </>
  );
}

// ===========================================================================
// Logs Tab
// ===========================================================================

const LOG_TYPE_COLORS: Record<string, { bg: string; fg: string }> = {
  tool_call:            { bg: "#312e81", fg: "#a5b4fc" },
  memory_injection:     { bg: "#3b0764", fg: "#d8b4fe" },
  skill_context:        { bg: "#134e4a", fg: "#5eead4" },
  knowledge_context:    { bg: "#1e3a5f", fg: "#93c5fd" },
  tool_retrieval:       { bg: "#713f12", fg: "#fde047" },
  context_compressed:   { bg: "#365314", fg: "#bef264" },
  context_breakdown:    { bg: "#164e63", fg: "#67e8f9" },
  token_usage:          { bg: "#333",    fg: "#999"    },
  error:                { bg: "#7f1d1d", fg: "#fca5a5" },
  harness:              { bg: "#78350f", fg: "#fbbf24" },
  response:             { bg: "#166534", fg: "#86efac" },
};

function LogsTab({ channelId }: { channelId: string }) {
  const router = useRouter();
  const { data, isLoading } = useLogs({ channel_id: channelId, page_size: 20 });

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;
  if (!data?.rows?.length) return <EmptyState message="No log entries yet." />;

  return (
    <>
      <Section title={`Recent Logs (${data.rows.length} of ${data.total})`}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {data.rows.map((row: LogRow) => {
            const evType = row.kind === "tool_call" ? "tool_call" : row.event_type || "trace_event";
            const name = row.kind === "tool_call" ? row.tool_name : row.event_name || row.event_type;
            const c = LOG_TYPE_COLORS[evType] ?? { bg: "#333", fg: "#999" };
            return (
              <div
                key={row.id}
                onClick={() => row.correlation_id && router.push(`/admin/logs/${row.correlation_id}` as any)}
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "8px 12px", background: "#1a1a1a", borderRadius: 6, border: "1px solid #2a2a2a",
                  cursor: row.correlation_id ? "pointer" : "default",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <span style={{
                    fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 4,
                    background: c.bg, color: c.fg, whiteSpace: "nowrap", flexShrink: 0,
                  }}>
                    {evType}
                  </span>
                  <span style={{ fontSize: 12, color: "#e5e5e5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {name || "—"}
                  </span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                  <span style={{ fontSize: 10, color: "#555" }}>
                    {row.created_at ? new Date(row.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}
                  </span>
                  {row.correlation_id && (
                    <span style={{ fontSize: 10, color: "#444", fontFamily: "monospace" }}>
                      {row.correlation_id.substring(0, 8)}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      <Pressable
        onPress={() => router.push(`/admin/logs?channel_id=${channelId}` as any)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          alignSelf: "flex-start",
        }}
      >
        <Text style={{ fontSize: 13, color: "#3b82f6" }}>View all in Logs</Text>
        <ExternalLink size={12} color="#3b82f6" />
      </Pressable>
    </>
  );
}


// ===========================================================================
// Tools Override Tab
// ===========================================================================
type OverrideMode = "inherit" | "override" | "disabled";

const MODE_OPTIONS = [
  { label: "Inherit from bot", value: "inherit" },
  { label: "Override (whitelist)", value: "override" },
  { label: "Disable (blacklist)", value: "disabled" },
];

function ToolsOverrideTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const queryClient = useQueryClient();
  const { data: editorData, isLoading: editorLoading } = useBotEditorData(botId);
  const { data: settings } = useChannelSettings(channelId);
  const { data: effective } = useChannelEffectiveTools(channelId);
  const updateMutation = useUpdateChannelSettings(channelId);
  const [filter, setFilter] = useState("");
  const [saved, setSaved] = useState(false);

  // Derive current modes from settings
  const getMode = (overrideKey: string, disabledKey: string): OverrideMode => {
    if (!settings) return "inherit";
    const o = (settings as any)[overrideKey];
    const d = (settings as any)[disabledKey];
    if (o != null) return "override";
    if (d != null) return "disabled";
    return "inherit";
  };

  const localMode = getMode("local_tools_override", "local_tools_disabled");
  const mcpMode = getMode("mcp_servers_override", "mcp_servers_disabled");
  const clientMode = getMode("client_tools_override", "client_tools_disabled");

  // Get the list being edited for a category
  const getEditList = (mode: OverrideMode, overrideKey: string, disabledKey: string): string[] => {
    if (!settings) return [];
    if (mode === "override") return (settings as any)[overrideKey] || [];
    if (mode === "disabled") return (settings as any)[disabledKey] || [];
    return [];
  };

  const localList = getEditList(localMode, "local_tools_override", "local_tools_disabled");
  const mcpList = getEditList(mcpMode, "mcp_servers_override", "mcp_servers_disabled");
  const clientList = getEditList(clientMode, "client_tools_override", "client_tools_disabled");

  // Save helper
  const save = useCallback(async (patch: Partial<ChannelSettings>) => {
    setSaved(false);
    await updateMutation.mutateAsync(patch);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }, [updateMutation]);

  // Mode change handler
  const handleModeChange = useCallback((
    category: "local_tools" | "mcp_servers" | "client_tools",
    newMode: OverrideMode,
  ) => {
    const overrideKey = `${category}_override` as keyof ChannelSettings;
    const disabledKey = `${category}_disabled` as keyof ChannelSettings;
    const patch: any = {};
    if (newMode === "inherit") {
      patch[overrideKey] = null;
      patch[disabledKey] = null;
    } else if (newMode === "override") {
      patch[overrideKey] = [];
      patch[disabledKey] = null;
    } else {
      patch[overrideKey] = null;
      patch[disabledKey] = [];
    }
    save(patch);
  }, [save]);

  // Toggle a tool in override/disabled list
  const toggleTool = useCallback((
    category: "local_tools" | "mcp_servers" | "client_tools",
    mode: OverrideMode,
    currentList: string[],
    toolName: string,
  ) => {
    if (mode === "inherit") return;
    const key = mode === "override" ? `${category}_override` : `${category}_disabled`;
    const next = currentList.includes(toolName)
      ? currentList.filter((t) => t !== toolName)
      : [...currentList, toolName];
    save({ [key]: next } as any);
  }, [save]);

  // Toggle all tools in a group
  const toggleGroup = useCallback((
    category: "local_tools" | "mcp_servers" | "client_tools",
    mode: OverrideMode,
    currentList: string[],
    toolNames: string[],
  ) => {
    if (mode === "inherit") return;
    const key = mode === "override" ? `${category}_override` : `${category}_disabled`;
    const allIn = toolNames.every((n) => currentList.includes(n));
    const next = allIn
      ? currentList.filter((t) => !toolNames.includes(t))
      : [...new Set([...currentList, ...toolNames])];
    save({ [key]: next } as any);
  }, [save]);

  if (editorLoading) {
    return <ActivityIndicator size="small" color="#555" />;
  }

  if (!editorData) {
    return <EmptyState message="No bot editor data available" />;
  }

  const q = filter.toLowerCase();

  // Get all bot tool names for reference
  const allBotLocalTools = editorData.tool_groups.flatMap((g) =>
    g.packs.flatMap((p) => p.tools.map((t) => t.name))
  );

  return (
    <>
      {/* Status indicator */}
      {saved && (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 }}>
          <Check size={12} color="#22c55e" />
          <Text style={{ color: "#22c55e", fontSize: 11 }}>Saved</Text>
        </View>
      )}

      {/* Search */}
      <View style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
        background: "#111", border: "1px solid #333", borderRadius: 6, padding: "5px 10px",
        marginBottom: 12,
      } as any}>
        <Search size={12} color="#555" />
        <input
          type="text" value={filter}
          onChange={(e: any) => setFilter(e.target.value)}
          placeholder="Search tools..."
          style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#e5e5e5", fontSize: 12 }}
        />
        {filter && (
          <Pressable onPress={() => setFilter("")}>
            <X size={10} color="#555" />
          </Pressable>
        )}
      </View>

      {/* Legend */}
      <View style={{ flexDirection: "row", gap: 16, marginBottom: 16 }}>
        <Text style={{ fontSize: 10, color: "#555" }}>
          Inherit = use bot defaults | Override = only checked tools active | Disable = checked tools removed
        </Text>
      </View>

      {/* Local Tools */}
      <Section title="Local Tools">
        <View style={{ marginBottom: 8 }}>
          <SelectInput
            value={localMode}
            onChange={(v: string) => handleModeChange("local_tools", v as OverrideMode)}
            options={MODE_OPTIONS}
          />
        </View>
        {localMode === "inherit" ? (
          <Text style={{ fontSize: 11, color: "#555", fontStyle: "italic" }}>
            Using bot defaults ({allBotLocalTools.length} tools)
          </Text>
        ) : (
          <>
            <Text style={{ fontSize: 10, color: "#666", marginBottom: 8 }}>
              {localMode === "override"
                ? `Checked tools will be active (${localList.length} selected)`
                : `Checked tools will be disabled (${localList.length} disabled)`}
            </Text>
            {editorData.tool_groups.map((group) => {
              const groupTools = group.packs.flatMap((p) => p.tools.map((t) => t.name));
              const filteredPacks = group.packs.map((pack) => ({
                ...pack,
                tools: q ? pack.tools.filter((t) => t.name.toLowerCase().includes(q)) : pack.tools,
              })).filter((p) => p.tools.length > 0);
              if (filteredPacks.length === 0) return null;

              const groupFilteredTools = filteredPacks.flatMap((p) => p.tools.map((t) => t.name));
              const selectedInGroup = groupTools.filter((n) => localList.includes(n)).length;
              const allInGroup = selectedInGroup === groupTools.length && groupTools.length > 0;

              return (
                <View key={group.integration} style={{
                  borderWidth: 1, borderColor: "#1a1a1a", borderRadius: 8, overflow: "hidden", marginBottom: 8,
                }}>
                  {/* Group header */}
                  <View style={{
                    padding: 6, paddingHorizontal: 10, backgroundColor: "#0a0a0a",
                    flexDirection: "row", alignItems: "center", gap: 6,
                  }}>
                    {group.is_core ? (
                      <Text style={{ fontSize: 11, fontWeight: "600", color: "#888" }}>Core</Text>
                    ) : (
                      <Text style={{
                        fontSize: 9, fontWeight: "700", paddingHorizontal: 5, paddingVertical: 1,
                        borderRadius: 3, backgroundColor: "#92400e33", color: "#fbbf24",
                        textTransform: "uppercase",
                      }}>{group.integration}</Text>
                    )}
                    <Text style={{ fontSize: 9, color: "#555", marginLeft: "auto" }}>
                      {selectedInGroup}/{groupTools.length}
                    </Text>
                    <Pressable
                      onPress={() => toggleGroup("local_tools", localMode, localList, groupTools)}
                    >
                      <Text style={{
                        fontSize: 9, paddingHorizontal: 6, paddingVertical: 1,
                        borderWidth: 1, borderColor: "#333", borderRadius: 4,
                        color: allInGroup ? "#f87171" : "#86efac",
                      }}>{allInGroup ? "none" : "all"}</Text>
                    </Pressable>
                  </View>

                  {/* Tools grid */}
                  <View style={{ flexDirection: "row", flexWrap: "wrap", padding: 4, gap: 1 }}>
                    {filteredPacks.flatMap((pack) =>
                      pack.tools.map((tool) => {
                        const checked = localList.includes(tool.name);
                        return (
                          <Pressable
                            key={tool.name}
                            onPress={() => toggleTool("local_tools", localMode, localList, tool.name)}
                            style={{
                              flexDirection: "row", alignItems: "center", gap: 4,
                              padding: 3, paddingHorizontal: 6, borderRadius: 3,
                              width: "49%",
                              backgroundColor: checked ? "rgba(59,130,246,0.08)" : "transparent",
                              borderWidth: 1, borderColor: checked ? "#3b82f622" : "transparent",
                            }}
                          >
                            <input
                              type="checkbox" checked={checked} readOnly
                              style={{ accentColor: localMode === "disabled" ? "#ef4444" : "#3b82f6" }}
                            />
                            <Text style={{
                              fontFamily: "monospace", fontSize: 11,
                              color: checked ? (localMode === "disabled" ? "#fca5a5" : "#93c5fd") : "#555",
                            }} numberOfLines={1}>{tool.name}</Text>
                          </Pressable>
                        );
                      })
                    )}
                  </View>
                </View>
              );
            })}
          </>
        )}
      </Section>

      {/* MCP Servers */}
      {editorData.mcp_servers.length > 0 && (
        <Section title="MCP Servers">
          <View style={{ marginBottom: 8 }}>
            <SelectInput
              value={mcpMode}
              onChange={(v: string) => handleModeChange("mcp_servers", v as OverrideMode)}
              options={MODE_OPTIONS}
            />
          </View>
          {mcpMode === "inherit" ? (
            <Text style={{ fontSize: 11, color: "#555", fontStyle: "italic" }}>
              Using bot defaults
            </Text>
          ) : (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 2 }}>
              {editorData.mcp_servers.filter((s) => !q || s.toLowerCase().includes(q)).map((srv) => {
                const checked = mcpList.includes(srv);
                return (
                  <Pressable
                    key={srv}
                    onPress={() => toggleTool("mcp_servers", mcpMode, mcpList, srv)}
                    style={{
                      flexDirection: "row", alignItems: "center", gap: 6,
                      padding: 4, paddingHorizontal: 8, borderRadius: 4, width: "49%",
                      backgroundColor: checked ? "rgba(59,130,246,0.08)" : "transparent",
                      borderWidth: 1, borderColor: checked ? "#3b82f622" : "transparent",
                    }}
                  >
                    <input
                      type="checkbox" checked={checked} readOnly
                      style={{ accentColor: mcpMode === "disabled" ? "#ef4444" : "#3b82f6" }}
                    />
                    <Text style={{
                      fontFamily: "monospace", fontSize: 11,
                      color: checked ? (mcpMode === "disabled" ? "#fca5a5" : "#93c5fd") : "#555",
                    }}>{srv}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        </Section>
      )}

      {/* Client Tools */}
      {editorData.client_tools.length > 0 && (
        <Section title="Client Tools">
          <View style={{ marginBottom: 8 }}>
            <SelectInput
              value={clientMode}
              onChange={(v: string) => handleModeChange("client_tools", v as OverrideMode)}
              options={MODE_OPTIONS}
            />
          </View>
          {clientMode === "inherit" ? (
            <Text style={{ fontSize: 11, color: "#555", fontStyle: "italic" }}>
              Using bot defaults
            </Text>
          ) : (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 2 }}>
              {editorData.client_tools.filter((t) => !q || t.toLowerCase().includes(q)).map((tool) => {
                const checked = clientList.includes(tool);
                return (
                  <Pressable
                    key={tool}
                    onPress={() => toggleTool("client_tools", clientMode, clientList, tool)}
                    style={{
                      flexDirection: "row", alignItems: "center", gap: 6,
                      padding: 4, paddingHorizontal: 8, borderRadius: 4, width: "49%",
                      backgroundColor: checked ? "rgba(59,130,246,0.08)" : "transparent",
                      borderWidth: 1, borderColor: checked ? "#3b82f622" : "transparent",
                    }}
                  >
                    <input
                      type="checkbox" checked={checked} readOnly
                      style={{ accentColor: clientMode === "disabled" ? "#ef4444" : "#3b82f6" }}
                    />
                    <Text style={{
                      fontFamily: "monospace", fontSize: 11,
                      color: checked ? (clientMode === "disabled" ? "#fca5a5" : "#93c5fd") : "#555",
                    }}>{tool}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        </Section>
      )}

      {/* Skills */}
      {editorData.all_skills.length > 0 && (() => {
        const skillMode = getMode("skills_override", "skills_disabled");
        // For override: list of {id, mode?, similarity_threshold?} dicts
        const skillOverrideList: { id: string; mode?: string }[] = settings?.skills_override || [];
        const skillOverrideIds = skillOverrideList.map((s) => s.id);
        // For disabled: list of skill id strings
        const skillDisabledList: string[] = settings?.skills_disabled || [];
        // Bot's configured skills
        const botSkillIds = (editorData.bot.skills || []).map((s: any) => s.id);
        // All available skills (from all_skills), filtered to bot's skills
        const botSkills = editorData.all_skills.filter((s) => botSkillIds.includes(s.id));

        const handleSkillModeChange = (newMode: OverrideMode) => {
          const patch: any = {};
          if (newMode === "inherit") {
            patch.skills_override = null;
            patch.skills_disabled = null;
          } else if (newMode === "override") {
            patch.skills_override = [];
            patch.skills_disabled = null;
          } else {
            patch.skills_override = null;
            patch.skills_disabled = [];
          }
          save(patch);
        };

        const toggleSkill = (skillId: string) => {
          if (skillMode === "override") {
            const next = skillOverrideIds.includes(skillId)
              ? skillOverrideList.filter((s) => s.id !== skillId)
              : [...skillOverrideList, { id: skillId }];
            save({ skills_override: next } as any);
          } else if (skillMode === "disabled") {
            const next = skillDisabledList.includes(skillId)
              ? skillDisabledList.filter((s) => s !== skillId)
              : [...skillDisabledList, skillId];
            save({ skills_disabled: next } as any);
          }
        };

        const toggleAllSkills = () => {
          const ids = botSkills.map((s) => s.id);
          if (skillMode === "override") {
            const allIn = ids.every((id) => skillOverrideIds.includes(id));
            const next = allIn ? [] : ids.map((id) => ({ id }));
            save({ skills_override: next } as any);
          } else if (skillMode === "disabled") {
            const allIn = ids.every((id) => skillDisabledList.includes(id));
            const next = allIn ? [] : ids;
            save({ skills_disabled: next } as any);
          }
        };

        return (
          <Section title="Skills">
            <View style={{ marginBottom: 8 }}>
              <SelectInput
                value={skillMode}
                onChange={(v: string) => handleSkillModeChange(v as OverrideMode)}
                options={MODE_OPTIONS}
              />
            </View>
            {skillMode === "inherit" ? (
              <Text style={{ fontSize: 11, color: "#555", fontStyle: "italic" }}>
                Using bot defaults ({botSkills.length} skills)
              </Text>
            ) : (
              <>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <Text style={{ fontSize: 10, color: "#666", flex: 1 }}>
                    {skillMode === "override"
                      ? `Checked skills will be active (${skillOverrideIds.length} selected)`
                      : `Checked skills will be disabled (${skillDisabledList.length} disabled)`}
                  </Text>
                  <Pressable onPress={toggleAllSkills}>
                    <Text style={{
                      fontSize: 9, paddingHorizontal: 6, paddingVertical: 1,
                      borderWidth: 1, borderColor: "#333", borderRadius: 4,
                      color: "#86efac",
                    }}>
                      {(skillMode === "override"
                        ? botSkills.every((s) => skillOverrideIds.includes(s.id))
                        : botSkills.every((s) => skillDisabledList.includes(s.id)))
                        ? "none" : "all"}
                    </Text>
                  </Pressable>
                </View>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 2 }}>
                  {botSkills.filter((s) => !q || s.id.toLowerCase().includes(q) || (s.name || "").toLowerCase().includes(q)).map((skill) => {
                    const checked = skillMode === "override"
                      ? skillOverrideIds.includes(skill.id)
                      : skillDisabledList.includes(skill.id);
                    return (
                      <Pressable
                        key={skill.id}
                        onPress={() => toggleSkill(skill.id)}
                        style={{
                          flexDirection: "row", alignItems: "center", gap: 6,
                          padding: 4, paddingHorizontal: 8, borderRadius: 4, width: "49%",
                          backgroundColor: checked ? "rgba(59,130,246,0.08)" : "transparent",
                          borderWidth: 1, borderColor: checked ? "#3b82f622" : "transparent",
                        }}
                      >
                        <input
                          type="checkbox" checked={checked} readOnly
                          style={{ accentColor: skillMode === "disabled" ? "#ef4444" : "#3b82f6" }}
                        />
                        <Text style={{
                          fontSize: 11,
                          color: checked ? (skillMode === "disabled" ? "#fca5a5" : "#93c5fd") : "#555",
                        }} numberOfLines={1}>{skill.name || skill.id}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </>
            )}
          </Section>
        );
      })()}

      {/* Effective tools summary */}
      {effective && (
        <Section title="Effective Configuration">
          <Text style={{ fontSize: 11, color: "#666", marginBottom: 4 }}>
            After applying overrides, this channel has:
          </Text>
          <Text style={{ fontSize: 11, color: "#888", fontFamily: "monospace" }}>
            {effective.local_tools.length} local tools, {effective.mcp_servers.length} MCP servers, {effective.client_tools.length} client tools, {effective.pinned_tools.length} pinned tools, {effective.skills.length} skills
          </Text>
        </Section>
      )}
    </>
  );
}
