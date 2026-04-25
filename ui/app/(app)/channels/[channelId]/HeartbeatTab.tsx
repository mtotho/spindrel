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
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";
import { useChannels } from "@/src/api/hooks/useChannels";
import { apiFetch } from "@/src/api/client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { WorkflowSelector } from "@/src/components/shared/WorkflowSelector";
import { useWorkflows } from "@/src/api/hooks/useWorkflows";

import { QuietHoursPicker } from "./QuietHoursPicker";
import { HeartbeatHistoryList } from "./HeartbeatHistoryList";
import { ContextPreview, HeartbeatTemplatePreview } from "./HeartbeatContextPreview";
import { SpatialPolicyCard } from "./SpatialBotPolicyControls";

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

const EXECUTION_DEPTH_OPTIONS = [
  { label: "Low", value: "low" },
  { label: "Medium", value: "medium" },
  { label: "High", value: "high" },
  { label: "Custom", value: "custom" },
];

function normalizeExecutionPolicy(raw: any, defaultPolicy?: any, presets?: Record<string, any>) {
  const fallback = defaultPolicy ?? { preset: "medium" };
  const preset = typeof raw?.preset === "string" ? raw.preset : fallback.preset ?? "medium";
  const base = presets?.[preset] ?? presets?.[fallback.preset] ?? fallback;
  return {
    preset: presets?.[preset] || preset === "custom" ? preset : fallback.preset ?? "medium",
    tool_surface: raw?.tool_surface ?? fallback.tool_surface ?? "focused_escape",
    continuation_mode: raw?.continuation_mode ?? fallback.continuation_mode ?? "stateless",
    soft_max_llm_calls: raw?.soft_max_llm_calls ?? base.soft_max_llm_calls,
    hard_max_llm_calls: raw?.hard_max_llm_calls ?? base.hard_max_llm_calls,
    soft_current_prompt_tokens: raw?.soft_current_prompt_tokens ?? base.soft_current_prompt_tokens,
    target_seconds: raw?.target_seconds ?? base.target_seconds,
  };
}

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

