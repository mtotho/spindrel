import { useCallback, useState, useEffect } from "react";
import { View, Text, Pressable, ScrollView, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft, Check, RotateCw, Play, ExternalLink, Plus, Search, X } from "lucide-react";
import {
  useChannelSettings,
  useUpdateChannelSettings,
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
const TABS = [
  { key: "general", label: "General" },
  { key: "context", label: "Context" },
  { key: "tools", label: "Tools" },
  { key: "integrations", label: "Integrations" },
  { key: "sessions", label: "Sessions" },
  { key: "knowledge", label: "Knowledge" },
  { key: "heartbeat", label: "Heartbeat" },
  { key: "memories", label: "Memories" },
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
        workspace_rag: settings.workspace_rag,
        context_compaction: settings.context_compaction,
        compaction_interval: settings.compaction_interval,
        compaction_keep_turns: settings.compaction_keep_turns,
        memory_knowledge_compaction_prompt: settings.memory_knowledge_compaction_prompt,
        context_compression: settings.context_compression,
        compression_model: settings.compression_model,
        compression_threshold: settings.compression_threshold,
        compression_keep_turns: settings.compression_keep_turns,
        elevation_enabled: settings.elevation_enabled,
        elevation_threshold: settings.elevation_threshold,
        elevated_model: settings.elevated_model,
        model_override: settings.model_override,
        model_provider_id_override: settings.model_provider_id_override,
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
    <View className="flex-1 bg-surface" style={{ overflow: "hidden" }}>
      {/* Header */}
      <View className="flex-row items-center gap-3 px-4 py-3 border-b border-surface-border" style={{ flexShrink: 0 }}>
        <Pressable onPress={goBack} className="p-1 rounded hover:bg-surface-overlay">
          <ArrowLeft size={18} color="#999" />
        </Pressable>
        <View className="flex-1 min-w-0">
          <Text className="text-text font-semibold text-sm" numberOfLines={1}>
            {channel?.display_name || channel?.name || channel?.client_id || "Channel"}
          </Text>
          <Text className="text-text-dim text-xs" numberOfLines={1}>
            Channel Settings
          </Text>
        </View>
        {tab === "general" && (
          <Pressable
            onPress={handleSave}
            disabled={updateMutation.isPending}
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              paddingHorizontal: 14,
              paddingVertical: 7,
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
          <GeneralTab form={form} patch={patch} bots={bots} settings={settings} elevationData={elevationData} />
        )}
        {tab === "context" && <ContextTab channelId={channelId!} />}
        {tab === "tools" && <ToolsOverrideTab channelId={channelId!} botId={channel?.bot_id} />}
        {tab === "integrations" && <IntegrationsTab channelId={channelId!} />}
        {tab === "sessions" && <SessionsTab channelId={channelId!} />}
        {tab === "knowledge" && <KnowledgeTab channelId={channelId!} />}
        {tab === "heartbeat" && <HeartbeatTab channelId={channelId!} />}
        {tab === "memories" && <MemoriesTab channelId={channelId!} />}
        {tab === "tasks" && <TasksTab channelId={channelId!} botId={channel?.bot_id} />}
        {tab === "compression" && <CompressionTab channelId={channelId!} />}
        {tab === "logs" && <LogsTab channelId={channelId!} />}
      </ScrollView>
    </View>
  );
}

