import { useState, useCallback } from "react";
import ReactDOM from "react-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, Trash2, Copy, FileText } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useTask, useCreateTask, useUpdateTask, useDeleteTask, type StepDef } from "@/src/api/hooks/useTasks";
import { useWorkflows } from "@/src/api/hooks/useWorkflows";
import { useSkills } from "@/src/api/hooks/useSkills";
import { useTools } from "@/src/api/hooks/useTools";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { PromptTemplateLink } from "@/src/components/shared/PromptTemplateLink";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { FormRow, TextInput, SelectInput, Toggle, Section } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { formatDateTime, isoToLocalInput, localInputToISO } from "@/src/utils/time";
import {
  EnableToggle,
  InfoRow,
  STATUS_OPTIONS,
  TASK_TYPE_OPTIONS_CREATE,
} from "./SchedulingPickers";
import { TriggerSection, type TriggerConfig } from "./TriggerSection";
import { TaskStepEditor } from "./TaskStepEditor";
import { ChipPicker } from "./TaskCreateModal";


// ---------------------------------------------------------------------------
// TaskEditor (near-fullscreen overlay)
// ---------------------------------------------------------------------------
export interface TaskEditorProps {
  taskId: string | null;        // null = create mode
  onClose: () => void;
  onSaved: () => void;
  defaultChannelId?: string;    // pre-select channel in create mode
  defaultBotId?: string;        // pre-select bot in create mode
  onClone?: (taskId: string) => void;  // callback when clone is clicked
  cloneFromId?: string;         // load this task's data for cloning
  extraQueryKeysToInvalidate?: string[][]; // additional query keys to invalidate on save/delete
}

