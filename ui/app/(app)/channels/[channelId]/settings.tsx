import { useCallback, useState, useEffect } from "react";
import { View, Text, Pressable, ScrollView, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft, Check, RotateCw, Play, ExternalLink } from "lucide-react";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useChannel,
} from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import {
  Section, FormRow, TextInput, SelectInput, Toggle,
  Row, Col, TabBar, EmptyState,
  triStateOptions, triStateValue, triStateParse,
} from "@/src/components/shared/FormControls";
import { apiFetch } from "@/src/api/client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { ChannelSettings } from "@/src/types/api";
import { useLogs, type LogRow } from "@/src/api/hooks/useLogs";
import { useChannelElevation } from "@/src/api/hooks/useElevation";

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
  { key: "sessions", label: "Sessions" },
  { key: "knowledge", label: "Knowledge" },
  { key: "heartbeat", label: "Heartbeat" },
  { key: "memories", label: "Memories" },
  { key: "tasks", label: "Tasks" },
  { key: "plans", label: "Plans" },
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
          <GeneralTab form={form} patch={patch} bots={bots} settings={settings} />
        )}
        {tab === "sessions" && <SessionsTab channelId={channelId!} />}
        {tab === "knowledge" && <KnowledgeTab channelId={channelId!} />}
        {tab === "heartbeat" && <HeartbeatTab channelId={channelId!} />}
        {tab === "memories" && <MemoriesTab channelId={channelId!} />}
        {tab === "tasks" && <TasksTab channelId={channelId!} />}
        {tab === "plans" && <PlansTab channelId={channelId!} />}
        {tab === "compression" && <CompressionTab channelId={channelId!} />}
        {tab === "logs" && <LogsTab channelId={channelId!} />}
      </ScrollView>
    </View>
  );
}

// ===========================================================================
// General Tab — settings form
// ===========================================================================
function GeneralTab({ form, patch, bots, settings }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  bots: any[] | undefined;
  settings: ChannelSettings;
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
// Sessions Tab
// ===========================================================================
function SessionsTab({ channelId }: { channelId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["channel-sessions", channelId],
    queryFn: () => apiFetch<any[]>(`/api/v1/admin/channels/${channelId}/sessions`),
  });

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;
  if (!data?.length) return <EmptyState message="No sessions yet." />;

  return (
    <Section title="Session History">
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {data.map((s: any) => (
          <div key={s.id} style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "10px 12px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
          }}>
            <div>
              <div style={{ fontSize: 13, color: "#e5e5e5", fontFamily: "monospace" }}>
                {s.id?.substring(0, 12)}...
                {s.title && <span style={{ fontFamily: "sans-serif", marginLeft: 8, color: "#999" }}>{s.title}</span>}
              </div>
              <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>
                {s.message_count ?? 0} messages
                {s.last_active && <span> · {new Date(s.last_active).toLocaleString()}</span>}
              </div>
            </div>
            {s.is_active && (
              <span style={{ fontSize: 10, background: "#166534", color: "#86efac", padding: "2px 8px", borderRadius: 4, fontWeight: 600 }}>
                ACTIVE
              </span>
            )}
          </div>
        ))}
      </div>
    </Section>
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
function TasksTab({ channelId }: { channelId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["channel-tasks", channelId],
    queryFn: () => apiFetch<any[]>(`/api/v1/admin/channels/${channelId}/tasks`),
  });

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;
  if (!data?.length) return <EmptyState message="No tasks yet." />;

  const statusColors: Record<string, { bg: string; fg: string }> = {
    pending: { bg: "#333", fg: "#999" },
    running: { bg: "#1e3a5f", fg: "#93c5fd" },
    complete: { bg: "#166534", fg: "#86efac" },
    failed: { bg: "#7f1d1d", fg: "#fca5a5" },
  };

  return (
    <Section title={`Tasks (${data.length})`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {data.map((t: any) => {
          const sc = statusColors[t.status] || statusColors.pending;
          return (
            <div key={t.id} style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "10px 12px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
            }}>
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
    </Section>
  );
}

// ===========================================================================
// Plans Tab
// ===========================================================================
function PlansTab({ channelId }: { channelId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["channel-plans", channelId],
    queryFn: () => apiFetch<any[]>(`/api/v1/admin/channels/${channelId}/plans`),
  });

  if (isLoading) return <ActivityIndicator color="#3b82f6" />;
  if (!data?.length) return <EmptyState message="No plans yet." />;

  const statusColors: Record<string, { bg: string; fg: string }> = {
    active: { bg: "#1e3a5f", fg: "#93c5fd" },
    complete: { bg: "#166534", fg: "#86efac" },
    abandoned: { bg: "#333", fg: "#999" },
  };

  return (
    <Section title={`Plans (${data.length})`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {data.map((p: any) => {
          const sc = statusColors[p.status] || statusColors.active;
          return (
            <div key={p.id} style={{
              padding: "12px 14px", background: "#1a1a1a", borderRadius: 8, border: "1px solid #2a2a2a",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#e5e5e5" }}>
                  {p.title || "Untitled Plan"}
                </div>
                <span style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
                  background: sc.bg, color: sc.fg,
                }}>
                  {p.status}
                </span>
              </div>
              {p.description && (
                <div style={{ fontSize: 12, color: "#888", marginBottom: 8 }}>{p.description}</div>
              )}
              {p.items?.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  {p.items.map((item: any) => (
                    <div key={item.id} style={{ display: "flex", gap: 8, fontSize: 12, color: "#999" }}>
                      <span style={{
                        color: item.status === "done" ? "#86efac" : item.status === "in_progress" ? "#93c5fd" : item.status === "skipped" ? "#666" : "#999",
                      }}>
                        {item.status === "done" ? "✓" : item.status === "in_progress" ? "→" : item.status === "skipped" ? "—" : "○"}
                      </span>
                      <span style={{ color: item.status === "done" ? "#86efac" : "#999" }}>
                        {item.content}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Section>
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