// ===========================================================================
// General Tab — settings form
// ===========================================================================
function GeneralTab({ form, patch, bots, settings, elevationData }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  bots: any[] | undefined;
  settings: ChannelSettings;
  elevationData: any;
}) {
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
          value={form.workspace_rag ?? true}
          onChange={(v) => patch("workspace_rag", v)}
          label="Workspace RAG"
          description="Auto-inject relevant workspace files into context each turn."
        />
      </Section>

      <Section title="Compaction" description="Auto-summarizes old turns so the context window never fills up.">
        <Toggle
          value={form.context_compaction ?? true}
          onChange={(v) => patch("context_compaction", v)}
          label="Enable auto-compaction"
        />
        {form.context_compaction && (
          <>
            <Row>
              <Col>
                <FormRow label="Interval (user turns)">
                  <TextInput
                    value={form.compaction_interval?.toString() ?? ""}
                    onChangeText={(v) => patch("compaction_interval", v ? parseInt(v) || undefined : undefined)}
                    placeholder="default"
                    type="number"
                  />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="Keep Turns">
                  <TextInput
                    value={form.compaction_keep_turns?.toString() ?? ""}
                    onChangeText={(v) => patch("compaction_keep_turns", v ? parseInt(v) || undefined : undefined)}
                    placeholder="default"
                    type="number"
                  />
                </FormRow>
              </Col>
            </Row>
            <LlmPrompt
              value={form.memory_knowledge_compaction_prompt ?? ""}
              onChange={(v) => patch("memory_knowledge_compaction_prompt", v || undefined)}
              label="Memory/Knowledge Compaction Prompt"
              placeholder="Leave blank to use the global default prompt..."
              helpText="Given to the bot before summarization. Tags like @tool:save_memory auto-pin those tools during the memory phase."
              rows={5}
            />
          </>
        )}
      </Section>

      <Section title="Context Compression" description="Summarises old turns via a cheap model before each LLM call. Leave blank to inherit.">
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
// Knowledge Tab
// ===========================================================================
function KnowledgeTab({ channelId }: { channelId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["channel-knowledge", channelId],
    queryFn: () => apiFetch<any[]>(`/api/v1/admin/channels/${channelId}/knowledge`),
  });

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;
  if (!data?.length) return <EmptyState message="No knowledge entries scoped to this channel." />;

  const modeColors: Record<string, { bg: string; fg: string }> = {
    rag: { bg: "#1e3a5f", fg: "#93c5fd" },
    pinned: { bg: "#166534", fg: "#86efac" },
    tag_only: { bg: "#333", fg: "#999" },
  };

  return (
    <Section title={`Knowledge (${data.length})`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {data.map((k: any) => {
          const mc = modeColors[k.mode] || modeColors.rag;
          return (
            <div key={k.id} style={{
              padding: "10px 12px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#e5e5e5" }}>
                  {k.title || "Untitled"}
                </div>
                <span style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
                  background: mc.bg, color: mc.fg,
                }}>
                  {k.mode}
                </span>
              </div>
              {k.content && (
                <div style={{ fontSize: 12, color: "#888", whiteSpace: "pre-wrap", maxHeight: 80, overflow: "hidden" }}>
                  {k.content}
                </div>
              )}
              <div style={{ display: "flex", gap: 12, fontSize: 10, color: "#555", marginTop: 6 }}>
                <span>{k.content_length?.toLocaleString()} chars</span>
                {k.bot_id && <span>bot: {k.bot_id}</span>}
                {k.updated_at && <span>{new Date(k.updated_at).toLocaleString()}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

// ===========================================================================
// Heartbeat Tab
// ===========================================================================
function HeartbeatTab({ channelId }: { channelId: string }) {
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
      });
    } else if (data && !data.config) {
      setHbForm({
        interval_minutes: 60,
        model: "",
        model_provider_id: "",
        prompt: "",
        dispatch_results: true,
        trigger_response: false,
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
          <LlmPrompt
            value={hbForm.prompt ?? ""}
            onChange={(v) => setHbForm((f: any) => ({ ...f, prompt: v }))}
            label="Heartbeat Prompt"
            placeholder="Enter the heartbeat prompt..."
            helpText="This prompt runs on the configured interval. Use @-tags to reference skills or tools."
            rows={10}
          />
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
            disabled={!hbForm.prompt}
            style={{
              padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer",
              background: hbForm.prompt ? "#92400e" : "#333",
              color: hbForm.prompt ? "#fcd34d" : "#666",
              fontSize: 13, fontWeight: 500,
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            <Play size={12} color={hbForm.prompt ? "#fcd34d" : "#666"} />
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
// Memories Tab
// ===========================================================================
function MemoriesTab({ channelId }: { channelId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["channel-memories", channelId],
    queryFn: () => apiFetch<any[]>(`/api/v1/admin/channels/${channelId}/memories`),
  });

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;
  if (!data?.length) return <EmptyState message="No memories yet." />;

  return (
    <Section title={`Memories (${data.length})`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {data.map((m: any) => (
          <div key={m.id} style={{
            padding: "10px 12px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
          }}>
            {m.title && (
              <div style={{ fontSize: 13, fontWeight: 600, color: "#e5e5e5", marginBottom: 4 }}>{m.title}</div>
            )}
            <div style={{ fontSize: 12, color: "#999", whiteSpace: "pre-wrap", maxHeight: 120, overflow: "hidden" }}>
              {m.content?.substring(0, 300)}{m.content?.length > 300 ? "..." : ""}
            </div>
            <div style={{ fontSize: 10, color: "#555", marginTop: 6 }}>
              {new Date(m.created_at).toLocaleString()}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ===========================================================================
// Tasks Tab
// ===========================================================================
function TasksTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-tasks", channelId],
    queryFn: () => apiFetch<any[]>(`/api/v1/admin/channels/${channelId}/tasks`),
  });

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
  };

  const handleEditorSaved = () => {
    setEditorState({ mode: "closed" });
    queryClient.invalidateQueries({ queryKey: ["channel-tasks", channelId] });
  };

  const editorOpen = editorState.mode !== "closed";
  const editorTaskId = editorState.mode === "edit" ? editorState.taskId : null;

  return (
    <>
      <Section title={`Tasks (${data?.length ?? 0})`} action={
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
        ) : !data?.length ? (
          <EmptyState message="No tasks yet." />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {data.map((t: any) => {
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
function CompressionTab({ channelId }: { channelId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["channel-compression", channelId],
    queryFn: () => apiFetch<any>(`/api/v1/admin/channels/${channelId}/compression`),
  });

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;
  if (!data) return <EmptyState message="No compression data." />;

  return (
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