export function TaskEditor({
  taskId,
  onClose,
  onSaved,
  defaultChannelId,
  defaultBotId,
  onClone,
  cloneFromId,
  extraQueryKeysToInvalidate,
}: TaskEditorProps) {
  const isCreate = !taskId;
  const loadTaskId = taskId ?? cloneFromId;
  const { data: existingTask, isLoading: loadingTask } = useTask(loadTaskId ?? undefined);
  const createMut = useCreateTask();
  const updateMut = useUpdateTask(taskId ?? undefined);
  const deleteMut = useDeleteTask();
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const { data: allSkills } = useSkills();
  const { data: allTools } = useTools();
  const isWide = typeof window !== "undefined" && window.innerWidth >= 768;
  const qc = useQueryClient();

  // Form state
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [promptTemplateId, setPromptTemplateId] = useState<string | null>(null);
  const [workspaceFilePath, setWorkspaceFilePath] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [botId, setBotId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [status, setStatus] = useState("pending");
  const [taskType, setTaskType] = useState("scheduled");
  const [scheduledAt, setScheduledAt] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [triggerRagLoop, setTriggerRagLoop] = useState(false);
  const [modelOverride, setModelOverride] = useState("");
  const [fallbackModels, setFallbackModels] = useState<Array<{ model: string; provider_id?: string | null }>>([]);
  const [maxRunSeconds, setMaxRunSeconds] = useState<string>("");
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [workflowSessionMode, setWorkflowSessionMode] = useState<string | null>(null);
  const [triggerConfig, setTriggerConfig] = useState<TriggerConfig>({ type: "schedule" });
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [selectedToolKeys, setSelectedToolKeys] = useState<string[]>([]);
  const [steps, setSteps] = useState<StepDef[] | null>(null);
  const stepsMode = steps !== null;
  const [initialized, setInitialized] = useState(false);
  const { data: workflows } = useWorkflows();

  // Populate form when existing task loads (edit mode)
  if (!isCreate && !cloneFromId && existingTask && !initialized) {
    setTitle(existingTask.title || "");
    setPrompt(existingTask.prompt || "");
    setPromptTemplateId(existingTask.prompt_template_id ?? null);
    setWorkspaceFilePath(existingTask.workspace_file_path ?? null);
    setWorkspaceId(existingTask.workspace_id ?? null);
    setBotId(existingTask.bot_id || "");
    setChannelId(existingTask.channel_id || "");
    setStatus(existingTask.status || "pending");
    setTaskType(existingTask.task_type || "scheduled");
    setScheduledAt(existingTask.scheduled_at ? isoToLocalInput(existingTask.scheduled_at) : "");
    setRecurrence(existingTask.recurrence || "");
    setTriggerRagLoop(existingTask.trigger_rag_loop ?? existingTask.callback_config?.trigger_rag_loop ?? false);
    setModelOverride(existingTask.model_override ?? existingTask.execution_config?.model_override ?? existingTask.callback_config?.model_override ?? "");
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
    setInitialized(true);
  }

  // Populate form when cloning
  if (isCreate && cloneFromId && existingTask && !initialized) {
    setTitle(existingTask.title || "");
    setPrompt(existingTask.prompt || "");
    setPromptTemplateId(existingTask.prompt_template_id ?? null);
    setWorkspaceFilePath(existingTask.workspace_file_path ?? null);
    setWorkspaceId(existingTask.workspace_id ?? null);
    setBotId(existingTask.bot_id || "");
    setChannelId(existingTask.channel_id || "");
    setTaskType(existingTask.task_type || "scheduled");
    setScheduledAt(existingTask.scheduled_at ? isoToLocalInput(existingTask.scheduled_at) : "");
    setRecurrence(existingTask.recurrence || "");
    setTriggerRagLoop(existingTask.trigger_rag_loop ?? existingTask.callback_config?.trigger_rag_loop ?? false);
    setModelOverride(existingTask.model_override ?? existingTask.execution_config?.model_override ?? existingTask.callback_config?.model_override ?? "");
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
    setInitialized(true);
  }

  // Set defaults for create mode (no clone)
  if (isCreate && !cloneFromId && !initialized && bots && bots.length > 0) {
    setBotId(defaultBotId || bots[0].id);
    setChannelId(defaultChannelId || "");
    setInitialized(true);
  }

  const saving = createMut.isPending || updateMut.isPending;

  const invalidateExtra = useCallback(() => {
    if (extraQueryKeysToInvalidate) {
      for (const key of extraQueryKeysToInvalidate) {
        qc.invalidateQueries({ queryKey: key });
      }
    }
  }, [qc, extraQueryKeysToInvalidate]);

  const hasPromptOrWorkflow = !!prompt.trim() || !!promptTemplateId || !!workspaceFilePath || !!workflowId || (steps !== null && steps.length > 0);

  const handleSave = useCallback(async () => {
    if (!hasPromptOrWorkflow || !botId) return;
    try {
      const scheduledAtISO = localInputToISO(scheduledAt) || null;
      const effectiveTaskType = steps && steps.length > 0 ? "pipeline" : taskType;
      const effectiveSteps = steps && steps.length > 0 ? steps : null;
      if (isCreate) {
        await createMut.mutateAsync({
          prompt: prompt || undefined,
          title: title || null,
          prompt_template_id: promptTemplateId,
          workspace_file_path: workspaceFilePath,
          workspace_id: workspaceId,
          bot_id: botId,
          channel_id: channelId || null,
          scheduled_at: scheduledAtISO,
          recurrence: recurrence || null,
          task_type: effectiveTaskType,
          trigger_rag_loop: triggerRagLoop,
          model_override: modelOverride || null,
          fallback_models: fallbackModels.length > 0 ? fallbackModels : null,
          max_run_seconds: maxRunSeconds ? parseInt(maxRunSeconds) : null,
          workflow_id: workflowId || null,
          workflow_session_mode: workflowSessionMode || null,
          skills: selectedSkillIds.length > 0 ? selectedSkillIds : null,
          tools: selectedToolKeys.length > 0 ? selectedToolKeys : null,
          steps: effectiveSteps,
        });
      } else {
        await updateMut.mutateAsync({
          prompt,
          title: title || null,
          prompt_template_id: promptTemplateId,
          workspace_file_path: workspaceFilePath,
          workspace_id: workspaceId,
          bot_id: botId,
          status,
          scheduled_at: scheduledAtISO,
          recurrence: recurrence || null,
          task_type: effectiveTaskType,
          trigger_rag_loop: triggerRagLoop,
          model_override: modelOverride || null,
          fallback_models: fallbackModels.length > 0 ? fallbackModels : null,
          max_run_seconds: maxRunSeconds ? parseInt(maxRunSeconds) : null,
          workflow_id: workflowId || null,
          workflow_session_mode: workflowSessionMode || null,
          trigger_config: triggerConfig,
          skills: selectedSkillIds.length > 0 ? selectedSkillIds : null,
          tools: selectedToolKeys.length > 0 ? selectedToolKeys : null,
          steps: effectiveSteps,
        });
      }
      invalidateExtra();
      onSaved();
    } catch {
      // error is shown via mutation state
    }
  }, [prompt, title, botId, channelId, scheduledAt, recurrence, taskType, triggerRagLoop, modelOverride, fallbackModels, maxRunSeconds, status, isCreate, createMut, updateMut, onSaved, invalidateExtra, promptTemplateId, workspaceFilePath, workspaceId, workflowId, workflowSessionMode, hasPromptOrWorkflow]);

  const handleDelete = useCallback(async () => {
    if (!taskId || !confirm("Delete this task?")) return;
    await deleteMut.mutateAsync(taskId);
    invalidateExtra();
    onSaved();
  }, [taskId, deleteMut, onSaved, invalidateExtra]);

  const navigate = useNavigate();

  if (typeof document === "undefined") return null;
  const selectedBot = bots?.find((b) => b.id === botId);
  const botOptions = (bots || []).map((b) => ({ label: b.name || b.id, value: b.id }));
  const channelOptions = [
    { label: "\u2014 None \u2014", value: "" },
    ...(channels || []).map((c: any) => ({
      label: c.display_name || c.name || c.id,
      value: String(c.id),
    })),
  ];

  const skillOptions = (allSkills || []).map((s) => ({ key: s.id, label: s.name, tag: s.category ?? undefined }));
  const toolOptions = (allTools || []).map((tl) => ({ key: tl.tool_key, label: tl.tool_name, tag: tl.source_integration ?? undefined }));

  const editorTitle = cloneFromId ? "New Task (Clone)" : isCreate ? "New Task" : "Edit Task";

  return ReactDOM.createPortal(
    <div className="flex fixed inset-0 z-[10000] bg-surface">
      {/* Header */}
      <div className={`flex flex-row items-center border-b border-surface-border shrink-0 gap-2 ${isWide ? "px-5 py-3" : "px-3 py-2.5"}`}>
        <button
          onClick={onClose}
          className="bg-transparent border-none cursor-pointer p-1 shrink-0 rounded-md hover:bg-surface-overlay"
        >
          <ChevronLeft size={22} className="text-text-muted" />
        </button>

        <span className="text-text text-sm font-bold shrink-0">
          {editorTitle}
        </span>
        {cloneFromId && (
          <span className="text-[10px] px-2 py-0.5 rounded font-semibold bg-warning/[0.08] text-warning-muted">
            CLONE
          </span>
        )}
        {!isCreate && existingTask && isWide && (
          <span className="text-text-dim text-[11px] font-mono">
            {taskId?.slice(0, 8)}
          </span>
        )}

        <div className="flex-1" />

        {/* View Logs button (edit mode, when correlation_id available) */}
        {!isCreate && existingTask?.correlation_id && (
          <button
            onClick={() => {
              onClose();
              navigate(`/admin/logs/${existingTask.correlation_id}`);
            }}
            title="View Logs"
            className={`flex flex-row items-center ${isWide ? "gap-1.5 px-3.5" : "px-2"} py-1.5 text-[13px] border border-accent-muted rounded-md bg-transparent text-accent cursor-pointer shrink-0 hover:bg-accent/[0.06] transition-colors`}
          >
            <FileText size={14} />
            {isWide && "Logs"}
          </button>
        )}

        {/* Clone button (edit mode only) */}
        {!isCreate && onClone && taskId && (
          <button
            onClick={() => onClone(taskId)}
            title="Clone"
            className={`flex flex-row items-center ${isWide ? "gap-1.5 px-3.5" : "px-2"} py-1.5 text-[13px] border border-surface-border rounded-md bg-transparent text-text-muted cursor-pointer shrink-0 hover:border-accent/50 hover:text-text transition-colors`}
          >
            <Copy size={14} />
            {isWide && "Clone"}
          </button>
        )}

        {!isCreate && (
          <button
            onClick={handleDelete}
            disabled={deleteMut.isPending}
            title="Delete"
            className={`flex flex-row items-center ${isWide ? "gap-1.5 px-3.5" : "px-2"} py-1.5 text-[13px] border border-danger/[0.15] rounded-md bg-transparent text-danger cursor-pointer shrink-0 hover:bg-danger/[0.06] transition-colors`}
          >
            <Trash2 size={14} />
            {isWide && "Delete"}
          </button>
        )}
        {!isCreate && (
          <EnableToggle
            enabled={status !== "cancelled"}
            onChange={(on) => {
              // For schedules (has recurrence), toggle between active and cancelled
              const isSchedule = !!recurrence;
              setStatus(on ? (isSchedule ? "active" : "pending") : "cancelled");
            }}
            compact={!isWide}
          />
        )}
        <button
          onClick={handleSave}
          disabled={saving || !hasPromptOrWorkflow || !botId}
          className={`${isWide ? "px-5" : "px-3"} py-1.5 text-[13px] font-semibold border-none rounded-md shrink-0 transition-colors ${
            hasPromptOrWorkflow && botId
              ? "bg-accent text-white cursor-pointer hover:bg-accent-hover"
              : "bg-surface-border text-text-dim cursor-not-allowed"
          }`}
        >
          {saving ? "..." : isCreate ? "Create" : "Save"}
        </button>
      </div>

      {/* Error display */}
      {(createMut.error || updateMut.error || deleteMut.error) && (
        <div className="px-5 py-2 bg-danger/[0.08] text-danger text-xs">
          {(createMut.error || updateMut.error || deleteMut.error)?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      {(((!isCreate && !cloneFromId) || cloneFromId) && loadingTask) ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="chat-spinner" />
        </div>
      ) : (
        <div className={`flex flex-1 min-h-0 overflow-y-auto ${isWide ? "flex-row" : ""}`}>
          {/* Prompt + Result/Error */}
          <div className={isWide ? "flex-[3] border-r border-surface-overlay" : ""}>
            <div className="flex px-5 py-4 gap-4">
              <FormRow label="Title">
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Short task title (optional)"
                  className="bg-input border border-surface-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none w-full focus:border-accent"
                />
              </FormRow>
              {/* Mode toggle: Prompt | Steps (hidden when workflow selected) */}
              {!workflowId && (
              <div className="flex flex-row items-center gap-1">
                <button
                  onClick={() => {
                    if (stepsMode) {
                      if (steps && steps.length === 1 && steps[0].type === "agent") {
                        setPrompt(steps[0].prompt ?? "");
                      }
                      setSteps(null);
                    }
                  }}
                  className={`px-3 py-1 text-xs font-semibold rounded-l-md border transition-colors ${
                    !stepsMode
                      ? "bg-accent/10 text-accent border-accent/30"
                      : "bg-transparent text-text-dim border-surface-border hover:text-text cursor-pointer"
                  }`}
                >
                  Prompt
                </button>
                <button
                  onClick={() => {
                    if (!stepsMode) {
                      const initial: StepDef[] = prompt.trim()
                        ? [{ id: "step_1", type: "agent", prompt, label: "", on_failure: "abort" }]
                        : [];
                      setSteps(initial);
                    }
                  }}
                  className={`px-3 py-1 text-xs font-semibold rounded-r-md border border-l-0 transition-colors ${
                    stepsMode
                      ? "bg-accent/10 text-accent border-accent/30"
                      : "bg-transparent text-text-dim border-surface-border hover:text-text cursor-pointer"
                  }`}
                >
                  Steps
                </button>
              </div>
              )}

              {/* Prompt mode */}
              {!stepsMode && (
                <>
                  <WorkspaceFilePrompt
                    workspaceId={workspaceId ?? selectedBot?.shared_workspace_id}
                    filePath={workspaceFilePath}
                    onLink={(path, wsId) => { setWorkspaceFilePath(path); setWorkspaceId(wsId); setPromptTemplateId(null); }}
                    onUnlink={() => { setWorkspaceFilePath(null); setWorkspaceId(null); }}
                  />
                  {!workspaceFilePath && (
                    <>
                      <PromptTemplateLink
                        templateId={promptTemplateId}
                        onLink={(id) => setPromptTemplateId(id)}
                        onUnlink={() => setPromptTemplateId(null)}
                      />
                      <LlmPrompt
                        value={prompt}
                        onChange={setPrompt}
                        label="Prompt"
                        placeholder={workflowId ? "Optional — workflow will be triggered directly" : promptTemplateId ? "Using linked template..." : "Task prompt... (type @ for autocomplete)"}
                        rows={isWide ? 12 : 6}
                        fieldType="task_prompt"
                        botId={botId}
                        channelId={channelId}
                      />
                    </>
                  )}
                </>
              )}

              {/* Steps mode */}
              {stepsMode && (
                <TaskStepEditor
                  steps={steps!}
                  onChange={setSteps}
                  stepStates={existingTask?.step_states}
                  readOnly={false}
                />
              )}

              {/* Result/Error display */}
              {!isCreate && existingTask?.result && !stepsMode && (
                <div>
                  <div className="text-xs font-semibold text-text-muted mb-1.5">Result</div>
                  <div className="p-3 rounded-lg bg-input border border-surface-raised text-xs text-success whitespace-pre-wrap max-h-[300px] overflow-auto font-mono">
                    {existingTask.result}
                  </div>
                </div>
              )}

              {!isCreate && existingTask?.error && !stepsMode && (
                <div>
                  <div className="text-xs font-semibold text-text-muted mb-1.5">Error</div>
                  <div className="p-3 rounded-lg bg-danger/[0.08] border border-danger/[0.15] text-xs text-danger whitespace-pre-wrap max-h-[200px] overflow-auto font-mono">
                    {existingTask.error}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Metadata fields */}
          <div className={`px-5 py-4 ${isWide ? "flex-[2]" : "border-t border-surface-overlay"}`}>
            <div className="flex gap-4">
              <Section title="Configuration">
                <FormRow label="Bot">
                  <SelectInput
                    value={botId}
                    onChange={setBotId}
                    options={botOptions}
                  />
                </FormRow>

                <FormRow label="Channel" description="Assign to a channel for dispatch">
                  <SelectInput
                    value={channelId}
                    onChange={isCreate ? setChannelId : () => {}}
                    options={channelOptions}
                    style={isCreate ? {} : { opacity: 0.5, pointerEvents: "none" }}
                  />
                </FormRow>

                {!isCreate && (
                  <FormRow label="Status">
                    <SelectInput
                      value={status}
                      onChange={setStatus}
                      options={STATUS_OPTIONS}
                    />
                  </FormRow>
                )}

                <FormRow label="Task Type">
                  <SelectInput
                    value={taskType}
                    onChange={setTaskType}
                    options={TASK_TYPE_OPTIONS_CREATE}
                  />
                </FormRow>

                {!stepsMode && (
                  <FormRow label="Workflow Trigger" description="Run a workflow instead of a prompt">
                    <SelectInput
                      value={workflowId || ""}
                      onChange={(v) => {
                        setWorkflowId(v || null);
                        if (!v) setWorkflowSessionMode(null);
                      }}
                      options={[
                        { label: "None", value: "" },
                        ...(workflows || []).map((w) => ({ label: `${w.name} (${w.id})`, value: w.id })),
                      ]}
                    />
                  </FormRow>
                )}
                {workflowId && !stepsMode && (
                  <FormRow label="Session Mode" description="Workflow step session isolation">
                    <SelectInput
                      value={workflowSessionMode || ""}
                      onChange={(v) => setWorkflowSessionMode(v || null)}
                      options={[
                        { label: "Default (from workflow)", value: "" },
                        { label: "Shared", value: "shared" },
                        { label: "Isolated", value: "isolated" },
                      ]}
                    />
                  </FormRow>
                )}
              </Section>

              <Section title="Trigger">
                <TriggerSection
                  triggerConfig={triggerConfig}
                  onTriggerConfigChange={setTriggerConfig}
                  scheduledAt={scheduledAt}
                  onScheduledAtChange={setScheduledAt}
                  recurrence={recurrence}
                  onRecurrenceChange={setRecurrence}
                />
              </Section>

              <Section title="Skills & Tools">
                <ChipPicker
                  label="Skills"
                  items={skillOptions}
                  selected={selectedSkillIds}
                  onAdd={(id) => setSelectedSkillIds([...selectedSkillIds, id])}
                  onRemove={(id) => setSelectedSkillIds(selectedSkillIds.filter((x) => x !== id))}
                />
                <ChipPicker
                  label="Tools"
                  items={toolOptions}
                  selected={selectedToolKeys}
                  onAdd={(key) => setSelectedToolKeys([...selectedToolKeys, key])}
                  onRemove={(key) => setSelectedToolKeys(selectedToolKeys.filter((x) => x !== key))}
                />
              </Section>

              <Section title="Options">
                <Toggle
                  value={triggerRagLoop}
                  onChange={setTriggerRagLoop}
                  label="Trigger RAG Loop"
                  description="Create follow-up agent turn after task completes"
                />

                <FormRow label="Model Override">
                  <LlmModelDropdown
                    value={modelOverride}
                    onChange={setModelOverride}
                    placeholder="Inherit from bot"
                    allowClear
                  />
                </FormRow>

                <FormRow label="Fallback Models" description="Ordered fallback chain for this task.">
                  <FallbackModelList
                    value={fallbackModels}
                    onChange={setFallbackModels}
                  />
                </FormRow>

                <FormRow label="Max run time (seconds)">
                  <TextInput
                    value={maxRunSeconds}
                    onChangeText={setMaxRunSeconds}
                    placeholder="Inherit from channel/global"
                    type="number"
                  />
                </FormRow>
              </Section>

              {/* Read-only timing info in edit mode */}
              {!isCreate && existingTask && (
                <Section title="Timing">
                  <div className="flex gap-2">
                    <InfoRow label="Created" value={formatDateTime(existingTask.created_at)} />
                    <InfoRow label="Scheduled" value={formatDateTime(existingTask.scheduled_at)} />
                    <InfoRow label="Run At" value={formatDateTime(existingTask.run_at)} />
                    <InfoRow label="Completed" value={formatDateTime(existingTask.completed_at)} />
                    <InfoRow label="Retry Count" value={String(existingTask.retry_count)} />
                    {existingTask.run_count > 0 && (
                      <InfoRow label="Run Count" value={String(existingTask.run_count)} />
                    )}
                  </div>
                </Section>
              )}

              {/* Read-only dispatch info in edit mode */}
              {!isCreate && existingTask && (
                <Section title="Dispatch">
                  <div className="flex gap-2">
                    <InfoRow label="Type" value={existingTask.dispatch_type} />
                    {existingTask.delegation_session_id && (
                      <InfoRow label="Delegation Context" value={existingTask.delegation_session_id.slice(0, 8) + "..."} />
                    )}
                    {existingTask.dispatch_config && (
                      <div>
                        <div className="text-[11px] text-text-dim mb-1">Dispatch Config</div>
                        <pre className="text-[10px] text-text-muted bg-input p-2 rounded-md overflow-auto max-h-[120px] m-0">
                          {JSON.stringify(existingTask.dispatch_config, null, 2)}
                        </pre>
                      </div>
                    )}
                    {existingTask.execution_config && (
                      <div>
                        <div className="text-[11px] text-text-dim mb-1">Execution Config</div>
                        <pre className="text-[10px] text-text-muted bg-input p-2 rounded-md overflow-auto max-h-[120px] m-0">
                          {JSON.stringify(existingTask.execution_config, null, 2)}
                        </pre>
                      </div>
                    )}
                    {existingTask.callback_config && (
                      <div>
                        <div className="text-[11px] text-text-dim mb-1">Callback Config</div>
                        <pre className="text-[10px] text-text-muted bg-input p-2 rounded-md overflow-auto max-h-[120px] m-0">
                          {JSON.stringify(existingTask.callback_config, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </Section>
              )}
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}
