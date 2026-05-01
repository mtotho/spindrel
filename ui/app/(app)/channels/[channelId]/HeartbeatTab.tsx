import { useState, useEffect, useRef, useCallback } from "react";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import { Play, RotateCcw, Pencil, FileText, Workflow as WorkflowIcon } from "lucide-react";
import {
  Section, FormRow, TextInput, SelectInput, Toggle,
  Row, Col,
} from "@/src/components/shared/FormControls";
import { AdvancedSection, ActionButton, SettingsSegmentedControl, StatusBadge } from "@/src/components/shared/SettingsControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { PromptTemplateLink } from "@/src/components/shared/PromptTemplateLink";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { SessionTargetPicker } from "@/src/components/shared/SessionTargetPicker";
import type { SessionTarget } from "@/src/api/hooks/useTasks";
import { useRunPresets } from "@/src/api/hooks/useRunPresets";
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";
import { useChannels } from "@/src/api/hooks/useChannels";
import { apiFetch } from "@/src/api/client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { WorkflowSelector } from "@/src/components/shared/WorkflowSelector";
import { useWorkflows } from "@/src/api/hooks/useWorkflows";
import { useTools } from "@/src/api/hooks/useTools";
import { ToolMultiPicker } from "@/src/components/shared/task/ChipPicker";

import { QuietHoursPicker } from "./QuietHoursPicker";
import { HeartbeatHistoryList } from "./HeartbeatHistoryList";
import { ContextPreview, HeartbeatTemplatePreview } from "./HeartbeatContextPreview";
import { SpatialPolicyCard } from "./SpatialBotPolicyControls";
import { HeartbeatExecutionControls, normalizeExecutionPolicy } from "./HeartbeatExecutionControls";
import { saveMatchesCurrentDraft, shouldApplyServerDraft } from "./autosaveDraft";

// ---------------------------------------------------------------------------
// Interval options for heartbeat
// ---------------------------------------------------------------------------
const INTERVAL_OPTIONS = [
  { label: "5 minutes", value: "5" },
  { label: "15 minutes", value: "15" },
  { label: "30 minutes", value: "30" },
  { label: "1 hour", value: "60" },
  { label: "2 hours", value: "120" },
  { label: "3 hours", value: "180" },
  { label: "4 hours", value: "240" },
  { label: "6 hours", value: "360" },
  { label: "8 hours", value: "480" },
  { label: "12 hours", value: "720" },
  { label: "24 hours", value: "1440" },
];

