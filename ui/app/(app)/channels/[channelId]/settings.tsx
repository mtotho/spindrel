import { useCallback, useState, useEffect } from "react";
import { useHashTab } from "@/src/hooks/useHashTab";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useLocalSearchParams, Link } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft, Check, ExternalLink } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useChannel,
} from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { TabBar } from "@/src/components/shared/FormControls";
import { useQueryClient } from "@tanstack/react-query";
import type { ChannelSettings } from "@/src/types/api";

// Tab components
import { GeneralTab } from "./GeneralTab";
import { HistoryTab } from "./HistoryTab";
import { ContextTab } from "./ContextTab";
import { ToolsOverrideTab } from "./ToolsOverrideTab";
import { IntegrationsTab } from "./IntegrationsTab";
import { SessionsTab } from "./SessionsTab";
import { HeartbeatTab } from "./HeartbeatTab";
import { TasksTab } from "./TasksTab";
import { LogsTab } from "./LogsTab";
import { AttachmentsTab } from "./AttachmentsTab";
import { ChannelWorkspaceTab } from "./ChannelWorkspaceTab";

// ---------------------------------------------------------------------------
// Tab definitions — ordered by importance / frequency of use.
// Diagnostic tabs (Context, Tasks, Logs) pushed to the end.
// ---------------------------------------------------------------------------
const TABS = [
  { key: "general", label: "General" },
  { key: "workspace", label: "Workspace" },
  { key: "heartbeat", label: "Heartbeat" },
  { key: "history", label: "History" },
  { key: "tools", label: "Tools" },
  { key: "integrations", label: "Integrations" },
  { key: "attachments", label: "Attachments" },
  { key: "sessions", label: "Sessions" },
  { key: "context", label: "Context" },
  { key: "tasks", label: "Tasks" },
  { key: "logs", label: "Logs" },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function ChannelSettingsScreen() {
  const t = useThemeTokens();
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const insets = useSafeAreaInsets();
  const goBack = useGoBack(`/channels/${channelId}`);
  const queryClient = useQueryClient();
  const { refreshing, onRefresh } = usePageRefresh();
  const { data: channel } = useChannel(channelId);
  const { data: settings, isLoading } = useChannelSettings(channelId);
  const { data: bots } = useBots();
  const updateMutation = useUpdateChannelSettings(channelId!);

  // Check if the channel's bot is in a workspace
  const currentBot = bots?.find((b: any) => b.id === settings?.bot_id);
  const resolvedWorkspaceId = settings?.resolved_workspace_id ?? currentBot?.shared_workspace_id;
  const hasWorkspace = !!resolvedWorkspaceId;

  const tabKeys = TABS.map((t) => t.key);
  const [tab, setTab] = useHashTab("general", tabKeys);
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
        thinking_display: settings.thinking_display,
        max_iterations: settings.max_iterations,
        context_compaction: settings.context_compaction,
        compaction_interval: settings.compaction_interval,
        compaction_keep_turns: settings.compaction_keep_turns,
        history_mode: settings.history_mode,
        compaction_model: settings.compaction_model,
        trigger_heartbeat_before_compaction: settings.trigger_heartbeat_before_compaction,
        memory_flush_enabled: settings.memory_flush_enabled,
        memory_flush_model: settings.memory_flush_model,
        memory_flush_model_provider_id: settings.memory_flush_model_provider_id,
        memory_flush_prompt: settings.memory_flush_prompt,
        memory_flush_prompt_template_id: settings.memory_flush_prompt_template_id,
        memory_flush_workspace_file_path: settings.memory_flush_workspace_file_path,
        memory_flush_workspace_id: settings.memory_flush_workspace_id,
        section_index_count: settings.section_index_count,
        section_index_verbosity: settings.section_index_verbosity,
        model_override: settings.model_override,
        model_provider_id_override: settings.model_provider_id_override,
        fallback_models: settings.fallback_models ?? [],
        channel_prompt: settings.channel_prompt,
        channel_prompt_workspace_file_path: settings.channel_prompt_workspace_file_path,
        channel_prompt_workspace_id: settings.channel_prompt_workspace_id,
        workspace_skills_enabled: settings.workspace_skills_enabled,
        workspace_base_prompt_enabled: settings.workspace_base_prompt_enabled,
        channel_workspace_enabled: settings.channel_workspace_enabled,
        workspace_schema_template_id: settings.workspace_schema_template_id,
        index_segments: settings.index_segments ?? [],
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
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  const showSave = tab === "general" || tab === "history" || tab === "workspace";

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View
        className="border-b border-surface-border"
        style={{ flexShrink: 0, paddingTop: Math.max(insets.top, 12) }}
      >
        <View className="flex-row items-center gap-2 px-3 py-2" style={{ minHeight: 48 }}>
          <Pressable
            onPress={goBack}
            className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 40, height: 40, flexShrink: 0 }}
          >
            <ArrowLeft size={20} color={t.textMuted} />
          </Pressable>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text className="text-text font-semibold" style={{ fontSize: 15 }} numberOfLines={1}>
              {channel?.display_name || channel?.name || channel?.client_id || "Channel"}
            </Text>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <Text className="text-text-dim" style={{ fontSize: 11 }} numberOfLines={1}>
                Settings
              </Text>
              {settings?.bot_id && (
                <Link href={`/admin/bots/${settings.bot_id}` as any} asChild>
                  <Pressable style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
                    <ExternalLink size={10} color={t.accent} />
                    <Text style={{ fontSize: 11, color: t.accent }} numberOfLines={1}>{currentBot?.name || settings.bot_id}</Text>
                  </Pressable>
                </Link>
              )}
            </View>
          </View>
          {showSave && (
            <Pressable
              onPress={handleSave}
              disabled={updateMutation.isPending}
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: 5,
                paddingHorizontal: 12,
                minHeight: 36,
                borderRadius: 8,
                backgroundColor: saved ? t.successSubtle : t.accent,
                flexShrink: 0,
              }}
            >
              {saved ? (
                <>
                  <Check size={14} color={t.success} />
                  <Text style={{ color: t.success, fontSize: 12, fontWeight: "600" }}>Saved</Text>
                </>
              ) : (
                <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>
                  {updateMutation.isPending ? "..." : "Save"}
                </Text>
              )}
            </Pressable>
          )}
        </View>
      </View>

      {/* Tabs — with gradient fade hints for scrollability */}
      <View style={{ flexShrink: 0, position: "relative" }}>
        <View className="px-3 pt-2 pb-1">
          <TabBar tabs={TABS} active={tab} onChange={setTab} />
        </View>
        {/* Right fade to hint at scrollable tabs */}
        <div
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            bottom: 0,
            width: 32,
            background: `linear-gradient(to right, transparent, ${t.surface})`,
            pointerEvents: "none",
          }}
        />
      </View>

      {/* Tab content */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        className="flex-1"
        contentContainerStyle={{ padding: 16, paddingBottom: Math.max(insets.bottom, 20) + 16, gap: 20, maxWidth: 680, width: "100%", boxSizing: "border-box", overflowX: "hidden" } as any}
        key={tab}
      >
        {tab === "general" && (
          <GeneralTab form={form} patch={patch} bots={bots} settings={settings} workspaceId={currentBot?.shared_workspace_id} channelId={channelId!} />
        )}
        {tab === "workspace" && (
          <ChannelWorkspaceTab
            form={form}
            patch={patch}
            channelId={channelId!}
            workspaceId={resolvedWorkspaceId ?? undefined}
            indexSegmentDefaults={settings?.index_segment_defaults}
            hasSharedWorkspace={hasWorkspace}
            sharedWorkspaceId={currentBot?.shared_workspace_id}
          />
        )}
        {tab === "heartbeat" && <HeartbeatTab channelId={channelId!} workspaceId={currentBot?.shared_workspace_id} botModel={currentBot?.model} />}
        {tab === "history" && (
          <HistoryTab form={form} patch={patch} channelId={channelId!} workspaceId={currentBot?.shared_workspace_id} memoryScheme={currentBot?.memory_scheme} botHistoryMode={currentBot?.history_mode} />
        )}
        {tab === "tools" && <ToolsOverrideTab channelId={channelId!} botId={channel?.bot_id} />}
        {tab === "integrations" && <IntegrationsTab channelId={channelId!} />}
        {tab === "attachments" && <AttachmentsTab channelId={channelId!} />}
        {tab === "sessions" && <SessionsTab channelId={channelId!} />}
        {tab === "context" && <ContextTab channelId={channelId!} />}
        {tab === "tasks" && <TasksTab channelId={channelId!} botId={channel?.bot_id} />}
        {tab === "logs" && <LogsTab channelId={channelId!} />}
      </RefreshableScrollView>
    </View>
  );
}
