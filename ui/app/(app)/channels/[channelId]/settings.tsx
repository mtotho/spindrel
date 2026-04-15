import { Spinner } from "@/src/components/shared/Spinner";
import { useCallback, useState, useEffect, useRef } from "react";
import { useHashTab } from "@/src/hooks/useHashTab";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import { ArrowLeft, Check, ExternalLink, Zap } from "lucide-react";
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
// Tab definitions — single flat list, all visible. A separator divides
// primary settings from diagnostic/operational tabs.
// ---------------------------------------------------------------------------
const ALL_TABS: { key: string; label: string; separator?: boolean }[] = [
  { key: "general", label: "General" },
  { key: "participants", label: "Participants" },
  { key: "workspace", label: "Workspace" },
  { key: "capabilities", label: "Capabilities" },
  { key: "integrations", label: "Integrations" },
  { key: "heartbeat", label: "Heartbeat" },
  { key: "history", label: "History" },
  { key: "attachments", label: "Attachments" },
  { key: "context", label: "Context", separator: true },
  { key: "workflows", label: "Workflows" },
  { key: "tasks", label: "Tasks" },
  { key: "logs", label: "Logs" },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function ChannelSettingsScreen() {
  const t = useThemeTokens();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { channelId } = useParams<{ channelId: string }>();
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
  const [form, setForm] = useState<Partial<ChannelSettings>>({});
  const [saved, setSaved] = useState(false);

  // Tab bar horizontal scroll: translate vertical wheel → horizontal,
  // track edge overflow for fade indicators, and keep the active tab visible.
  const tabBarRef = useRef<HTMLDivElement | null>(null);
  const tabButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [tabOverflow, setTabOverflow] = useState({ left: false, right: false });

  const updateTabOverflow = useCallback(() => {
    const el = tabBarRef.current;
    if (!el) return;
    const left = el.scrollLeft > 1;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setTabOverflow((prev) => (prev.left === left && prev.right === right ? prev : { left, right }));
  }, []);

  useEffect(() => {
    const el = tabBarRef.current;
    if (!el) return;
    updateTabOverflow();
    el.addEventListener("scroll", updateTabOverflow, { passive: true });
    const ro = new ResizeObserver(updateTabOverflow);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", updateTabOverflow);
      ro.disconnect();
    };
  }, [updateTabOverflow]);

  // Translate vertical mouse-wheel into horizontal scroll so desktop users
  // with a regular mouse can reach off-screen tabs.
  useEffect(() => {
    const el = tabBarRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      // Only intercept when there's actually horizontal overflow and the
      // user is using a vertical wheel (deltaY dominant, deltaX ~0).
      if (el.scrollWidth <= el.clientWidth) return;
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
      e.preventDefault();
      el.scrollLeft += e.deltaY;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // Keep the active tab in view whenever it changes (e.g. via hash navigation).
  useEffect(() => {
    const btn = tabButtonRefs.current[tab];
    if (btn) btn.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tab]);

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
        task_max_run_seconds: settings.task_max_run_seconds,
        context_compaction: settings.context_compaction,
        compaction_interval: settings.compaction_interval,
        compaction_keep_turns: settings.compaction_keep_turns,
        history_mode: settings.history_mode,
        compaction_model: settings.compaction_model,
        compaction_model_provider_id: settings.compaction_model_provider_id,
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
  // Stable ref to mutation so the unmount cleanup doesn't fire on every render.
  // (useMutation returns a new object each render, so depending on it directly
  // would re-run the effect's cleanup constantly → infinite loop.)
  const mutationRef = useRef(updateMutation);
  mutationRef.current = updateMutation;

  const debouncedSave = useCallback(() => {
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(async () => {
      saveTimeoutRef.current = null;
      try {
        await mutationRef.current.mutateAsync(formRef.current);
        setSaved(true);
        setTimeout(() => setSaved(false), 2500);
      } catch {
        // Error state handled by updateMutation.isError
      }
    }, 800);
  }, []);

  // Flush pending save on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
        saveTimeoutRef.current = null;
        mutationRef.current.mutate(formRef.current);
      }
    };
  }, []);

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
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", backgroundColor: t.surface }}>
        <Spinner color={t.accent} />
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", backgroundColor: t.surface }}>
      {/* Header */}
      <div
        style={{
          flexShrink: 0,
          paddingTop: 12,
          borderBottom: `1px solid ${t.surfaceBorder}`,
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          backgroundColor: `${t.surface}e6`,
        }}
      >
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: isMobile ? 8 : 12, padding: isMobile ? "0 12px" : "0 16px", minHeight: 52 }}>
          <button
            className="header-icon-btn"
            onClick={goBack}
            style={{ width: isMobile ? 36 : 44, height: isMobile ? 36 : 44, flexShrink: 0 }}
          >
            <ArrowLeft size={isMobile ? 18 : 20} color={t.textMuted} />
          </button>
          <div style={{ flex: 1, minWidth: 0, padding: "8px 0" }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {channel?.display_name || channel?.name || channel?.client_id || "Channel"}
            </div>
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2, flexWrap: "wrap" }}>
              <span style={{ fontSize: 12, color: t.textDim }}>
                Settings
              </span>
              {settings?.bot_id && (
                <a
                  className="header-bot-link"
                  href={`/admin/bots/${settings.bot_id}`}
                  onClick={(e) => { e.preventDefault(); navigate(`/admin/bots/${settings.bot_id}`); }}
                  style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3, fontSize: 11, color: t.accent, textDecoration: "none", cursor: "pointer" }}
                >
                  <ExternalLink size={10} color={t.accent} />
                  {currentBot?.name || settings.bot_id}
                </a>
              )}
              {activatable?.filter(ig => ig.activated).map(ig => (
                <span key={ig.integration_type} style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3, fontSize: 11, color: t.success }}>
                  <Zap size={10} color={t.success} fill={t.success} />
                  {prettyIntegrationName(ig.integration_type)}
                </span>
              ))}
            </div>
          </div>
          {/* Auto-save status indicator */}
          {updateMutation.isPending && (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4, flexShrink: 0 }}>
              <Spinner size={10} color={t.textDim} />
              <span style={{ fontSize: 11, color: t.textDim }}>Saving</span>
            </div>
          )}
          {saved && !updateMutation.isPending && (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4, flexShrink: 0 }}>
              <Check size={12} color={t.success} />
              <span style={{ fontSize: 11, color: t.success }}>Saved</span>
            </div>
          )}
          {updateMutation.isError && !updateMutation.isPending && !saved && (
            <span style={{ fontSize: 11, color: "#ef4444", flexShrink: 0 }}>Save failed</span>
          )}
        </div>
      </div>

      {/* Tabs — single horizontally-scrollable row of underline tabs.
          Subtle separator between primary and diagnostic groups.
          No "More" dropdown — every tab is reachable in one place.
          Vertical mouse wheel is translated into horizontal scroll, and
          edge fades indicate when more tabs are off-screen. */}
      <div style={{ flexShrink: 0, width: "100%", minWidth: 0, position: "relative" }}>
        <div
          ref={tabBarRef}
          className="hide-scrollbar"
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "stretch",
            gap: 0,
            overflowX: "auto",
            WebkitOverflowScrolling: "touch",
            scrollbarWidth: "none",
            borderBottom: `1px solid ${t.surfaceBorder}`,
            padding: `0 ${isMobile ? 8 : 12}px`,
            maxWidth: "100%",
            minWidth: 0,
          }}
        >
          {ALL_TABS.map((tb) => {
            const isActive = tb.key === tab;
            return (
              <div key={tb.key} style={{ display: "flex", flexDirection: "row", alignItems: "stretch", flexShrink: 0 }}>
                {tb.separator && (
                  <div
                    aria-hidden
                    style={{
                      width: 1,
                      background: t.surfaceBorder,
                      margin: "10px 8px",
                      flexShrink: 0,
                    }}
                  />
                )}
                <button
                  ref={(el) => { tabButtonRefs.current[tb.key] = el; }}
                  onClick={() => setTab(tb.key)}
                  style={{
                    position: "relative",
                    padding: "12px 14px 11px",
                    fontSize: 13,
                    fontWeight: isActive ? 600 : 500,
                    background: "transparent",
                    border: "none",
                    color: isActive ? t.text : t.textDim,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                    transition: "color 0.15s",
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.color = t.textMuted;
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.color = t.textDim;
                  }}
                >
                  {tb.label}
                  {isActive && (
                    <div
                      style={{
                        position: "absolute",
                        left: 10,
                        right: 10,
                        bottom: -1,
                        height: 2,
                        background: t.accent,
                        borderRadius: "2px 2px 0 0",
                      }}
                    />
                  )}
                </button>
              </div>
            );
          })}
        </div>
        {/* Edge fades — only visible when there are off-screen tabs in that direction. */}
        {tabOverflow.left && (
          <div
            aria-hidden
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 1,
              width: 24,
              pointerEvents: "none",
              background: `linear-gradient(to right, ${t.surface}, ${t.surface}00)`,
            }}
          />
        )}
        {tabOverflow.right && (
          <div
            aria-hidden
            style={{
              position: "absolute",
              right: 0,
              top: 0,
              bottom: 1,
              width: 24,
              pointerEvents: "none",
              background: `linear-gradient(to left, ${t.surface}, ${t.surface}00)`,
            }}
          />
        )}
      </div>

      {/* Tab content */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        className="flex-1"
        contentContainerStyle={{ padding: isMobile ? 12 : 16, gap: isMobile ? 16 : 20, width: "100%", boxSizing: "border-box", overflowX: "hidden" } as any}
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
        {tab === "integrations" && <IntegrationsTab channelId={channelId!} workspaceEnabled={!!form.channel_workspace_enabled} />}
        {tab === "attachments" && <AttachmentsTab channelId={channelId!} />}
        {tab === "context" && <ContextTab channelId={channelId!} />}
        {tab === "workflows" && <WorkflowsTab channelId={channelId!} />}
        {tab === "tasks" && <TasksTab channelId={channelId!} botId={channel?.bot_id} />}
        {tab === "logs" && <LogsTab channelId={channelId!} />}
      </RefreshableScrollView>
    </div>
  );
}