function formatIntervalLabel(minutes: number): string {
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  if (minutes % 60 === 0) {
    const h = minutes / 60;
    return `${h} hour${h === 1 ? "" : "s"}`;
  }
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${m}m`;
}

function buildIntervalOptions(current: number | null | undefined) {
  const currentStr = current != null ? String(current) : null;
  if (currentStr && !INTERVAL_OPTIONS.some((o) => o.value === currentStr)) {
    return [...INTERVAL_OPTIONS, { label: formatIntervalLabel(current as number), value: currentStr }];
  }
  return INTERVAL_OPTIONS;
}

function withIssueReportingDefault(executionConfig: any, enabled: boolean) {
  return {
    ...(executionConfig ?? {}),
    allow_issue_reporting: enabled,
  };
}

function mergeUniqueStrings(current: unknown, incoming: unknown): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const list of [current, incoming]) {
    if (!Array.isArray(list)) continue;
    for (const item of list) {
      if (typeof item !== "string" || !item.trim()) continue;
      const key = item.trim();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(key);
    }
  }
  return out;
}

function RunNowButton({
  label,
  onClick,
  disabled,
  title,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      title={title}
      className={
        "inline-flex min-h-[38px] shrink-0 items-center justify-center gap-1.5 rounded-md " +
        "border border-accent/35 bg-accent/[0.08] px-3.5 text-[13px] font-semibold text-accent " +
        "transition-colors hover:border-accent/55 hover:bg-accent/[0.12] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35 " +
        "disabled:cursor-default disabled:border-surface-border disabled:bg-transparent disabled:text-text-dim"
      }
    >
      <Play size={13} />
      {label}
    </button>
  );
}

function HeartbeatTabLoading({
  workflowMode = false,
  workspaceFileLinked = false,
  templateLinked = false,
  dispatchResults = false,
}: {
  workflowMode?: boolean;
  workspaceFileLinked?: boolean;
  templateLinked?: boolean;
  dispatchResults?: boolean;
}) {
  const placeholder = "rounded-md border border-input-border bg-input/55";
  const mutedLine = "rounded-full bg-surface-overlay/60";
  const mutedButton = "inline-flex h-[24px] rounded border border-surface-border bg-transparent";
  const toggleRow = "flex min-h-[32px] items-start gap-2.5 py-1.5";

  return (
    <>
      <Section
        title={
          <div className="flex flex-wrap items-center gap-2">
            <span>Heartbeat</span>
            <StatusBadge label="Loading" variant="neutral" />
          </div>
        }
        description="Heartbeat schedules background runs for this channel."
        action={
          <span className="block h-[34px] w-16 rounded-md bg-surface-overlay/35" aria-hidden />
        }
      >
        {null}
      </Section>

      <div className="flex flex-col gap-5" aria-busy="true" aria-label="Loading heartbeat settings">
        <Section title="Schedule">
          <div className="flex w-full flex-col gap-1.5">
            <span className={`${mutedLine} h-3 w-16`} aria-hidden />
            <span className={`${placeholder} h-10 w-full`} aria-hidden />
          </div>
        </Section>

        <Section title="Action">
          <div className="mb-3">
            <div className="inline-flex rounded-md bg-surface-raised/40 p-1" aria-hidden>
              <span className={`h-[30px] w-[87px] rounded-md ${workflowMode ? "bg-surface-overlay/35" : "bg-surface-overlay/70"}`} />
              <span className={`h-[30px] w-[103px] rounded-md ${workflowMode ? "bg-surface-overlay/70" : "bg-surface-overlay/35"}`} />
            </div>
          </div>

          {workflowMode ? (
            <div className="flex flex-col gap-2" aria-hidden>
              <div className="flex flex-col gap-1.5">
                <span className={`${mutedLine} h-3 w-20`} />
                <span className={`${placeholder} h-10 w-full`} />
                <span className={`${mutedLine} h-3 w-72 opacity-70`} />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className={`${mutedLine} h-3 w-24`} />
                <span className={`${placeholder} h-10 w-full`} />
                <span className={`${mutedLine} h-3 w-80 opacity-70`} />
              </div>
            </div>
          ) : (
            <>
              {workspaceFileLinked ? (
                <div className={`${placeholder} mb-1 h-[92px] w-full`} aria-hidden />
              ) : (
                <>
                  <div className={`${mutedButton} mb-1 w-[143px]`} aria-hidden />
                  <div className="mb-1 flex flex-wrap items-center gap-1.5" aria-hidden>
                    <span className={`${mutedButton} w-[105px]`} />
                  </div>
                  {templateLinked ? (
                    <div className={`${placeholder} h-[228px] w-full`} aria-hidden />
                  ) : (
                    <div className="flex flex-col gap-1.5" aria-hidden>
                      <div className="flex min-h-[30px] items-center justify-between gap-2">
                        <div className="min-w-0">
                          <span className={`${mutedLine} block h-3 w-[112px]`} />
                          <span className={`${mutedLine} mt-1 block h-3 w-[96px] opacity-70`} />
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <span className="h-7 w-[72px] rounded-md bg-surface-overlay/35" />
                          <span className="h-7 w-[57px] rounded-md bg-surface-overlay/35" />
                        </div>
                      </div>
                      <div className={`${placeholder} h-[280px] w-full`} />
                      <div className="flex min-h-[17px] items-center justify-between gap-3">
                        <span className={`${mutedLine} h-3 w-[410px] max-w-[45%] opacity-70`} />
                        <span className={`${mutedLine} h-3 w-[104px] opacity-70`} />
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </Section>

        {!workflowMode && (
          <Section title="Dispatch">
            <div className="flex flex-col gap-2" aria-hidden>
              <div className={toggleRow}>
                <span className="mt-0.5 h-5 w-[34px] shrink-0 rounded-full bg-surface-border" />
                <span className={`${mutedLine} mt-1 h-4 w-[150px]`} />
              </div>
              {dispatchResults && (
                <div className="flex flex-col gap-1.5">
                  <span className={`${mutedLine} h-3 w-[92px]`} />
                  <span className={`${placeholder} h-10 w-full`} />
                  <span className={`${mutedLine} h-3 w-[240px] opacity-70`} />
                </div>
              )}
              <div className={toggleRow}>
                <span className="mt-0.5 h-5 w-[34px] shrink-0 rounded-full bg-surface-border" />
                <div className="min-w-0">
                  <span className={`${mutedLine} block h-4 w-[246px]`} />
                  <span className={`${mutedLine} mt-1 block h-3 w-[370px] opacity-70`} />
                </div>
              </div>
            </div>
          </Section>
        )}

        <div className="mt-1 flex min-h-[40px] flex-wrap gap-2" aria-hidden>
          <span className="h-10 w-[93px] rounded-md bg-surface-overlay/35" />
          {!workflowMode && (
            <span className={`${mutedLine} self-center h-3 w-[310px] opacity-70`} />
          )}
        </div>

        {!workflowMode && (
          <div className="mt-2.5" aria-hidden>
            <div className="flex min-h-[44px] items-center gap-1.5 px-0.5">
              <span className={`${mutedLine} h-3 w-[135px] opacity-70`} />
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Heartbeat Tab
// ---------------------------------------------------------------------------
type HeartbeatSaveState = {
  dirty: boolean;
  isPending: boolean;
  isError: boolean;
  lastSavedAt: number | null;
};

type HeartbeatActions = {
  save: () => Promise<void>;
  revert: () => void;
};

export function HeartbeatTab({
  channelId,
  workspaceId,
  botModel,
  isHarnessChannel = false,
  onSaveStateChange,
  onActionsChange,
}: {
  channelId: string;
  workspaceId?: string | null;
  botModel?: string;
  isHarnessChannel?: boolean;
  onSaveStateChange?: (state: HeartbeatSaveState) => void;
  onActionsChange?: (actions: HeartbeatActions | null) => void;
}) {
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();
  const [hbFirePollStartedAt, setHbFirePollStartedAt] = useState<number | null>(null);
  const { data, isFetching, isLoading } = useQuery({
    queryKey: ["channel-heartbeat", channelId],
    queryFn: () => apiFetch<any>(`/api/v1/admin/channels/${channelId}/heartbeat`),
    refetchOnMount: "always",
    refetchInterval: hbFirePollStartedAt ? 2000 : false,
  });
  const { data: channels } = useChannels();
  const channel = channels?.find((c: any) => c.id === channelId) as any;
  const spatialBots = [
    channel?.bot_id ? { botId: channel.bot_id, name: channel.bot_name || channel.bot_id, label: "Primary" } : null,
    ...((channel?.member_bots ?? []) as Array<any>).map((m) => ({
      botId: m.bot_id,
      name: m.bot_name || m.bot_id,
      label: "Member",
    })),
  ].filter(Boolean) as Array<{ botId: string; name: string; label: string }>;

  const [hbForm, setHbForm] = useState<any>(null);
  const [initialHeartbeatApplied, setInitialHeartbeatApplied] = useState(false);
  const [hbDirty, setHbDirty] = useState(false);
  const [hbLastSavedAt, setHbLastSavedAt] = useState<number | null>(null);
  const [customizedFromTemplateId, setCustomizedFromTemplateId] = useState<string | null>(null);
  const [templatePreviewExpanded, setTemplatePreviewExpanded] = useState(false);
  const hbFormRef = useRef<any>(null);
  const hbDirtyRef = useRef(false);
  const hbSavePendingRef = useRef(false);

  // Fetch templates to render linked template content
  const { data: allTemplates } = usePromptTemplates();
  const linkedTemplate = allTemplates?.find((tpl) => tpl.id === hbForm?.prompt_template_id);

  // Fetch workflows for the workflow selector
  const { data: workflows } = useWorkflows();
  const { data: allTools = [] } = useTools();
  const { data: heartbeatPresetData } = useRunPresets("channel_heartbeat");

  useEffect(() => {
    setHbForm(null);
    hbFormRef.current = null;
    setInitialHeartbeatApplied(false);
  }, [channelId]);

  useEffect(() => {
    if (!data || isFetching) return;
    if (!shouldApplyServerDraft({
      dirty: hbDirtyRef.current,
      pending: hbSavePendingRef.current,
      hasScheduledSave: false,
    })) {
      return;
    }
    if (data?.config) {
      const nextForm = {
        enabled: data.config.enabled ?? false,
        interval_minutes: data.config.interval_minutes ?? 60,
        model: data.config.model ?? "",
        model_provider_id: data.config.model_provider_id ?? "",
        fallback_models: data.config.fallback_models ?? [],
        prompt: data.config.prompt ?? "",
        dispatch_results: data.config.dispatch_results ?? true,
        dispatch_mode: data.config.dispatch_mode ?? "always",
        trigger_response: data.config.trigger_response ?? false,
        prompt_template_id: data.config.prompt_template_id ?? null,
        workspace_file_path: data.config.workspace_file_path ?? null,
        workspace_id: data.config.workspace_id ?? null,
        max_run_seconds: data.config.max_run_seconds ?? null,
        previous_result_max_chars: data.config.previous_result_max_chars ?? null,
        repetition_detection: data.config.repetition_detection ?? null,
        quiet_start: data.config.quiet_start ?? "",
        quiet_end: data.config.quiet_end ?? "",
        timezone: data.config.timezone ?? "",
        workflow_id: data.config.workflow_id ?? null,
        workflow_session_mode: data.config.workflow_session_mode ?? null,
        skip_tool_approval: data.config.skip_tool_approval ?? false,
        append_spatial_prompt: data.config.append_spatial_prompt ?? false,
        append_spatial_map_overview: data.config.append_spatial_map_overview ?? false,
        include_pinned_widgets: data.config.include_pinned_widgets ?? false,
        runner_mode: data.config.runner_mode ?? null,
        harness_effort: data.config.harness_effort ?? "",
        effective_runner_mode: data.config.effective_runner_mode ?? (isHarnessChannel ? "harness" : "spindrel"),
        execution_policy: normalizeExecutionPolicy(
          data.config.execution_policy,
          data.default_execution_policy,
          data.execution_policy_presets,
        ),
        execution_config: data.config.execution_config ?? {},
      };
      setHbForm(nextForm);
      hbFormRef.current = nextForm;
      setInitialHeartbeatApplied(true);
      hbDirtyRef.current = false;
      setHbDirty(false);
    } else if (data && !data.config) {
      const nextForm = {
        enabled: false,
        interval_minutes: 60,
        model: "",
        model_provider_id: "",
        fallback_models: [],
        prompt: "",
        dispatch_results: true,
        dispatch_mode: "always",
        trigger_response: false,
        prompt_template_id: null,
        workspace_file_path: null,
        workspace_id: null,
        max_run_seconds: null,
        previous_result_max_chars: null,
        repetition_detection: null,
        quiet_start: "",
        quiet_end: "",
        timezone: "",
        workflow_id: null,
        workflow_session_mode: null,
        skip_tool_approval: false,
        append_spatial_prompt: false,
        append_spatial_map_overview: false,
        include_pinned_widgets: false,
        runner_mode: null,
        harness_effort: "",
        effective_runner_mode: isHarnessChannel ? "harness" : "spindrel",
        execution_policy: normalizeExecutionPolicy(
          null,
          data.default_execution_policy,
          data.execution_policy_presets,
        ),
        execution_config: withIssueReportingDefault({}, true),
      };
      setHbForm(nextForm);
      hbFormRef.current = nextForm;
      setInitialHeartbeatApplied(true);
      hbDirtyRef.current = false;
      setHbDirty(false);
    }
  }, [data, isFetching, isHarnessChannel]);

  const saveMutation = useMutation({
    mutationFn: (body: any) => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
    onSuccess: (_saved: any, draft: any) => {
      queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      queryClient.invalidateQueries({ queryKey: ["channel-spatial-bot-policy", channelId] });
      if (saveMatchesCurrentDraft({ savedDraft: draft, currentDraft: hbFormRef.current })) {
        hbDirtyRef.current = false;
        setHbDirty(false);
        setHbLastSavedAt(Date.now());
      }
    },
  });

  const saveMutationRef = useRef(saveMutation);
  saveMutationRef.current = saveMutation;

  const updateHbForm = useCallback((updater: (prev: any) => any) => {
    const current = hbFormRef.current;
    const nextForm = updater(current);
    if (!nextForm) return;
    hbFormRef.current = nextForm;
    setHbForm(nextForm);
    hbDirtyRef.current = true;
    setHbDirty(true);
    setHbLastSavedAt(null);
    saveMutationRef.current.reset();
  }, []);

  const saveHeartbeat = useCallback(async () => {
    if (!hbFormRef.current) return;
    const draft = { ...hbFormRef.current, dispatch_mode: "always" };
    hbSavePendingRef.current = true;
    try {
      await saveMutationRef.current.mutateAsync(draft);
    } catch {
      // Error state is surfaced via saveMutation.isError / header pill.
    } finally {
      hbSavePendingRef.current = false;
    }
  }, []);

  const revertHeartbeat = useCallback(() => {
    if (!data) return;
    const source = data.config;
    const nextForm = source ? {
      enabled: source.enabled ?? false,
      interval_minutes: source.interval_minutes ?? 60,
      model: source.model ?? "",
      model_provider_id: source.model_provider_id ?? "",
      fallback_models: source.fallback_models ?? [],
      prompt: source.prompt ?? "",
      dispatch_results: source.dispatch_results ?? true,
      dispatch_mode: source.dispatch_mode ?? "always",
      trigger_response: source.trigger_response ?? false,
      prompt_template_id: source.prompt_template_id ?? null,
      workspace_file_path: source.workspace_file_path ?? null,
      workspace_id: source.workspace_id ?? null,
      max_run_seconds: source.max_run_seconds ?? null,
      previous_result_max_chars: source.previous_result_max_chars ?? null,
      repetition_detection: source.repetition_detection ?? null,
      quiet_start: source.quiet_start ?? "",
      quiet_end: source.quiet_end ?? "",
      timezone: source.timezone ?? "",
      workflow_id: source.workflow_id ?? null,
      workflow_session_mode: source.workflow_session_mode ?? null,
      skip_tool_approval: source.skip_tool_approval ?? false,
      append_spatial_prompt: source.append_spatial_prompt ?? false,
      append_spatial_map_overview: source.append_spatial_map_overview ?? false,
      include_pinned_widgets: source.include_pinned_widgets ?? false,
      runner_mode: source.runner_mode ?? null,
      harness_effort: source.harness_effort ?? "",
      effective_runner_mode: source.effective_runner_mode ?? (isHarnessChannel ? "harness" : "spindrel"),
      execution_policy: normalizeExecutionPolicy(
        source.execution_policy,
        data.default_execution_policy,
        data.execution_policy_presets,
      ),
      execution_config: source.execution_config ?? {},
    } : {
      enabled: false,
      interval_minutes: 60,
      model: "",
      model_provider_id: "",
      fallback_models: [],
      prompt: "",
      dispatch_results: true,
      dispatch_mode: "always",
      trigger_response: false,
      prompt_template_id: null,
      workspace_file_path: null,
      workspace_id: null,
      max_run_seconds: null,
      previous_result_max_chars: null,
      repetition_detection: null,
      quiet_start: "",
      quiet_end: "",
      timezone: "",
      workflow_id: null,
      workflow_session_mode: null,
      skip_tool_approval: false,
      append_spatial_prompt: false,
      append_spatial_map_overview: false,
      include_pinned_widgets: false,
      runner_mode: null,
      harness_effort: "",
      effective_runner_mode: isHarnessChannel ? "harness" : "spindrel",
      execution_policy: normalizeExecutionPolicy(
        null,
        data.default_execution_policy,
        data.execution_policy_presets,
      ),
      execution_config: withIssueReportingDefault({}, true),
    };
    setHbForm(nextForm);
    hbFormRef.current = nextForm;
    hbDirtyRef.current = false;
    setHbDirty(false);
    setHbLastSavedAt(null);
    setCustomizedFromTemplateId(null);
    setTemplatePreviewExpanded(false);
    saveMutationRef.current.reset();
  }, [data, isHarnessChannel]);

  const updateExecutionPreset = useCallback((preset: string) => {
    updateHbForm((f: any) => {
      const values = data?.execution_policy_presets?.[preset];
      if (!values) {
        return {
          ...f,
          execution_policy: {
            ...normalizeExecutionPolicy(f.execution_policy, data?.default_execution_policy, data?.execution_policy_presets),
            preset: "custom",
          },
        };
      }
      return {
        ...f,
        execution_policy: {
          ...normalizeExecutionPolicy(f.execution_policy, data?.default_execution_policy, data?.execution_policy_presets),
          preset,
          ...values,
        },
      };
    });
  }, [data?.default_execution_policy, data?.execution_policy_presets, updateHbForm]);

  const updateExecutionNumber = useCallback((field: string, value: string) => {
    const parsed = parseInt(value, 10);
    updateHbForm((f: any) => ({
      ...f,
      execution_policy: {
        ...normalizeExecutionPolicy(f.execution_policy, data?.default_execution_policy, data?.execution_policy_presets),
        preset: "custom",
        [field]: Number.isNaN(parsed) ? null : parsed,
      },
    }));
  }, [data?.default_execution_policy, data?.execution_policy_presets, updateHbForm]);

  const updateExecutionToolSurface = useCallback((toolSurface: string) => {
    updateHbForm((f: any) => ({
      ...f,
      execution_policy: {
        ...normalizeExecutionPolicy(f.execution_policy, data?.default_execution_policy, data?.execution_policy_presets),
        tool_surface: toolSurface,
      },
    }));
  }, [data?.default_execution_policy, data?.execution_policy_presets, updateHbForm]);

  useEffect(() => {
    onSaveStateChange?.({
      dirty: hbDirty,
      isPending: saveMutation.isPending,
      isError: saveMutation.isError,
      lastSavedAt: hbLastSavedAt,
    });
  }, [
    hbDirty,
    hbLastSavedAt,
    onSaveStateChange,
    saveMutation.isError,
    saveMutation.isPending,
  ]);

  useEffect(() => {
    onActionsChange?.({ save: saveHeartbeat, revert: revertHeartbeat });
    return () => onActionsChange?.(null);
  }, [onActionsChange, revertHeartbeat, saveHeartbeat]);

  const [hbFired, setHbFired] = useState(false);
  const fireMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat/fire`, { method: "POST" }),
    onSuccess: () => {
      const startedAt = Date.now();
      setHbFirePollStartedAt(startedAt);
      queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] });
      setHbFired(true);
      setTimeout(() => setHbFired(false), 3000);
    },
  });

  useEffect(() => {
    if (!hbFirePollStartedAt) return;
    const recentRuns = (data?.history ?? []) as Array<{ run_at?: string; status?: string }>;
    const newRun = recentRuns.find((run) => {
      if (!run.run_at) return false;
      return new Date(run.run_at).getTime() >= hbFirePollStartedAt - 5000;
    });
    if (newRun && (newRun.status === "complete" || newRun.status === "failed")) {
      setHbFirePollStartedAt(null);
      return;
    }
    if (Date.now() - hbFirePollStartedAt > 120_000) {
      setHbFirePollStartedAt(null);
    }
  }, [data?.history, hbFirePollStartedAt]);

  if (isLoading || !initialHeartbeatApplied || !hbForm) {
    return (
      <HeartbeatTabLoading
        workflowMode={!!data?.config?.workflow_id}
        workspaceFileLinked={!!data?.config?.workspace_file_path}
        templateLinked={!!data?.config?.prompt_template_id}
        dispatchResults={data?.config?.dispatch_results ?? false}
      />
    );
  }

  const enabled = hbForm.enabled ?? false;
  const runnerMode = hbForm.runner_mode ?? hbForm.effective_runner_mode ?? (isHarnessChannel ? "harness" : "spindrel");
  const isHarnessRunner = isHarnessChannel && runnerMode === "harness";
  const isWorkflowMode = !isHarnessRunner && !!hbForm.workflow_id;
  const hasAction = isWorkflowMode
    ? !!hbForm.workflow_id
    : !!(hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path || hbForm.append_spatial_prompt || hbForm.append_spatial_map_overview);
  const sessionTarget = (hbForm.execution_config?.session_target as SessionTarget | undefined) ?? { mode: "primary" };
  const runNowLabel = hbFirePollStartedAt ? "Running..." : hbFired ? "Fired" : fireMutation.isPending ? "Firing..." : "Run Now";
  const runNowDisabled = hbDirty || !hasAction || fireMutation.isPending || !!hbFirePollStartedAt;
  const runNowTitle = hbDirty
    ? "Save heartbeat changes before running manually."
    : !hasAction
      ? "Add a prompt or pipeline before running heartbeat manually."
      : undefined;
  const heartbeatProfiles = heartbeatPresetData?.presets ?? [];
  const spatialWidgetProfile = heartbeatProfiles.find((preset) => preset.id === "spatial_widget_steward_heartbeat");
  const spatialWidgetProfileDefaults = spatialWidgetProfile?.heartbeat_defaults;
  const spatialWidgetProfileActive = !!spatialWidgetProfileDefaults
    && !!hbForm.append_spatial_prompt
    && !!hbForm.append_spatial_map_overview
    && !!hbForm.include_pinned_widgets
    && mergeUniqueStrings([], hbForm.execution_config?.tools).includes("inspect_spatial_widget_scene")
    && mergeUniqueStrings([], hbForm.execution_config?.skills).includes("widgets/spatial_stewardship");
  const applySpatialWidgetProfile = () => {
    if (!spatialWidgetProfileDefaults) return;
    updateHbForm((f: any) => {
      const currentExecution = f.execution_config ?? {};
      const nextExecution = {
        ...currentExecution,
        ...spatialWidgetProfileDefaults.execution_config,
        tools: mergeUniqueStrings(currentExecution.tools, spatialWidgetProfileDefaults.execution_config?.tools),
        skills: mergeUniqueStrings(currentExecution.skills, spatialWidgetProfileDefaults.execution_config?.skills),
      };
      return {
        ...f,
        append_spatial_prompt: spatialWidgetProfileDefaults.append_spatial_prompt,
        append_spatial_map_overview: spatialWidgetProfileDefaults.append_spatial_map_overview,
        include_pinned_widgets: spatialWidgetProfileDefaults.include_pinned_widgets,
        execution_config: nextExecution,
      };
    });
  };

  return (
    <>
      <Section
        title={
          <div className="flex flex-wrap items-center gap-2">
            <span>Heartbeat</span>
            <StatusBadge label={enabled ? "Enabled" : "Disabled"} variant={enabled ? "success" : "neutral"} />
            {hbDirty && <StatusBadge label="Unsaved" variant="warning" />}
          </div>
        }
        description={enabled
          ? "Heartbeat schedules background runs for this channel."
          : "Heartbeat is disabled. You can still configure it here, then enable it when the schedule is ready."}
        action={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <RunNowButton
              label={runNowLabel}
              onClick={() => fireMutation.mutate()}
              disabled={runNowDisabled}
              title={runNowTitle}
            />
          </div>
        }
      >
        <div className="flex flex-col gap-1">
          <Toggle
            value={enabled}
            onChange={(v) => updateHbForm((f: any) => ({ ...f, enabled: v }))}
            label="Enabled"
            description="Runs on the configured schedule after these settings are saved."
          />
          {hbDirty && (
            <span className="text-[11px] text-text-dim">
              Save changes before running heartbeat manually.
            </span>
          )}
          {!hbDirty && !hasAction && (
            <span className="text-[11px] text-text-dim">
              Add a prompt or pipeline before running heartbeat manually.
            </span>
          )}
        </div>
      </Section>

      <div className="flex flex-col gap-5">
        {isHarnessChannel && (
          <Section
            title="Runner"
            description={isHarnessRunner
              ? "Heartbeat runs queue one-shot host hints for the configured harness session target."
              : "Heartbeat runs use the normal Spindrel agent loop for this harness channel."}
          >
            <SettingsSegmentedControl
              value={isHarnessRunner ? "harness" : "spindrel"}
              onChange={(mode) => updateHbForm((f: any) => ({
                ...f,
                runner_mode: mode,
                effective_runner_mode: mode,
                workflow_id: mode === "harness" ? null : f.workflow_id,
                workflow_session_mode: mode === "harness" ? null : f.workflow_session_mode,
                dispatch_results: mode === "harness" ? false : f.dispatch_results,
                trigger_response: mode === "harness" ? false : f.trigger_response,
              }))}
              options={[
                { value: "harness", label: "Run with harness" },
                { value: "spindrel", label: "Use Spindrel agent" },
              ]}
            />
            {!isHarnessRunner && !hbForm.model && (
              <p className="mt-2 text-[11px] text-warning-muted">
                Choose an explicit heartbeat model before enabling this Spindrel-agent runner.
              </p>
            )}
          </Section>
        )}

        {/* ---- Schedule Section ---- */}
        <Section title="Schedule">
          <Row stack={isMobile}>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Interval">
                <SelectInput
                  value={hbForm.interval_minutes?.toString() ?? "60"}
                  onChange={(v) => updateHbForm((f: any) => ({ ...f, interval_minutes: parseInt(v, 10) }))}
                  options={buildIntervalOptions(hbForm.interval_minutes)}
                />
              </FormRow>
            </Col>
          </Row>
        </Section>

        <Section title="Run Target">
          <FormRow
            label="Session"
            description="Choose which channel session heartbeat runs use for chat context and output."
          >
            <SessionTargetPicker
              channelId={channelId}
              value={sessionTarget}
              onChange={(target) => updateHbForm((f: any) => ({
                ...f,
                execution_config: {
                  ...(f.execution_config ?? {}),
                  session_target: target,
                },
              }))}
            />
          </FormRow>
        </Section>

        <Section
          title={
            <div className="flex flex-wrap items-center gap-2">
              <span>Escalation</span>
              <StatusBadge
                label={hbForm.execution_config?.allow_issue_reporting ? "Can report blockers" : "Reporting off"}
                variant={hbForm.execution_config?.allow_issue_reporting ? "success" : "neutral"}
              />
            </div>
          }
          description="Heartbeat runs can raise durable blockers, missing permissions, or recurring system problems into Mission Control instead of burying them in noisy logs."
        >
          <Toggle
            value={!!hbForm.execution_config?.allow_issue_reporting}
            onChange={(v) => updateHbForm((f: any) => ({
              ...f,
              execution_config: withIssueReportingDefault(f.execution_config, v),
            }))}
            label="Report blockers to Mission Control"
            description="Enabled for new heartbeats. Turn it off only when this automation should never create review items."
          />
        </Section>

        {/* ---- Model Section ---- */}
        {isHarnessRunner ? (
          <Section title="Harness Model">
            <Row stack={isMobile}>
              <Col minWidth={isMobile ? 0 : 220}>
                <LlmModelDropdown
                  label="Submodel"
                  value={hbForm.model ?? ""}
                  selectedProviderId={hbForm.model_provider_id ?? null}
                  onChange={(v, providerId) => updateHbForm((f: any) => ({
                    ...f,
                    model: v,
                    model_provider_id: v ? (providerId ?? null) : null,
                  }))}
                  placeholder="inherit from harness session"
                  allowClear
                />
              </Col>
              <Col minWidth={isMobile ? 0 : 180}>
                <FormRow label="Effort">
                  <SelectInput
                    value={hbForm.harness_effort || ""}
                    onChange={(v) => updateHbForm((f: any) => ({ ...f, harness_effort: v || "" }))}
                    options={[
                      { label: "inherit", value: "" },
                      { label: "low", value: "low" },
                      { label: "medium", value: "medium" },
                      { label: "high", value: "high" },
                    ]}
                  />
                </FormRow>
              </Col>
            </Row>
          </Section>
        ) : <Section title="Model">
          <Row stack={isMobile}>
            <Col minWidth={isMobile ? 0 : 200}>
              <LlmModelDropdown
                label="Model"
                value={hbForm.model ?? ""}
                selectedProviderId={hbForm.model_provider_id ?? null}
                onChange={(v, providerId) => updateHbForm((f: any) => ({
                  ...f,
                  model: v,
                  model_provider_id: v ? (providerId ?? null) : null,
                }))}
                placeholder={`inherit (${botModel ?? "bot default"})`}
                allowClear
              />
            </Col>
          </Row>
          <FormRow label="Fallback Models" description="Ordered fallback chain for heartbeat runs.">
            <FallbackModelList
              value={hbForm.fallback_models ?? []}
              onChange={(v) => updateHbForm((f: any) => ({ ...f, fallback_models: v }))}
            />
          </FormRow>
        </Section>}

        {/* ---- Spatial Section ---- */}
        {!isWorkflowMode && (
          <Section
            title="Spatial Canvas"
            description="Canned spatial context is appended to heartbeat runs. Per-bot policy controls movement, nearby inspection, object tugging, and bot-owned spatial widgets."
          >
            <div className="flex flex-col gap-3">
              {spatialWidgetProfile && spatialWidgetProfileDefaults && (
                <div className="flex flex-col gap-3 rounded-md bg-surface-raised/35 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[13px] font-semibold text-text">{spatialWidgetProfile.title}</span>
                      <StatusBadge
                        label={spatialWidgetProfileActive ? "Applied" : "Profile"}
                        variant={spatialWidgetProfileActive ? "success" : "neutral"}
                      />
                    </div>
                    <p className="mt-1 max-w-[72ch] text-[12px] leading-relaxed text-text-dim">
                      {spatialWidgetProfile.description}
                    </p>
                  </div>
                  <ActionButton
                    label={spatialWidgetProfileActive ? "Reapply" : "Apply"}
                    size="small"
                    variant={spatialWidgetProfileActive ? "secondary" : "primary"}
                    onPress={applySpatialWidgetProfile}
                  />
                </div>
              )}
              <Toggle
                value={hbForm.append_spatial_prompt ?? false}
                onChange={(v) => updateHbForm((f: any) => ({ ...f, append_spatial_prompt: v }))}
                label="Use spatial heartbeat prompt"
                description="Adds a standard prompt that tells the bot how to use its canvas context without posting routine status updates."
              />
              <Toggle
                value={hbForm.append_spatial_map_overview ?? false}
                onChange={(v) => updateHbForm((f: any) => ({ ...f, append_spatial_map_overview: v }))}
                label="Include map overview"
                description="Injects a compact far-zoom canvas summary for bots with map-view permission."
              />
              <Toggle
                value={hbForm.include_pinned_widgets ?? false}
                onChange={(v) => updateHbForm((f: any) => ({ ...f, include_pinned_widgets: v }))}
                label="Include pinned dashboard widgets"
                description="Inject the channel's pinned dashboard widgets (notes, todos, standing orders, etc.) into the heartbeat preamble so the bot can see and act on their current state. Off by default — chat already has its own switch under Agent → Behavior."
              />
              {spatialBots.length > 0 && (
                <div className="flex flex-col gap-2">
                  {spatialBots.map((bot, index) => (
                    <SpatialPolicyCard
                      key={bot.botId}
                      channelId={channelId}
                      botId={bot.botId}
                      botName={bot.name}
                      label={bot.label}
                    />
                  ))}
                </div>
              )}
            </div>
          </Section>
        )}

        {/* ---- Action: Pipeline or Prompt ---- */}
        <Section title="Action">
          {/* Mode toggle: Prompt (default) vs Pipeline */}
          {!isHarnessRunner && <div className="mb-3">
            <SettingsSegmentedControl
              value={isWorkflowMode ? "workflow" : "prompt"}
              onChange={(mode) => {
                if (mode === "workflow" && !isWorkflowMode) {
                  const firstWf = workflows?.[0];
                  updateHbForm((f: any) => ({ ...f, workflow_id: firstWf?.id ?? "" }));
                } else if (mode === "prompt" && isWorkflowMode) {
                  updateHbForm((f: any) => ({ ...f, workflow_id: null, workflow_session_mode: null }));
                }
              }}
              options={[
                { value: "prompt", label: "Prompt", icon: <FileText size={12} /> },
                { value: "workflow", label: "Pipeline", icon: <WorkflowIcon size={12} /> },
              ]}
            />
          </div>}

          {isWorkflowMode ? (
            /* ---- Pipeline Selector ---- */
            <div className="flex flex-col gap-2">
              <FormRow label="Pipeline" description="This pipeline will be triggered on each heartbeat interval.">
                <WorkflowSelector
                  value={hbForm.workflow_id}
                  onChange={(id) => updateHbForm((f: any) => ({ ...f, workflow_id: id }))}
                />
              </FormRow>
              {hbForm.workflow_id && (() => {
                const wf = workflows?.find((w: any) => w.id === hbForm.workflow_id);
                if (!wf) return null;
                return (
                  <div style={{
                    padding: "10px 12px", borderRadius: 6,
                    fontSize: 12, lineHeight: 1.5,
                  }} className="bg-surface-raised/40 text-text-muted">
                    {wf.description && <div className="mb-1">{wf.description}</div>}
                    <div className="text-[11px] text-text-dim">
                      {wf.steps?.length ?? 0} step{(wf.steps?.length ?? 0) !== 1 ? "s" : ""}
                      {wf.tags?.length ? ` · ${wf.tags.join(", ")}` : ""}
                    </div>
                  </div>
                );
              })()}
            </div>
          ) : (
            /* ---- Prompt Editor ---- */
            <>
              <WorkspaceFilePrompt
                workspaceId={hbForm.workspace_id ?? workspaceId}
                filePath={hbForm.workspace_file_path}
                onLink={(path, wsId) => updateHbForm((f: any) => ({ ...f, workspace_file_path: path, workspace_id: wsId, prompt_template_id: null }))}
                onUnlink={() => updateHbForm((f: any) => ({ ...f, workspace_file_path: null, workspace_id: null }))}
              />
              {!hbForm.workspace_file_path && (
                <>
                    <PromptTemplateLink
                      templateId={hbForm.prompt_template_id ?? null}
                      onLink={(id) => {
                        updateHbForm((f: any) => ({ ...f, prompt_template_id: id, prompt: "" }));
                        setCustomizedFromTemplateId(null);
                        setTemplatePreviewExpanded(false);
                      }}
                      onUnlink={() => {
                        updateHbForm((f: any) => ({ ...f, prompt_template_id: null }));
                      }}
                    />

                  {/* Template linked — read-only preview with customize option */}
                  {hbForm.prompt_template_id && linkedTemplate ? (
                    <HeartbeatTemplatePreview
                      content={linkedTemplate.content}
                      description={linkedTemplate.description}
                      expanded={templatePreviewExpanded}
                      onToggleExpand={() => setTemplatePreviewExpanded((v) => !v)}
                      onCustomize={() => {
                        setCustomizedFromTemplateId(hbForm.prompt_template_id);
                        updateHbForm((f: any) => ({
                          ...f,
                          prompt: linkedTemplate.content,
                          prompt_template_id: null,
                        }));
                      }}
                    />
                  ) : (
                    <>
                      {/* "Customized" badge with reset option */}
                      {customizedFromTemplateId && (
                        <div className="mb-1 flex items-center gap-1.5">
                          <div className="flex items-center gap-1 text-[10px] font-semibold text-warning">
                            <Pencil size={10} />
                            Customized from template
                          </div>
                          <ActionButton
                            label="Reset to Template"
                            onPress={() => {
                              updateHbForm((f: any) => ({
                                ...f,
                                prompt_template_id: customizedFromTemplateId,
                                prompt: "",
                              }));
                              setCustomizedFromTemplateId(null);
                              setTemplatePreviewExpanded(false);
                            }}
                            icon={<RotateCcw size={10} />}
                            variant="ghost"
                            size="small"
                          />
                        </div>
                      )}
                      <LlmPrompt
                        value={hbForm.prompt ?? ""}
                        onChange={(v) => updateHbForm((f: any) => ({ ...f, prompt: v }))}
                        label="Heartbeat Prompt"
                        placeholder="Enter the heartbeat prompt..."
                        helpText="This prompt runs on the configured interval. Use @-tags to reference skills or tools."
                        rows={10}
                        fieldType="heartbeat"
                        channelId={channelId}
                      />
                    </>
                  )}
                </>
              )}
            </>
          )}
        </Section>

        {/* ---- Dispatch Section (only for prompt mode) ---- */}
        {!isWorkflowMode && !isHarnessRunner && (
          <Section title="Dispatch">
            <div className="flex flex-col gap-2">
              <Toggle
                value={hbForm.dispatch_results ?? true}
                onChange={(v) => updateHbForm((f: any) => ({ ...f, dispatch_results: v }))}
                label="Post heartbeat response to channel"
              />
              {hbForm.dispatch_results && (
                <Toggle
                  value={hbForm.trigger_response ?? false}
                  onChange={(v) => updateHbForm((f: any) => ({ ...f, trigger_response: v }))}
                  label="Trigger agent response after posting"
                  description="After posting the heartbeat result, the bot will process it and respond again."
                />
              )}
            </div>
          </Section>
        )}

        {/* ---- Advanced Section (only for prompt mode) ---- */}
        {!isWorkflowMode && (
          <AdvancedSection>
            <Section title="Quiet Hours">
              <QuietHoursPicker
                start={hbForm.quiet_start ?? ""}
                end={hbForm.quiet_end ?? ""}
                timezone={hbForm.timezone ?? ""}
                onChangeStart={(v) => updateHbForm((f: any) => ({ ...f, quiet_start: v }))}
                onChangeEnd={(v) => updateHbForm((f: any) => ({ ...f, quiet_end: v }))}
                onChangeTimezone={(v) => updateHbForm((f: any) => ({ ...f, timezone: v }))}
                inheritedRange={data?.default_quiet_hours}
                defaultTimezone={data?.default_timezone}
              />
            </Section>
            <Section title="Detection">
              <Toggle
                value={hbForm.repetition_detection ?? data?.default_repetition_detection ?? true}
                onChange={(v) => {
                  const globalDefault = data?.default_repetition_detection ?? true;
                  updateHbForm((f: any) => ({ ...f, repetition_detection: v === globalDefault ? null : v }));
                }}
                label="Repetition detection"
                description={`Warn when consecutive heartbeat outputs are too similar.${hbForm.repetition_detection === null ? " (using global default)" : ""}`}
              />
            </Section>
            <Section title="Tool Policies">
              <ToolMultiPicker
                tools={allTools}
                selected={hbForm.execution_config?.tools ?? []}
                onAdd={(key) => updateHbForm((f: any) => {
                  const current = f.execution_config?.tools ?? [];
                  return {
                    ...f,
                    execution_config: {
                      ...(f.execution_config ?? {}),
                      tools: current.includes(key) ? current : [...current, key],
                    },
                  };
                })}
                onRemove={(key) => updateHbForm((f: any) => ({
                  ...f,
                  execution_config: {
                    ...(f.execution_config ?? {}),
                    tools: (f.execution_config?.tools ?? []).filter((x: string) => x !== key),
                  },
                }))}
              />
              <Toggle
                value={hbForm.skip_tool_approval ?? false}
                onChange={(v) => updateHbForm((f: any) => ({ ...f, skip_tool_approval: v }))}
                label="Auto-approve tool calls"
                description="Skip tool approval policies for heartbeat runs. Tools execute without waiting for manual approval."
              />
            </Section>
            <Section title="Limits">
              <div className="flex flex-col gap-3">
                {!isHarnessRunner && <FormRow label="Max run time (seconds)">
                  <TextInput
                    value={hbForm.max_run_seconds?.toString() ?? ""}
                    onChangeText={(v) => {
                      const n = parseInt(v, 10);
                      updateHbForm((f: any) => ({ ...f, max_run_seconds: Number.isNaN(n) ? null : n }));
                    }}
                    placeholder={`${data?.default_max_run_seconds ?? 1200} (default)`}
                    type="number"
                  />
                </FormRow>}
                {!isHarnessRunner && <FormRow label="Heartbeat execution budget" description="Controls autonomous LLM-call depth and tool exposure. Max run time remains the outer timeout.">
                  <HeartbeatExecutionControls
                    policy={hbForm.execution_policy}
                    defaultPolicy={data?.default_execution_policy}
                    presets={data?.execution_policy_presets}
                    isMobile={isMobile}
                    onPresetChange={updateExecutionPreset}
                    onToolSurfaceChange={updateExecutionToolSurface}
                    onNumberChange={updateExecutionNumber}
                  />
                </FormRow>}
                <FormRow label="Previous result max chars" description="Per-heartbeat override. 0 = no truncation.">
                  <TextInput
                    value={hbForm.previous_result_max_chars?.toString() ?? ""}
                    onChangeText={(v) => {
                      const n = parseInt(v, 10);
                      updateHbForm((f: any) => ({ ...f, previous_result_max_chars: Number.isNaN(n) ? null : n }));
                    }}
                    placeholder={`${data?.default_previous_result_chars ?? 500} (global default)`}
                    type="number"
                  />
                </FormRow>
              </div>
            </Section>
            <ContextPreview form={hbForm} data={data} />
          </AdvancedSection>
        )}
      </div>

      {/* Status + History */}
      {data?.config && (
        <div className="mt-3 pt-1">
          <div className="mb-3 flex flex-wrap gap-4 text-xs text-text-dim">
            {data.config.last_run_at && (
              <span>Last run: <span className="text-text-muted">{new Date(data.config.last_run_at).toLocaleString()}</span></span>
            )}
            {data.config.next_run_at && enabled && (
              <span>Next run: <span className="text-text-muted">{new Date(data.config.next_run_at).toLocaleString()}</span></span>
            )}
          </div>

          {data.history?.length > 0 && (
            <HeartbeatHistoryList history={data.history} isWide={!isMobile} />
          )}
        </div>
      )}
    </>
  );
}
