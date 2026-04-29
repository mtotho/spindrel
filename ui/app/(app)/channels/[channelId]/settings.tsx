import { Spinner } from "@/src/components/shared/Spinner";
import { useCallback, useState, useEffect, useRef } from "react";
import { useHashTab } from "@/src/hooks/useHashTab";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import { ArrowLeft, ExternalLink, Zap } from "lucide-react";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useChannel,
  useActivatableIntegrations,
} from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { useIsAdmin } from "@/src/hooks/useScope";
import { prettyIntegrationName } from "@/src/utils/format";
import type { ChannelSettings } from "@/src/types/api";
import { ActionButton, SaveStatusPill, type SaveStatusTone } from "@/src/components/shared/SettingsControls";
import { saveMatchesCurrentDraft, shouldApplyServerDraft } from "./autosaveDraft";

// Tab components
import { HistoryTab } from "./HistoryTab";
import { ContextTab } from "./ContextTab";
import { ToolsOverrideTab } from "./ToolsOverrideTab";
import { BindingsSection } from "./integrations/BindingsSection";
import { HeartbeatTab } from "./HeartbeatTab";
import { TasksTab } from "./TasksTab";
import { LogsTab } from "./LogsTab";
import { AttachmentsTab } from "./AttachmentsTab";
import { ChannelWorkspaceTab } from "./ChannelWorkspaceTab";
import { PipelinesTab } from "./PipelinesTab";
import { ParticipantsTab } from "./ParticipantsTab";
import { DashboardTab } from "./DashboardTab";
import {
  ChannelTabSections,
  AgentTabSections,
  PresentationTabSections,
  AutomationTabSections,
} from "./ChannelSettingsSections";

// ---------------------------------------------------------------------------
// Tab definitions — single flat list, all visible. A separator divides
// primary settings from diagnostic/operational tabs. The Integrations tab
// is admin-only (backend writes are gated by require_admin_and_scope) and
// is filtered out for non-admins below.
// ---------------------------------------------------------------------------
type TabDef = { key: string; label: string; separator?: boolean; adminOnly?: boolean };
type ChildSaveState = {
  dirty: boolean;
  isPending: boolean;
  isError: boolean;
  lastSavedAt: number | null;
};
type HeartbeatActions = {
  save: () => Promise<void>;
  revert: () => void;
};

const IDLE_CHILD_SAVE_STATE: ChildSaveState = {
  dirty: false,
  isPending: false,
  isError: false,
  lastSavedAt: null,
};

function buildChannelSettingsForm(settings: ChannelSettings): Partial<ChannelSettings> {
  return {
    name: settings.name,
    private: settings.private,
    user_id: settings.user_id,
    bot_id: settings.bot_id,
    require_mention: settings.require_mention,
    passive_memory: settings.passive_memory,
    allow_bot_messages: settings.allow_bot_messages,
    workspace_rag: settings.workspace_rag,
    pinned_widget_context_enabled: settings.pinned_widget_context_enabled,
    thinking_display: settings.thinking_display,
    tool_output_display: settings.tool_output_display,
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
    workspace_schema_template_id: settings.workspace_schema_template_id,
    workspace_schema_content: settings.workspace_schema_content,
    index_segments: settings.index_segments ?? [],
    project_id: settings.project_id ?? null,
    project: settings.project ?? null,
    project_workspace_id: settings.project_workspace_id ?? null,
    project_path: settings.project_path ?? null,
    tags: settings.tags ?? [],
    category: settings.category ?? null,
    chat_mode: settings.chat_mode ?? "default",
    header_backdrop_mode: settings.header_backdrop_mode ?? "glass",
    plan_mode_control: settings.plan_mode_control ?? "auto",
    layout_mode: settings.layout_mode,
    widget_theme_ref: settings.widget_theme_ref,
    pipeline_mode: settings.pipeline_mode,
  };
}

