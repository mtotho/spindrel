import { useCallback, useState, useEffect, useRef } from "react";
import { useHashTab } from "@/src/hooks/useHashTab";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useLocalSearchParams, Link } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import { ArrowLeft, Check, ExternalLink, Zap, ChevronDown } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useChannel,
  useActivatableIntegrations,
} from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { prettyIntegrationName } from "@/src/utils/format";
import type { ChannelSettings } from "@/src/types/api";

// Tab components
import { GeneralTab } from "./GeneralTab";
import { HistoryTab } from "./HistoryTab";
import { ContextTab } from "./ContextTab";
import { ToolsOverrideTab } from "./ToolsOverrideTab";
import { IntegrationsTab } from "./IntegrationsTab";
import { HeartbeatTab } from "./HeartbeatTab";
import { TasksTab } from "./TasksTab";
import { LogsTab } from "./LogsTab";
import { AttachmentsTab } from "./AttachmentsTab";
import { ChannelWorkspaceTab } from "./ChannelWorkspaceTab";
import { WorkflowsTab } from "./WorkflowsTab";
import { ParticipantsTab } from "./ParticipantsTab";

// ---------------------------------------------------------------------------
// Tab definitions — ordered by importance / frequency of use.
// Diagnostic tabs (Context, Tasks, Logs) pushed to the end.
// ---------------------------------------------------------------------------
const PRIMARY_TABS = [
  { key: "general", label: "General" },
  { key: "participants", label: "Participants" },
  { key: "workspace", label: "Workspace" },
  { key: "heartbeat", label: "Heartbeat" },
  { key: "history", label: "History" },
  { key: "capabilities", label: "Capabilities" },
  { key: "connections", label: "Connections" },
  { key: "attachments", label: "Attachments" },
];
const ADVANCED_TABS = [
  { key: "context", label: "Context" },
  { key: "workflows", label: "Workflows" },
  { key: "tasks", label: "Tasks" },
  { key: "logs", label: "Logs" },
];
const ALL_TABS = [...PRIMARY_TABS, ...ADVANCED_TABS];
const ADVANCED_KEYS = new Set(ADVANCED_TABS.map((t) => t.key));

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function ChannelSettingsScreen() {
  const t = useThemeTokens();
  const isMobile = useIsMobile();
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const insets = useSafeAreaInsets();
  const goBack = useGoBack(`/channels/${channelId}`);
  const { refreshing, onRefresh } = usePageRefresh();
  const { data: channel } = useChannel(channelId);
  const { data: settings, isLoading } = useChannelSettings(channelId);
  const { data: bots } = useBots();
  const updateMutation = useUpdateChannelSettings(channelId!);
  const { data: activatable } = useActivatableIntegrations(channelId);

  // Check if the channel's bot is in a workspace
  const currentBot = bots?.find((b: any) => b.id === settings?.bot_id);
  const resolvedWorkspaceId = settings?.resolved_workspace_id ?? currentBot?.shared_workspace_id;
  const hasWorkspace = !!resolvedWorkspaceId;

  const tabKeys = ALL_TABS.map((tab) => tab.key);
  const [tab, setTab] = useHashTab("general", tabKeys);
  const [moreOpen, setMoreOpen] = useState(false);
  const moreBtnRef = useRef<HTMLButtonElement>(null);
  const [form, setForm] = useState<Partial<ChannelSettings>>({});
  const [saved, setSaved] = useState(false);

  const isAdvancedTab = ADVANCED_KEYS.has(tab);

  // Close "More" dropdown on Escape
  useEffect(() => {
    if (!moreOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMoreOpen(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
    };
  }, [moreOpen]);

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
        workspace_schema_content: settings.workspace_schema_content,
        index_segments: settings.index_segments ?? [],
        tags: settings.tags ?? [],
        category: settings.category ?? null,
      });
    }
  }, [settings]);

  // Debounced auto-save: every patch() triggers a save after 800ms.
  // Multiple rapid changes batch into one PATCH request.
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const formRef = useRef(form);
  formRef.current = form;

  const debouncedSave = useCallback(() => {
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(async () => {
      try {
        await updateMutation.mutateAsync(formRef.current);
        setSaved(true);
        setTimeout(() => setSaved(false), 2500);
      } catch {
        // Error state handled by updateMutation.isError
      }
    }, 800);
  }, [updateMutation]);

  // Flush pending save on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
        updateMutation.mutate(formRef.current);
      }
    };
  }, [updateMutation]);

  const patch = useCallback(
    <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => {
      setForm((f) => ({ ...f, [key]: value }));
      setSaved(false);
      debouncedSave();
    },
    [debouncedSave]
  );

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
              {activatable?.filter(ig => ig.activated).map(ig => (
                <View key={ig.integration_type} style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
                  <Zap size={10} color={t.success} fill={t.success} />
                  <Text style={{ fontSize: 11, color: t.success }}>
                    {prettyIntegrationName(ig.integration_type)}
                  </Text>
                </View>
              ))}
            </View>
          </View>
          {/* Auto-save status indicator */}
          {updateMutation.isPending && (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 4, flexShrink: 0 }}>
              <ActivityIndicator size={10} color={t.textDim} />
              <Text style={{ fontSize: 11, color: t.textDim }}>Saving</Text>
            </View>
          )}
          {saved && !updateMutation.isPending && (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 4, flexShrink: 0 }}>
              <Check size={12} color={t.success} />
              <Text style={{ fontSize: 11, color: t.success }}>Saved</Text>
            </View>
          )}
          {updateMutation.isError && !updateMutation.isPending && !saved && (
            <Text style={{ fontSize: 11, color: "#ef4444", flexShrink: 0 }}>Save failed</Text>
          )}
        </View>
      </View>

      {/* Tabs — single row with overflow dropdown for advanced */}
      <View style={{ flexShrink: 0 }} className="px-3 pt-2 pb-1">
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {/* Scrollable primary tabs */}
          <div
            style={{
              display: "flex",
              gap: 4,
              overflowX: "auto",
              WebkitOverflowScrolling: "touch",
              scrollbarWidth: "none",
              paddingBottom: 4,
              scrollSnapType: "x mandatory",
              flex: 1,
              minWidth: 0,
            }}
            className="hide-scrollbar"
          >
            {PRIMARY_TABS.map((tb) => {
              const isActive = tb.key === tab;
              return (
                <button
                  key={tb.key}
                  onClick={() => setTab(tb.key)}
                  style={{
                    padding: "6px 10px",
                    fontSize: 12,
                    fontWeight: isActive ? 600 : 500,
                    border: "1px solid",
                    borderColor: isActive ? t.accent : t.surfaceBorder,
                    borderRadius: 6,
                    background: isActive ? t.accent : "transparent",
                    color: isActive ? "#fff" : t.textMuted,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                    transition: "all 0.15s",
                    flexShrink: 0,
                    scrollSnapAlign: "start",
                    minHeight: 36,
                  }}
                >
                  {tb.label}
                </button>
              );
            })}
          </div>

          {/* "More" dropdown — rendered via portal to avoid stacking context issues */}
          <div style={{ flexShrink: 0, paddingBottom: 4 }}>
            <button
              ref={moreBtnRef as any}
              onClick={() => setMoreOpen((v) => !v)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 3,
                padding: "6px 10px",
                fontSize: 12,
                fontWeight: isAdvancedTab ? 600 : 500,
                border: "1px solid",
                borderColor: isAdvancedTab ? t.accent : t.surfaceBorder,
                borderRadius: 6,
                background: isAdvancedTab ? t.accent : "transparent",
                color: isAdvancedTab ? "#fff" : t.textMuted,
                cursor: "pointer",
                whiteSpace: "nowrap",
                transition: "all 0.15s",
                minHeight: 36,
              }}
            >
              {isAdvancedTab ? ADVANCED_TABS.find((at) => at.key === tab)?.label : "More"}
              <ChevronDown
                size={10}
                color={isAdvancedTab ? "#fff" : t.textMuted}
                style={{ transform: moreOpen ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s" } as any}
              />
            </button>
            {moreOpen && typeof document !== "undefined" && (() => {
              const ReactDOM = require("react-dom");
              const rect = moreBtnRef.current?.getBoundingClientRect();
              return ReactDOM.createPortal(
                <>
                  <div
                    onClick={() => setMoreOpen(false)}
                    style={{ position: "fixed", inset: 0, zIndex: 10010 }}
                  />
                  <div
                    style={{
                      position: "fixed",
                      top: (rect?.bottom ?? 0) + 4,
                      right: window.innerWidth - (rect?.right ?? 0),
                      zIndex: 10011,
                      background: t.surfaceRaised,
                      border: `1px solid ${t.surfaceBorder}`,
                      borderRadius: 8,
                      padding: 4,
                      minWidth: 140,
                      boxShadow: "0 8px 32px rgba(0,0,0,0.25)",
                    }}
                  >
                    {ADVANCED_TABS.map((at) => (
                      <button
                        key={at.key}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          setTab(at.key);
                          setMoreOpen(false);
                        }}
                        style={{
                          display: "block",
                          width: "100%",
                          textAlign: "left",
                          padding: "8px 10px",
                          fontSize: 12,
                          fontWeight: at.key === tab ? 600 : 400,
                          color: at.key === tab ? t.accent : t.text,
                          background: "transparent",
                          border: "none",
                          borderRadius: 4,
                          cursor: "pointer",
                        }}
                      >
                        {at.label}
                      </button>
                    ))}
                  </div>
                </>,
                document.body,
              );
            })()}
          </div>
        </div>
      </View>

      {/* Tab content */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        className="flex-1"
        contentContainerStyle={{ padding: isMobile ? 12 : 16, paddingBottom: Math.max(insets.bottom, 20) + 16, gap: isMobile ? 16 : 20, maxWidth: (["logs", "tasks", "context", "workflows"] as string[]).includes(tab) ? 1200 : (["capabilities"] as string[]).includes(tab) ? 960 : 680, width: "100%", boxSizing: "border-box", overflowX: "hidden" } as any}
        key={tab}
      >
        {tab === "general" && (
          <GeneralTab form={form} patch={patch} bots={bots} settings={settings} workspaceId={currentBot?.shared_workspace_id} channelId={channelId!} />
        )}
        {tab === "participants" && (
          <ParticipantsTab channelId={channelId!} primaryBotId={settings?.bot_id ?? ""} />
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
        {tab === "capabilities" && <ToolsOverrideTab channelId={channelId!} botId={channel?.bot_id} workspaceEnabled={!!form.channel_workspace_enabled} />}
        {tab === "connections" && <IntegrationsTab channelId={channelId!} workspaceEnabled={!!form.channel_workspace_enabled} />}
        {tab === "attachments" && <AttachmentsTab channelId={channelId!} />}
        {tab === "context" && <ContextTab channelId={channelId!} />}
        {tab === "workflows" && <WorkflowsTab channelId={channelId!} />}
        {tab === "tasks" && <TasksTab channelId={channelId!} botId={channel?.bot_id} />}
        {tab === "logs" && <LogsTab channelId={channelId!} />}
      </RefreshableScrollView>
    </View>
  );
}
