/**
 * useTaskFormState — shared form state for task creation and editing.
 *
 * Extracts all form fields, initialization logic, save/delete handlers,
 * and derived values that were duplicated between TaskCreateModal and TaskEditor.
 */
import { useState, useCallback, useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useTask, useCreateTask, useUpdateTask, useDeleteTask, type MachineTargetGrant, type SessionTarget, type StepDef, type TaskLayout } from "@/src/api/hooks/useTasks";
import { useSkills } from "@/src/api/hooks/useSkills";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";
import { localInputToISO, isoToLocalInput } from "@/src/utils/time";
import type { TriggerConfig } from "../TriggerSection";

export interface UseTaskFormStateOptions {
  mode: "create" | "edit";
  taskId?: string;
  cloneFromId?: string;
  defaultBotId?: string;
  defaultChannelId?: string;
  extraQueryKeysToInvalidate?: string[][];
  onSaved: (createdTaskId?: string) => void;
}

export function useTaskFormState(opts: UseTaskFormStateOptions) {
  const { mode, taskId, cloneFromId, defaultBotId, defaultChannelId, extraQueryKeysToInvalidate, onSaved } = opts;
  const isCreate = mode === "create";
  const loadTaskId = taskId ?? cloneFromId;
  const qc = useQueryClient();

  // Data hooks
  const { data: existingTask, isLoading: loadingTask } = useTask(loadTaskId ?? undefined);
  const createMut = useCreateTask();
  const updateMut = useUpdateTask(taskId ?? undefined);
  const deleteMut = useDeleteTask();
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const { data: allSkills } = useSkills();
  const { data: allTools } = useTools();

  // Form state
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [promptTemplateId, setPromptTemplateId] = useState<string | null>(null);
  const [workspaceFilePath, setWorkspaceFilePath] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [botId, setBotId] = useState("");
  const [channelId, setRawChannelId] = useState("");
  const [sessionTarget, setSessionTarget] = useState<SessionTarget>({ mode: "primary" });
  const [freshProjectInstance, setFreshProjectInstance] = useState(false);
  const [status, setStatus] = useState("pending");
  const [taskType, setTaskType] = useState("scheduled");
  const [scheduledAt, setScheduledAt] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [triggerRagLoop, setTriggerRagLoop] = useState(false);
  const [modelOverride, setModelOverride] = useState("");
  const [harnessEffort, setHarnessEffort] = useState("");
  const [skipToolApproval, setSkipToolApproval] = useState(false);
  const [allowIssueReporting, setAllowIssueReporting] = useState(true);
  const [fallbackModels, setFallbackModels] = useState<Array<{ model: string; provider_id?: string | null }>>([]);
  const [maxRunSeconds, setMaxRunSeconds] = useState<string>("");
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [workflowSessionMode, setWorkflowSessionMode] = useState<string | null>(null);
  const [triggerConfig, setTriggerConfig] = useState<TriggerConfig>({ type: "schedule" });
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [selectedToolKeys, setSelectedToolKeys] = useState<string[]>([]);
  const [steps, setSteps] = useState<StepDef[] | null>(null);
  const [layout, setLayout] = useState<TaskLayout>({});
  const [postFinalToChannel, setPostFinalToChannel] = useState(false);
  const [historyMode, setHistoryMode] = useState<"none" | "recent" | "full">("none");
  const [historyRecentCount, setHistoryRecentCount] = useState(10);
  const [machineTargetGrant, setMachineTargetGrant] = useState<MachineTargetGrant | null>(null);
  const [initialized, setInitialized] = useState(false);

  const stepsMode = steps !== null;

  // Initialize from existing task (edit or clone)
  useEffect(() => {
    if (initialized || !existingTask) return;

    // Edit mode — populate from existing task
    if (!isCreate && !cloneFromId) {
      setTitle(existingTask.title || "");
      setPrompt(existingTask.prompt || "");
      setPromptTemplateId(existingTask.prompt_template_id ?? null);
      setWorkspaceFilePath(existingTask.workspace_file_path ?? null);
      setWorkspaceId(existingTask.workspace_id ?? null);
      setBotId(existingTask.bot_id || "");
      setRawChannelId(existingTask.channel_id || "");
      setSessionTarget(existingTask.session_target ?? (existingTask.execution_config?.session_target as SessionTarget | undefined) ?? { mode: "primary" });
      setFreshProjectInstance(existingTask.execution_config?.project_instance?.mode === "fresh");
      setStatus(existingTask.status || "pending");
      setTaskType(existingTask.task_type || "scheduled");
      setScheduledAt(existingTask.scheduled_at ? isoToLocalInput(existingTask.scheduled_at) : "");
      setRecurrence(existingTask.recurrence || "");
      setTriggerRagLoop(existingTask.trigger_rag_loop ?? existingTask.callback_config?.trigger_rag_loop ?? false);
      setModelOverride(existingTask.model_override ?? existingTask.execution_config?.model_override ?? existingTask.callback_config?.model_override ?? "");
      setHarnessEffort(existingTask.harness_effort ?? existingTask.execution_config?.harness_effort ?? "");
      setSkipToolApproval(!!(existingTask.skip_tool_approval ?? existingTask.execution_config?.skip_tool_approval));
      setAllowIssueReporting(!!(existingTask.allow_issue_reporting ?? existingTask.execution_config?.allow_issue_reporting));
      setFallbackModels(existingTask.fallback_models ?? existingTask.execution_config?.fallback_models ?? []);
      setMaxRunSeconds(existingTask.max_run_seconds != null ? String(existingTask.max_run_seconds) : "");
      setWorkflowId(existingTask.workflow_id ?? null);
      setWorkflowSessionMode(existingTask.workflow_session_mode ?? null);
      if (existingTask.trigger_config) {
        setTriggerConfig(existingTask.trigger_config as TriggerConfig);
      } else if (existingTask.recurrence) {
        setTriggerConfig({ type: "schedule" });
      }
      setSelectedSkillIds(existingTask.execution_config?.skills ?? []);
      setSelectedToolKeys(existingTask.execution_config?.tools ?? []);
      setSteps(existingTask.steps ?? null);
      setLayout(existingTask.layout ?? {});
      setPostFinalToChannel(!!existingTask.execution_config?.post_final_to_channel);
      setHistoryMode((existingTask.execution_config?.history_mode as any) ?? "none");
      setHistoryRecentCount(existingTask.execution_config?.history_recent_count ?? 10);
      setMachineTargetGrant(existingTask.machine_target_grant ?? null);
      setInitialized(true);
      return;
    }

    // Clone mode
    if (isCreate && cloneFromId) {
      setTitle((existingTask.title || "") + " (Clone)");
      setPrompt(existingTask.prompt || "");
      setPromptTemplateId(existingTask.prompt_template_id ?? null);
      setWorkspaceFilePath(existingTask.workspace_file_path ?? null);
      setWorkspaceId(existingTask.workspace_id ?? null);
      setBotId(existingTask.bot_id || "");
      setRawChannelId(existingTask.channel_id || "");
      setSessionTarget(existingTask.session_target ?? (existingTask.execution_config?.session_target as SessionTarget | undefined) ?? { mode: "primary" });
      setFreshProjectInstance(existingTask.execution_config?.project_instance?.mode === "fresh");
      setTaskType(existingTask.task_type || "scheduled");
      setScheduledAt("");
      setRecurrence(existingTask.recurrence || "");
      setTriggerRagLoop(existingTask.trigger_rag_loop ?? existingTask.callback_config?.trigger_rag_loop ?? false);
      setModelOverride(existingTask.model_override ?? existingTask.execution_config?.model_override ?? existingTask.callback_config?.model_override ?? "");
      setHarnessEffort(existingTask.harness_effort ?? existingTask.execution_config?.harness_effort ?? "");
      setSkipToolApproval(!!(existingTask.skip_tool_approval ?? existingTask.execution_config?.skip_tool_approval));
      setAllowIssueReporting(!!(existingTask.allow_issue_reporting ?? existingTask.execution_config?.allow_issue_reporting));
      setFallbackModels(existingTask.fallback_models ?? existingTask.execution_config?.fallback_models ?? []);
      setMaxRunSeconds(existingTask.max_run_seconds != null ? String(existingTask.max_run_seconds) : "");
      setWorkflowId(existingTask.workflow_id ?? null);
      setWorkflowSessionMode(existingTask.workflow_session_mode ?? null);
      if (existingTask.trigger_config) {
        setTriggerConfig(existingTask.trigger_config as TriggerConfig);
      }
      setSelectedSkillIds(existingTask.execution_config?.skills ?? []);
      setSelectedToolKeys(existingTask.execution_config?.tools ?? []);
      setSteps(existingTask.steps ?? null);
      setLayout(existingTask.layout ?? {});
      setPostFinalToChannel(!!existingTask.execution_config?.post_final_to_channel);
      setHistoryMode((existingTask.execution_config?.history_mode as any) ?? "none");
      setHistoryRecentCount(existingTask.execution_config?.history_recent_count ?? 10);
      setMachineTargetGrant(existingTask.machine_target_grant ?? null);
      setInitialized(true);
    }
  }, [existingTask, initialized, isCreate, cloneFromId]);

  // Set defaults for fresh create (no clone)
  useEffect(() => {
    if (initialized || !isCreate || cloneFromId) return;
    if (!bots || bots.length === 0) return;
    setBotId(defaultBotId || bots[0].id);
    setRawChannelId(defaultChannelId || "");
    setSessionTarget({ mode: "primary" });
    setInitialized(true);
  }, [initialized, isCreate, cloneFromId, bots, defaultBotId, defaultChannelId]);

  const setChannelId = useCallback((nextChannelId: string) => {
    setRawChannelId(nextChannelId);
    setSessionTarget({ mode: "primary" });
  }, []);

  // Derived
  const saving = createMut.isPending || updateMut.isPending;
  const hasPromptOrWorkflow = !!prompt.trim() || !!promptTemplateId || !!workspaceFilePath || !!workflowId || (steps !== null && steps.length > 0);
  const canSave = hasPromptOrWorkflow && !!botId;
  const error = createMut.error || updateMut.error || deleteMut.error;

  const invalidateExtra = useCallback(() => {
    if (extraQueryKeysToInvalidate) {
      for (const key of extraQueryKeysToInvalidate) {
        qc.invalidateQueries({ queryKey: key });
      }
    }
  }, [qc, extraQueryKeysToInvalidate]);

  const handleSave = useCallback(async () => {
    if (!hasPromptOrWorkflow || !botId) return;
    try {
      const scheduledAtISO = triggerConfig.type === "schedule" ? (localInputToISO(scheduledAt) || null) : null;
      const effectiveRecurrence = triggerConfig.type === "schedule" ? (recurrence || null) : null;
      const effectiveTaskType = steps && steps.length > 0 ? "pipeline" : taskType;
      const effectiveSteps = steps && steps.length > 0 ? steps : null;
      const effectiveLayout: TaskLayout | null = stepsMode ? layout : null;
      const skillsPayload = selectedSkillIds.length > 0 ? selectedSkillIds : null;
      const toolsPayload = selectedToolKeys.length > 0 ? selectedToolKeys : null;
      const channelOutputPayload = {
        post_final_to_channel: postFinalToChannel,
        history_mode: historyMode,
        history_recent_count: historyMode === "recent" ? historyRecentCount : null,
      };
      const machineTargetGrantPayload = machineTargetGrant
        ? {
            provider_id: machineTargetGrant.provider_id,
            target_id: machineTargetGrant.target_id,
            capabilities: machineTargetGrant.capabilities?.length ? machineTargetGrant.capabilities : ["inspect", "exec"],
            allow_agent_tools: machineTargetGrant.allow_agent_tools ?? true,
            expires_at: machineTargetGrant.expires_at ?? null,
          }
        : null;

      if (isCreate) {
        const created = await createMut.mutateAsync({
          prompt: prompt || undefined,
          title: title || null,
          prompt_template_id: promptTemplateId,
          workspace_file_path: workspaceFilePath,
          workspace_id: workspaceId,
          bot_id: botId,
          channel_id: channelId || null,
          session_target: channelId ? sessionTarget : null,
          project_instance: freshProjectInstance ? { mode: "fresh" } : { mode: "shared" },
          scheduled_at: scheduledAtISO,
          recurrence: effectiveRecurrence,
          task_type: effectiveTaskType,
          trigger_rag_loop: triggerRagLoop,
          model_override: modelOverride || null,
          harness_effort: harnessEffort || null,
          skip_tool_approval: skipToolApproval,
          allow_issue_reporting: allowIssueReporting,
          fallback_models: fallbackModels.length > 0 ? fallbackModels : null,
          max_run_seconds: maxRunSeconds ? parseInt(maxRunSeconds) : null,
          workflow_id: workflowId || null,
          workflow_session_mode: workflowSessionMode || null,
          trigger_config: triggerConfig,
          skills: skillsPayload,
          tools: toolsPayload,
          steps: effectiveSteps,
          layout: effectiveLayout,
          machine_target_grant: machineTargetGrantPayload,
          ...channelOutputPayload,
        });
        invalidateExtra();
        onSaved(created.id);
        return;
      } else {
        await updateMut.mutateAsync({
          prompt,
          title: title || null,
          prompt_template_id: promptTemplateId,
          workspace_file_path: workspaceFilePath,
          workspace_id: workspaceId,
          bot_id: botId,
          channel_id: channelId || null,
          session_target: channelId ? sessionTarget : null,
          project_instance: freshProjectInstance ? { mode: "fresh" } : { mode: "shared" },
          status,
          scheduled_at: scheduledAtISO,
          recurrence: effectiveRecurrence,
          task_type: effectiveTaskType,
          trigger_rag_loop: triggerRagLoop,
          model_override: modelOverride || null,
          harness_effort: harnessEffort || null,
          skip_tool_approval: skipToolApproval,
          allow_issue_reporting: allowIssueReporting,
          fallback_models: fallbackModels.length > 0 ? fallbackModels : null,
          max_run_seconds: maxRunSeconds ? parseInt(maxRunSeconds) : null,
          workflow_id: workflowId || null,
          workflow_session_mode: workflowSessionMode || null,
          trigger_config: triggerConfig,
          skills: skillsPayload,
          tools: toolsPayload,
          steps: effectiveSteps,
          layout: effectiveLayout,
          machine_target_grant: machineTargetGrantPayload,
          ...channelOutputPayload,
        });
      }
      invalidateExtra();
      onSaved();
    } catch {
      // error shown via mutation state
    }
  }, [prompt, title, botId, channelId, sessionTarget, freshProjectInstance, scheduledAt, recurrence, taskType, triggerRagLoop, modelOverride, harnessEffort, skipToolApproval, allowIssueReporting, fallbackModels, maxRunSeconds, status, isCreate, createMut, updateMut, onSaved, invalidateExtra, promptTemplateId, workspaceFilePath, workspaceId, workflowId, workflowSessionMode, hasPromptOrWorkflow, triggerConfig, selectedSkillIds, selectedToolKeys, steps, layout, stepsMode, postFinalToChannel, historyMode, historyRecentCount, machineTargetGrant]);

  const handleDelete = useCallback(async () => {
    if (!taskId) return;
    await deleteMut.mutateAsync(taskId);
    invalidateExtra();
    onSaved();
  }, [taskId, deleteMut, onSaved, invalidateExtra]);

  // Options for dropdowns
  const selectedBot = bots?.find((b) => b.id === botId);
  const botOptions = useMemo(() => (bots || []).map((b) => ({ label: b.name || b.id, value: b.id })), [bots]);
  const channelOptions = useMemo(() => [
    { label: "\u2014 None \u2014", value: "" },
    ...(channels || []).map((c: any) => ({
      label: c.display_name || c.name || c.id,
      value: String(c.id),
    })),
  ], [channels]);
  const skillOptions = useMemo(() => (allSkills || []).map((s) => ({ key: s.id, label: s.name, tag: s.category ?? undefined })), [allSkills]);
  const toolOptions = useMemo(() => (allTools || []).map((t) => ({ key: t.tool_key, label: t.tool_name, tag: t.source_integration ?? undefined })), [allTools]);

  return {
    // Mode
    isCreate,
    loadingTask,
    existingTask,
    saving,
    error,
    canSave,
    hasPromptOrWorkflow,
    stepsMode,

    // Form fields + setters
    title, setTitle,
    prompt, setPrompt,
    promptTemplateId, setPromptTemplateId,
    workspaceFilePath, setWorkspaceFilePath,
    workspaceId, setWorkspaceId,
    botId, setBotId,
    channelId, setChannelId,
    sessionTarget, setSessionTarget,
    freshProjectInstance, setFreshProjectInstance,
    status, setStatus,
    taskType, setTaskType,
    scheduledAt, setScheduledAt,
    recurrence, setRecurrence,
    triggerRagLoop, setTriggerRagLoop,
    modelOverride, setModelOverride,
    harnessEffort, setHarnessEffort,
    skipToolApproval, setSkipToolApproval,
    allowIssueReporting, setAllowIssueReporting,
    fallbackModels, setFallbackModels,
    maxRunSeconds, setMaxRunSeconds,
    workflowId, setWorkflowId,
    workflowSessionMode, setWorkflowSessionMode,
    triggerConfig, setTriggerConfig,
    selectedSkillIds, setSelectedSkillIds,
    selectedToolKeys, setSelectedToolKeys,
    steps, setSteps,
    layout, setLayout,
    postFinalToChannel, setPostFinalToChannel,
    historyMode, setHistoryMode,
    historyRecentCount, setHistoryRecentCount,
    machineTargetGrant, setMachineTargetGrant,

    // Actions
    handleSave,
    handleDelete,

    // Data
    selectedBot,
    bots,
    channels,
    deleteMut,

    // Dropdown options
    botOptions,
    channelOptions,
    skillOptions,
    toolOptions,
    allTools: allTools ?? [],
  };
}

export type TaskFormState = ReturnType<typeof useTaskFormState>;