function RunNowButton({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
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
        description="Heartbeat schedules background runs for this channel. Configuration saves automatically."
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

export function HeartbeatTab({
  channelId,
  workspaceId,
  botModel,
  onSaveStateChange,
}: {
  channelId: string;
  workspaceId?: string | null;
  botModel?: string;
  onSaveStateChange?: (state: HeartbeatSaveState) => void;
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
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch templates to render linked template content
  const { data: allTemplates } = usePromptTemplates();
  const linkedTemplate = allTemplates?.find((tpl) => tpl.id === hbForm?.prompt_template_id);

  // Fetch workflows for the workflow selector
  const { data: workflows } = useWorkflows();

  useEffect(() => {
    setHbForm(null);
    hbFormRef.current = null;
    setInitialHeartbeatApplied(false);
  }, [channelId]);

  useEffect(() => {
    if (!data || isFetching) return;
    if (data?.config) {
      const nextForm = {
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
        execution_policy: normalizeExecutionPolicy(
          data.config.execution_policy,
          data.default_execution_policy,
          data.execution_policy_presets,
        ),
      };
      setHbForm(nextForm);
      hbFormRef.current = nextForm;
      setInitialHeartbeatApplied(true);
      hbDirtyRef.current = false;
      setHbDirty(false);
    } else if (data && !data.config) {
      const nextForm = {
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
        execution_policy: normalizeExecutionPolicy(
          null,
          data.default_execution_policy,
          data.execution_policy_presets,
        ),
      };
      setHbForm(nextForm);
      hbFormRef.current = nextForm;
      setInitialHeartbeatApplied(true);
      hbDirtyRef.current = false;
      setHbDirty(false);
    }
  }, [data, isFetching]);

  const toggleMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat/toggle`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      setHbLastSavedAt(Date.now());
    },
  });

  const saveMutation = useMutation({
    mutationFn: (body: any) => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      queryClient.invalidateQueries({ queryKey: ["channel-spatial-bot-policy", channelId] });
      hbDirtyRef.current = false;
      setHbDirty(false);
      setHbLastSavedAt(Date.now());
    },
  });

  const saveMutationRef = useRef(saveMutation);
  saveMutationRef.current = saveMutation;

  const scheduleSave = useCallback(() => {
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(async () => {
      saveTimeoutRef.current = null;
      if (!hbFormRef.current) return;
      try {
        await saveMutationRef.current.mutateAsync(hbFormRef.current);
      } catch {
        // Error state is surfaced via saveMutation.isError / header pill.
      }
    }, 800);
  }, []);

  const updateHbForm = useCallback((updater: (prev: any) => any) => {
    let nextForm: any = null;
    setHbForm((prev: any) => {
      nextForm = updater(prev);
      return nextForm;
    });
    if (!nextForm) return;
    hbFormRef.current = nextForm;
    hbDirtyRef.current = true;
    setHbDirty(true);
    setHbLastSavedAt(null);
    saveMutationRef.current.reset();
    scheduleSave();
  }, [scheduleSave]);

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

  useEffect(() => {
    onSaveStateChange?.({
      dirty: hbDirty,
      isPending: saveMutation.isPending || toggleMutation.isPending,
      isError: saveMutation.isError || toggleMutation.isError,
      lastSavedAt: hbLastSavedAt,
    });
  }, [
    hbDirty,
    hbLastSavedAt,
    onSaveStateChange,
    saveMutation.isError,
    saveMutation.isPending,
    toggleMutation.isError,
    toggleMutation.isPending,
  ]);

  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
        saveTimeoutRef.current = null;
        if (hbDirtyRef.current && hbFormRef.current) {
          saveMutationRef.current.mutate(hbFormRef.current);
        }
      }
    };
  }, []);

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

  const enabled = data?.config?.enabled ?? false;
  const isWorkflowMode = !!hbForm.workflow_id;
  const hasAction = isWorkflowMode
    ? !!hbForm.workflow_id
    : !!(hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path || hbForm.append_spatial_prompt);
  const runNowLabel = hbFirePollStartedAt ? "Running..." : hbFired ? "Fired" : fireMutation.isPending ? "Firing..." : "Run Now";

  return (
    <>
      <Section
        title={
          <div className="flex flex-wrap items-center gap-2">
            <span>Heartbeat</span>
            <StatusBadge label={enabled ? "Enabled" : "Disabled"} variant={enabled ? "success" : "neutral"} />
          </div>
        }
        description={enabled
          ? "Heartbeat schedules background runs for this channel. Configuration saves automatically."
          : "Heartbeat is disabled. You can still configure it here, then enable it when the schedule is ready."}
        action={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <RunNowButton
              label={runNowLabel}
              onClick={() => fireMutation.mutate()}
              disabled={!hasAction || fireMutation.isPending || !!hbFirePollStartedAt}
            />
            <ActionButton
              label={toggleMutation.isPending ? "Updating..." : enabled ? "Disable" : "Enable"}
              onPress={() => toggleMutation.mutate()}
              variant="secondary"
              size="small"
              disabled={toggleMutation.isPending}
            />
          </div>
        }
      >
        {null}
      </Section>

      <div className="flex flex-col gap-5">
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

        {/* ---- Model Section ---- */}
        <Section title="Model">
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
        </Section>

        {/* ---- Spatial Section ---- */}
        {!isWorkflowMode && (
          <Section
            title="Spatial Canvas"
            description="Canned spatial context is appended to heartbeat runs. Per-bot policy controls movement, nearby inspection, object tugging, and bot-owned spatial widgets."
          >
            <div className="flex flex-col gap-3">
              <Toggle
                value={hbForm.append_spatial_prompt ?? false}
                onChange={(v) => updateHbForm((f: any) => ({ ...f, append_spatial_prompt: v }))}
                label="Use spatial heartbeat prompt"
                description="Adds a standard prompt that tells the bot how to use its canvas context without posting routine status updates."
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

        {/* ---- Action: Workflow or Prompt ---- */}
        <Section title="Action">
          {/* Mode toggle: Prompt (default) vs Workflow */}
          <div className="mb-3">
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
                { value: "workflow", label: "Workflow", icon: <WorkflowIcon size={12} /> },
              ]}
            />
          </div>

          {isWorkflowMode ? (
            /* ---- Workflow Selector ---- */
            <div className="flex flex-col gap-2">
              <FormRow label="Workflow" description="This workflow will be triggered on each heartbeat interval.">
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
              {hbForm.workflow_id && (
                <FormRow label="Session Mode" description="Override the workflow's session mode for heartbeat triggers.">
                  <SelectInput
                    value={hbForm.workflow_session_mode ?? ""}
                    onChange={(v) => updateHbForm((f: any) => ({ ...f, workflow_session_mode: v || null }))}
                    options={[
                      { label: "Use workflow default", value: "" },
                      { label: "Isolated (no chat messages)", value: "isolated" },
                      { label: "Shared (visible in chat)", value: "shared" },
                    ]}
                  />
                </FormRow>
              )}
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
        {!isWorkflowMode && (
          <Section title="Dispatch">
            <div className="flex flex-col gap-2">
              <Toggle
                value={hbForm.dispatch_results ?? true}
                onChange={(v) => updateHbForm((f: any) => ({ ...f, dispatch_results: v }))}
                label="Post results to channel"
              />
              {hbForm.dispatch_results && (
                <FormRow label="Dispatch mode" description="How heartbeat results are posted.">
                  <SelectInput
                    value={hbForm.dispatch_mode ?? "always"}
                    onChange={(v) => updateHbForm((f: any) => ({ ...f, dispatch_mode: v }))}
                    options={[
                      { label: "Always post", value: "always" },
                      { label: "LLM decides (via tool)", value: "optional" },
                    ]}
                  />
                </FormRow>
              )}
              <Toggle
                value={hbForm.trigger_response ?? false}
                onChange={(v) => updateHbForm((f: any) => ({ ...f, trigger_response: v }))}
                label="Trigger agent response after posting"
                description="After posting the heartbeat result, the bot will process it and respond again."
              />
            </div>
          </Section>
        )}

        {/* Run controls */}
        <div className="mt-1 flex flex-wrap gap-2">
          <RunNowButton
            label={runNowLabel}
            onClick={() => fireMutation.mutate()}
            disabled={!hasAction || fireMutation.isPending || !!hbFirePollStartedAt}
          />
          {!hasAction && (
            <span className="self-center text-[11px] text-text-dim">
              Add a prompt or workflow before running heartbeat manually.
            </span>
          )}
        </div>

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
              <Toggle
                value={hbForm.skip_tool_approval ?? false}
                onChange={(v) => updateHbForm((f: any) => ({ ...f, skip_tool_approval: v }))}
                label="Auto-approve tool calls"
                description="Skip tool approval policies for heartbeat runs. Tools execute without waiting for manual approval."
              />
            </Section>
            <Section title="Limits">
              <div className="flex flex-col gap-3">
                <FormRow label="Max run time (seconds)">
                  <TextInput
                    value={hbForm.max_run_seconds?.toString() ?? ""}
                    onChangeText={(v) => {
                      const n = parseInt(v, 10);
                      updateHbForm((f: any) => ({ ...f, max_run_seconds: Number.isNaN(n) ? null : n }));
                    }}
                    placeholder={`${data?.default_max_run_seconds ?? 1200} (default)`}
                    type="number"
                  />
                </FormRow>
                <FormRow label="Execution depth" description="Controls the heartbeat's LLM-call budget. Max run time remains the outer timeout.">
                  <SelectInput
                    value={normalizeExecutionPolicy(hbForm.execution_policy, data?.default_execution_policy, data?.execution_policy_presets).preset}
                    onChange={updateExecutionPreset}
                    options={EXECUTION_DEPTH_OPTIONS}
                  />
                </FormRow>
                <Row stack={isMobile}>
                  <Col minWidth={isMobile ? 0 : 150}>
                    <FormRow label="Soft LLM calls">
                      <TextInput
                        value={normalizeExecutionPolicy(hbForm.execution_policy, data?.default_execution_policy, data?.execution_policy_presets).soft_max_llm_calls?.toString() ?? ""}
                        onChangeText={(v) => updateExecutionNumber("soft_max_llm_calls", v)}
                        type="number"
                        min={1}
                      />
                    </FormRow>
                  </Col>
                  <Col minWidth={isMobile ? 0 : 150}>
                    <FormRow label="Hard LLM calls">
                      <TextInput
                        value={normalizeExecutionPolicy(hbForm.execution_policy, data?.default_execution_policy, data?.execution_policy_presets).hard_max_llm_calls?.toString() ?? ""}
                        onChangeText={(v) => updateExecutionNumber("hard_max_llm_calls", v)}
                        type="number"
                        min={1}
                      />
                    </FormRow>
                  </Col>
                </Row>
                <Row stack={isMobile}>
                  <Col minWidth={isMobile ? 0 : 190}>
                    <FormRow label="Soft current tokens">
                      <TextInput
                        value={normalizeExecutionPolicy(hbForm.execution_policy, data?.default_execution_policy, data?.execution_policy_presets).soft_current_prompt_tokens?.toString() ?? ""}
                        onChangeText={(v) => updateExecutionNumber("soft_current_prompt_tokens", v)}
                        type="number"
                        min={0}
                      />
                    </FormRow>
                  </Col>
                  <Col minWidth={isMobile ? 0 : 150}>
                    <FormRow label="Target seconds">
                      <TextInput
                        value={normalizeExecutionPolicy(hbForm.execution_policy, data?.default_execution_policy, data?.execution_policy_presets).target_seconds?.toString() ?? ""}
                        onChangeText={(v) => updateExecutionNumber("target_seconds", v)}
                        type="number"
                        min={1}
                      />
                    </FormRow>
                  </Col>
                </Row>
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