const ALL_TABS: TabDef[] = [
  { key: "channel", label: "Channel" },
  { key: "agent", label: "Agent" },
  { key: "presentation", label: "Presentation" },
  { key: "dashboard", label: "Dashboard" },
  { key: "knowledge", label: "Knowledge" },
  { key: "memory", label: "Memory" },
  { key: "automation", label: "Automation" },
  { key: "context", label: "Context", separator: true },
  { key: "logs", label: "Logs" },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function ChannelSettingsScreen() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const location = useLocation();
  const isAdmin = useIsAdmin();
  const { channelId } = useParams<{ channelId: string }>();
  const fromDashboard = new URLSearchParams(location.search).get("from") === "dashboard";
  const goBack = useGoBack(fromDashboard ? `/widgets/channel/${channelId}` : `/channels/${channelId}`);
  const { refreshing, onRefresh } = usePageRefresh();
  const { data: channel } = useChannel(channelId);
  const { data: settings, isLoading } = useChannelSettings(channelId);
  const { data: bots } = useBots();
  const updateMutation = useUpdateChannelSettings(channelId!);
  const { data: activatable } = useActivatableIntegrations(channelId);

  // Check if the channel's bot is in a workspace
  const currentBot = bots?.find((b: any) => b.id === settings?.bot_id);
  const isHarnessChannel = !!currentBot?.harness_runtime;
  const resolvedWorkspaceId = settings?.resolved_workspace_id ?? currentBot?.shared_workspace_id;
  const hasWorkspace = !!resolvedWorkspaceId;

  const hiddenHarnessTabs = new Set(["knowledge", "memory", "context"]);
  const visibleTabs = ALL_TABS.filter((tb) => {
    if (tb.adminOnly && !isAdmin) return false;
    if (isHarnessChannel && hiddenHarnessTabs.has(tb.key)) return false;
    return true;
  });
  const tabKeys = visibleTabs.map((tab) => tab.key);
  const [tab, setTab] = useHashTab("channel", tabKeys);
  const [form, setForm] = useState<Partial<ChannelSettings>>({});
  const [channelDirty, setChannelDirty] = useState(false);
  const [channelLastSavedAt, setChannelLastSavedAt] = useState<number | null>(null);
  const channelDirtyRef = useRef(false);
  const formRef = useRef(form);
  formRef.current = form;
  const [heartbeatSaveState, setHeartbeatSaveState] = useState<ChildSaveState>(IDLE_CHILD_SAVE_STATE);
  const heartbeatActionsRef = useRef<HeartbeatActions | null>(null);

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
      if (!shouldApplyServerDraft({
        dirty: channelDirtyRef.current,
        pending: updateMutation.isPending,
        hasScheduledSave: false,
      })) {
        return;
      }
      const nextForm = buildChannelSettingsForm(settings);
      setForm(nextForm);
      formRef.current = nextForm;
      channelDirtyRef.current = false;
      setChannelDirty(false);
    }
  }, [settings, updateMutation.isPending]);

  const patch = useCallback(
    <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => {
      setForm((f) => {
        const next = { ...f, [key]: value };
        formRef.current = next;
        return next;
      });
      channelDirtyRef.current = true;
      setChannelDirty(true);
    },
    []
  );

  const saveChannelSettingsOnly = useCallback(async () => {
    const draft = formRef.current;
    try {
      await updateMutation.mutateAsync(draft);
      if (saveMatchesCurrentDraft({ savedDraft: draft, currentDraft: formRef.current })) {
        channelDirtyRef.current = false;
        setChannelDirty(false);
        setChannelLastSavedAt(Date.now());
      }
    } catch {
      // Error state is surfaced by the header save pill.
    }
  }, [updateMutation]);

  const revertChannelSettingsOnly = useCallback(() => {
    if (!settings) return;
    const nextForm = buildChannelSettingsForm(settings);
    setForm(nextForm);
    formRef.current = nextForm;
    channelDirtyRef.current = false;
    setChannelDirty(false);
  }, [settings]);

  const saveAllSettings = useCallback(async () => {
    const saves: Promise<void>[] = [];
    if (channelDirty) saves.push(saveChannelSettingsOnly());
    if (heartbeatSaveState.dirty && heartbeatActionsRef.current) {
      saves.push(heartbeatActionsRef.current.save());
    }
    await Promise.all(saves);
  }, [channelDirty, heartbeatSaveState.dirty, saveChannelSettingsOnly]);

  const revertAllSettings = useCallback(() => {
    if (channelDirty) revertChannelSettingsOnly();
    if (heartbeatSaveState.dirty && heartbeatActionsRef.current) {
      heartbeatActionsRef.current.revert();
    }
  }, [channelDirty, heartbeatSaveState.dirty, revertChannelSettingsOnly]);

  const handleHeartbeatActionsChange = useCallback((actions: HeartbeatActions | null) => {
    heartbeatActionsRef.current = actions;
  }, []);

  const handleSetTab = useCallback((nextTab: string) => {
    if (nextTab === tab) return;
    if (tab === "automation" && heartbeatSaveState.dirty) {
      const discard = window.confirm("Discard unsaved heartbeat changes?");
      if (!discard) return;
      heartbeatActionsRef.current?.revert();
      setHeartbeatSaveState(IDLE_CHILD_SAVE_STATE);
    }
    setTab(nextTab);
  }, [heartbeatSaveState.dirty, setTab, tab]);

  const overallSaveTone: SaveStatusTone =
    updateMutation.isPending || heartbeatSaveState.isPending
      ? "pending"
      : updateMutation.isError || heartbeatSaveState.isError
        ? "error"
        : channelDirty || heartbeatSaveState.dirty
          ? "dirty"
          : channelLastSavedAt != null || heartbeatSaveState.lastSavedAt != null
            ? "saved"
            : "idle";
  const overallSaveLabel =
    overallSaveTone === "pending"
      ? "Saving changes"
      : overallSaveTone === "error"
        ? "Save failed"
        : overallSaveTone === "dirty"
          ? "Unsaved changes"
          : overallSaveTone === "saved"
            ? "Saved"
            : "";

  if (isLoading || !settings) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-surface">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-surface">
      {/* Header — no border-bottom. Tonal separation via spacing + the tab
          strip below. Per spindrel-ui SKILL §6: no border-b between stacked
          bars. */}
      <div className="shrink-0 bg-surface">
        <div className={`flex items-center ${isMobile ? "gap-2 px-3" : "gap-3 px-4"} min-h-[52px]`}>
          <button
            className={`header-icon-btn shrink-0 ${isMobile ? "w-9 h-9" : "w-11 h-11"}`}
            onClick={goBack}
            aria-label="Back"
          >
            <ArrowLeft size={isMobile ? 18 : 20} className="text-text-muted" />
          </button>
          <div className="flex-1 min-w-0 py-2">
            <h1 className="text-base font-bold text-text truncate">
              {channel?.display_name || channel?.name || channel?.client_id || "Channel"}
            </h1>
            <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
              <span className="text-xs text-text-dim">Settings</span>
              {settings?.bot_id && (
                <a
                  className="header-bot-link inline-flex items-center gap-0.5 text-[11px] text-accent hover:underline"
                  href={`/admin/bots/${settings.bot_id}`}
                  onClick={(e) => { e.preventDefault(); navigate(`/admin/bots/${settings.bot_id}`); }}
                >
                  <ExternalLink size={10} className="text-accent" />
                  {currentBot?.name || settings.bot_id}
                </a>
              )}
              {activatable?.filter(ig => ig.activated).map(ig => (
                <span
                  key={ig.integration_type}
                  className="inline-flex items-center gap-0.5 text-[11px] text-success"
                >
                  <Zap size={10} className="text-success fill-current" />
                  {prettyIntegrationName(ig.integration_type)}
                </span>
              ))}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
            <SaveStatusPill tone={overallSaveTone} label={overallSaveLabel} />
            <ActionButton
              label="Revert"
              onPress={revertAllSettings}
              variant="secondary"
              size="small"
              disabled={(!channelDirty && !heartbeatSaveState.dirty) || updateMutation.isPending || heartbeatSaveState.isPending}
            />
            <ActionButton
              label={updateMutation.isPending || heartbeatSaveState.isPending ? "Saving" : "Save"}
              onPress={saveAllSettings}
              size="small"
              disabled={(!channelDirty && !heartbeatSaveState.dirty) || updateMutation.isPending || heartbeatSaveState.isPending}
            />
          </div>
        </div>
      </div>

      {/* Tabs — single horizontally-scrollable row of underline tabs.
          Subtle separator between primary and diagnostic groups.
          No "More" dropdown — every tab is reachable in one place.
          Vertical mouse wheel is translated into horizontal scroll, and
          edge fades indicate when more tabs are off-screen. */}
      <div className="shrink-0 w-full min-w-0 relative">
        <div
          ref={tabBarRef}
          className={`hide-scrollbar flex items-stretch overflow-x-auto ${isMobile ? "px-2" : "px-3"} max-w-full min-w-0`}
          style={{ WebkitOverflowScrolling: "touch" }}
        >
          {visibleTabs.map((tb) => {
            const isActive = tb.key === tab;
            return (
              <div key={tb.key} className="flex items-stretch shrink-0">
                {tb.separator && (
                  <div
                    aria-hidden
                    className="w-px bg-surface-border my-2.5 mx-2 shrink-0"
                  />
                )}
                <button
                  ref={(el) => { tabButtonRefs.current[tb.key] = el; }}
                  onClick={() => handleSetTab(tb.key)}
                  data-active={isActive ? "true" : "false"}
                  className="relative px-3.5 pt-3 pb-[11px] text-[13px] whitespace-nowrap bg-transparent border-none cursor-pointer transition-colors text-text-dim hover:text-text-muted data-[active=true]:text-text data-[active=true]:font-semibold font-medium data-[active=true]:after:content-[''] data-[active=true]:after:absolute data-[active=true]:after:left-2.5 data-[active=true]:after:right-2.5 data-[active=true]:after:-bottom-px data-[active=true]:after:h-0.5 data-[active=true]:after:bg-accent data-[active=true]:after:rounded-t-sm"
                >
                  {tb.label}
                </button>
              </div>
            );
          })}
        </div>
        {/* Edge fades — only visible when there are off-screen tabs in that direction. */}
        {tabOverflow.left && (
          <div
            aria-hidden
            className="pointer-events-none absolute left-0 top-0 bottom-px w-6 bg-gradient-to-r from-surface to-transparent"
          />
        )}
        {tabOverflow.right && (
          <div
            aria-hidden
            className="pointer-events-none absolute right-0 top-0 bottom-px w-6 bg-gradient-to-l from-surface to-transparent"
          />
        )}
      </div>

      {/* Tab content */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        className="flex-1"
        contentContainerStyle={{ display: "flex", flexDirection: "column", padding: isMobile ? 14 : 20, gap: isMobile ? 20 : 28, width: "100%", boxSizing: "border-box", overflowX: "hidden" } as any}
        key={tab}
      >
        {tab === "channel" && (
          <>
            <ChannelTabSections form={form} patch={patch} channelId={channelId!} settings={settings} />
            <ParticipantsTab channelId={channelId!} primaryBotId={settings?.bot_id ?? ""} />
            {isAdmin && <BindingsSection channelId={channelId!} />}
          </>
        )}
        {tab === "agent" && (
          <>
            <AgentTabSections
              form={form}
              patch={patch}
              bots={bots}
              settings={settings}
              workspaceId={currentBot?.shared_workspace_id}
              channelId={channelId!}
              currentBot={currentBot}
            />
            <ToolsOverrideTab channelId={channelId!} botId={channel?.bot_id} isHarness={isHarnessChannel} />
          </>
        )}
        {tab === "presentation" && (
          <PresentationTabSections form={form} patch={patch} channelId={channelId!} />
        )}
        {tab === "dashboard" && (
          <DashboardTab channelId={channelId!} />
        )}
        {tab === "knowledge" && (
          <>
          <ChannelWorkspaceTab
            form={form}
            patch={patch}
            channelId={channelId!}
            workspaceId={resolvedWorkspaceId ?? undefined}
            botId={currentBot?.id}
            indexSegmentDefaults={settings?.index_segment_defaults}
            hasSharedWorkspace={hasWorkspace}
            sharedWorkspaceId={currentBot?.shared_workspace_id}
            botKnowledgeAutoRetrieval={currentBot?.workspace?.bot_knowledge_auto_retrieval !== false}
          />
            <AttachmentsTab channelId={channelId!} />
          </>
        )}
        {tab === "memory" && (
          <HistoryTab form={form} patch={patch} channelId={channelId!} workspaceId={currentBot?.shared_workspace_id} memoryScheme={currentBot?.memory_scheme} botHistoryMode={currentBot?.history_mode} />
        )}
        {tab === "automation" && (
          <>
            <AutomationTabSections form={form} patch={patch} />
            <HeartbeatTab
              channelId={channelId!}
              workspaceId={currentBot?.shared_workspace_id}
              botModel={currentBot?.model}
              isHarnessChannel={isHarnessChannel}
              onSaveStateChange={setHeartbeatSaveState}
              onActionsChange={handleHeartbeatActionsChange}
            />
            <PipelinesTab channelId={channelId!} />
            <TasksTab channelId={channelId!} botId={channel?.bot_id} />
          </>
        )}
        {tab === "context" && <ContextTab channelId={channelId!} />}
        {tab === "logs" && <LogsTab channelId={channelId!} />}
      </RefreshableScrollView>
    </div>
  );
}
