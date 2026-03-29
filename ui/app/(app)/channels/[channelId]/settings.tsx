import { useCallback, useState, useEffect, useMemo } from "react";
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
import { WorkspaceOverrideTab } from "./WorkspaceOverrideTab";
import { ToolsOverrideTab } from "./ToolsOverrideTab";
import { IntegrationsTab } from "./IntegrationsTab";
import { SessionsTab } from "./SessionsTab";
import { HeartbeatTab } from "./HeartbeatTab";
import { TasksTab } from "./TasksTab";
import { LogsTab } from "./LogsTab";
import { ChannelWorkspaceTab } from "./ChannelWorkspaceTab";

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------
const BASE_TABS = [
  { key: "general", label: "General" },
  { key: "history", label: "History" },
  { key: "context", label: "Context" },
  { key: "files", label: "Files" },
  { key: "tools", label: "Tools" },
  { key: "integrations", label: "Integrations" },
  { key: "sessions", label: "Sessions" },
  { key: "heartbeat", label: "Heartbeat" },
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
  const TABS = useMemo(() => {
    if (hasWorkspace) {
      const idx = BASE_TABS.findIndex((t) => t.key === "context");
      const tabs = [...BASE_TABS];
      tabs.splice(idx + 1, 0, { key: "workspace", label: "Workspace" });
      return tabs;
    }
    return BASE_TABS;
  }, [hasWorkspace]);

  const tabKeys = useMemo(() => TABS.map((t) => t.key), [TABS]);
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

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View className="flex-row items-center gap-3 px-4 py-3 border-b border-surface-border" style={{ flexShrink: 0, paddingTop: Math.max(insets.top, 12) }}>
        <Pressable
          onPress={goBack}
          className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
        >
          <ArrowLeft size={20} color={t.textMuted} />
        </Pressable>
        <View className="flex-1 min-w-0">
          <Text className="text-text font-semibold" style={{ fontSize: 16 }} numberOfLines={1}>
            {channel?.display_name || channel?.name || channel?.client_id || "Channel"}
          </Text>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text className="text-text-dim text-xs" numberOfLines={1}>
              Channel Settings
            </Text>
            {settings?.bot_id && (
              <Link href={`/admin/bots/${settings.bot_id}` as any} asChild>
                <Pressable style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
                  <ExternalLink size={10} color={t.accent} />
                  <Text style={{ fontSize: 11, color: t.accent }}>{currentBot?.name || settings.bot_id}</Text>
                </Pressable>
              </Link>
            )}
          </View>
        </View>
        {(tab === "general" || tab === "history" || tab === "workspace" || tab === "files") && (
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
              backgroundColor: saved ? t.successSubtle : t.accent,
            }}
          >
            {saved ? (
              <>
                <Check size={14} color={t.success} />
                <Text style={{ color: t.success, fontSize: 13, fontWeight: "600" }}>Saved</Text>
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
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        className="flex-1"
        contentContainerStyle={{ padding: 16, paddingBottom: Math.max(insets.bottom, 20) + 16, gap: 20, maxWidth: 680 }}
        key={tab}
      >
        {tab === "general" && (
          <GeneralTab form={form} patch={patch} bots={bots} settings={settings} workspaceId={currentBot?.shared_workspace_id} channelId={channelId!} />
        )}
        {tab === "history" && (
          <HistoryTab form={form} patch={patch} channelId={channelId!} workspaceId={currentBot?.shared_workspace_id} memoryScheme={currentBot?.memory_scheme} botHistoryMode={currentBot?.history_mode} />
        )}
        {tab === "context" && <ContextTab channelId={channelId!} />}
        {tab === "files" && (
          <ChannelWorkspaceTab form={form} patch={patch} channelId={channelId!} workspaceId={resolvedWorkspaceId ?? undefined} indexSegmentDefaults={settings?.index_segment_defaults} />
        )}
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
        {tab === "heartbeat" && <HeartbeatTab channelId={channelId!} workspaceId={currentBot?.shared_workspace_id} botModel={currentBot?.model} />}
        {tab === "tasks" && <TasksTab channelId={channelId!} botId={channel?.bot_id} />}
        {tab === "logs" && <LogsTab channelId={channelId!} />}
      </RefreshableScrollView>
    </View>
  );
}
