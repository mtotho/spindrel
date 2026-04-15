import { useCallback, useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useTask, useUpdateTask, useDeleteTask } from "@/src/api/hooks/useTasks";
import { useWorkflowRun, useWorkflows } from "@/src/api/hooks/useWorkflows";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { Trash2, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { PromptTemplateLink } from "@/src/components/shared/PromptTemplateLink";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { FormRow, TextInput as FormTextInput, SelectInput, Toggle, Section } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { isoToLocalInput, localInputToISO } from "@/src/utils/time";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  ScheduledAtPicker,
  RecurrencePicker,
  ScheduleSummary,
  EnableToggle,
  InfoRow,
  STATUS_OPTIONS,
  TASK_TYPE_OPTIONS_FULL,
} from "@/src/components/shared/SchedulingPickers";

function fmtDatetime(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function WorkflowRunLink({ runId, stepIndex, t }: { runId: string; stepIndex?: number; t: ReturnType<typeof useThemeTokens> }) {
  const { data: run } = useWorkflowRun(runId);
  const href = run ? `/admin/workflows/${run.workflow_id}` : undefined;
  return (
    <div>
      <div style={{ fontSize: 11, color: t.textDim, marginBottom: 6, display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
        <Zap size={11} color="#ea580c" />
        Workflow Step
      </div>
      <div style={{
        display: "flex", flexDirection: "column", gap: 6,
        padding: 8, borderRadius: 6, background: "rgba(249,115,22,0.06)",
        border: "1px solid rgba(249,115,22,0.15)",
      }}>
        <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 11, color: t.textDim }}>Run</span>
          {href ? (
            <Link to={href} style={{ fontSize: 11, color: t.accent, fontFamily: "monospace" } as any}>
              {runId.slice(0, 8)}...
            </Link>
          ) : (
            <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>{runId.slice(0, 8)}...</span>
          )}
        </div>
        {stepIndex != null && (
          <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 11, color: t.textDim }}>Step Index</span>
            <span style={{ fontSize: 11, color: t.text, fontFamily: "monospace" }}>{stepIndex}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function TaskDetailScreen() {
  const t = useThemeTokens();
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: task, isLoading } = useTask(taskId);
  const updateMut = useUpdateTask(taskId);
  const deleteMut = useDeleteTask();
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const { data: workflows } = useWorkflows();

  const [isWide, setIsWide] = useState(() => typeof window !== "undefined" && window.innerWidth >= 768);
  useEffect(() => {
    const handler = () => setIsWide(window.innerWidth >= 768);
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, []);

  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [promptTemplateId, setPromptTemplateId] = useState<string | null>(null);
  const [workspaceFilePath, setWorkspaceFilePath] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [botId, setBotId] = useState("");
  const [status, setStatus] = useState("pending");
  const [taskType, setTaskType] = useState("scheduled");
  const [scheduledAt, setScheduledAt] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [triggerRagLoop, setTriggerRagLoop] = useState(false);
  const [modelOverride, setModelOverride] = useState("");
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [workflowSessionMode, setWorkflowSessionMode] = useState<string | null>(null);
  const [initialized, setInitialized] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [snapshot, setSnapshot] = useState("");

  if (task && !initialized) {
    setTitle(task.title || "");
    setPrompt(task.prompt || "");
    setPromptTemplateId(task.prompt_template_id || null);
    setWorkspaceFilePath(task.workspace_file_path ?? null);
    setWorkspaceId(task.workspace_id ?? null);
    setBotId(task.bot_id || "");
    setStatus(task.status || "pending");
    setTaskType(task.task_type || "scheduled");
    setScheduledAt(task.scheduled_at ? isoToLocalInput(task.scheduled_at) : "");
    setRecurrence(task.recurrence || "");
    setTriggerRagLoop(task.trigger_rag_loop ?? task.callback_config?.trigger_rag_loop ?? false);
    setModelOverride(task.model_override || task.callback_config?.model_override || "");
    setWorkflowId(task.workflow_id ?? null);
    setWorkflowSessionMode(task.workflow_session_mode ?? null);
    setInitialized(true);
    setSnapshot(JSON.stringify([
      task.title || "", task.prompt || "", task.prompt_template_id || null,
      task.workspace_file_path ?? null, task.workspace_id ?? null, task.bot_id || "",
      task.status || "pending", task.task_type || "scheduled",
      task.scheduled_at ? isoToLocalInput(task.scheduled_at) : "",
      task.recurrence || "",
      task.trigger_rag_loop ?? task.callback_config?.trigger_rag_loop ?? false,
      task.model_override || task.callback_config?.model_override || "",
      task.workflow_id ?? null, task.workflow_session_mode ?? null,
    ]));
  }

  const hasPromptOrWorkflow = !!prompt.trim() || !!promptTemplateId || !!workspaceFilePath || !!workflowId;
  const currentSnap = JSON.stringify([
    title, prompt, promptTemplateId, workspaceFilePath, workspaceId, botId,
    status, taskType, scheduledAt, recurrence, triggerRagLoop, modelOverride,
    workflowId, workflowSessionMode,
  ]);
  const isDirty = initialized && currentSnap !== snapshot;

  const handleSave = useCallback(async () => {
    if (!hasPromptOrWorkflow || !botId) return;
    const scheduledAtISO = localInputToISO(scheduledAt) || null;
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
      task_type: taskType,
      trigger_rag_loop: triggerRagLoop,
      model_override: modelOverride || null,
      workflow_id: workflowId || null,
      workflow_session_mode: workflowSessionMode || null,
    });
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
    setSnapshot(currentSnap);
    setSavedFlash(true);
    setTimeout(() => setSavedFlash(false), 2000);
  }, [prompt, title, promptTemplateId, workspaceFilePath, workspaceId, botId, status, scheduledAt, recurrence, taskType, triggerRagLoop, modelOverride, workflowId, workflowSessionMode, hasPromptOrWorkflow, updateMut, qc, currentSnap]);

  const handleDelete = useCallback(async () => {
    if (!taskId || !confirm("Delete this task?")) return;
    await deleteMut.mutateAsync(taskId);
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
    navigate("/admin/tasks");
  }, [taskId, deleteMut, qc, navigate]);

  const botOptions = (bots || []).map((b) => ({ label: b.name || b.id, value: b.id }));

  if (isLoading) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", background: t.surface }}>
        <div className="chat-spinner" />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, background: t.surface, overflow: "hidden" }}>
      {/* Header */}
      <PageHeader variant="detail"
        parentLabel="Tasks"
        backTo="/admin/tasks"
        title="Edit Task"
        subtitle={taskId?.slice(0, 8)}
        right={<>
          <button
            onClick={handleDelete}
            disabled={deleteMut.isPending}
            title="Delete"
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: isWide ? 6 : 0,
              padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
              border: `1px solid ${t.dangerBorder}`, borderRadius: 6,
              background: "transparent", color: t.danger, cursor: "pointer", flexShrink: 0,
            }}
          >
            <Trash2 size={14} />
            {isWide && "Delete"}
          </button>
          <EnableToggle
            enabled={status !== "cancelled"}
            onChange={(on) => {
              const isSchedule = !!recurrence;
              setStatus(on ? (isSchedule ? "active" : "pending") : "cancelled");
            }}
            compact={!isWide}
          />
          <button
            onClick={handleSave}
            disabled={updateMut.isPending || !hasPromptOrWorkflow || !botId || !isDirty}
            style={{
              padding: isWide ? "6px 20px" : "6px 12px", fontSize: 13, fontWeight: 600,
              border: "none", borderRadius: 6, flexShrink: 0,
              background: savedFlash ? t.success : (!hasPromptOrWorkflow || !botId || !isDirty) ? t.surfaceBorder : t.accent,
              color: savedFlash ? "#fff" : (!hasPromptOrWorkflow || !botId || !isDirty) ? t.textDim : "#fff",
              cursor: (!hasPromptOrWorkflow || !botId || !isDirty) ? "default" : "pointer",
              transition: "background 0.2s",
            }}
          >
            {updateMut.isPending ? "..." : savedFlash ? "Saved!" : isDirty ? "Save" : "Saved"}
          </button>
        </>}
      />

      {/* Error display */}
      {(updateMut.error || deleteMut.error) && (
        <div style={{ padding: "8px 20px", background: t.dangerSubtle, color: t.danger, fontSize: 12 }}>
          {(updateMut.error || deleteMut.error)?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      <div style={{
        flex: 1, overflowY: "auto", minHeight: 0,
        ...(isWide ? { display: "flex", flexDirection: "row" as const } : {}),
      }}>
        {/* Prompt + Result/Error */}
        <div style={{
          ...(isWide ? { flex: 3, borderRight: `1px solid ${t.surfaceOverlay}` } : {}),
          display: "flex", flexDirection: "column",
        }}>
          <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 16 }}>
            <FormRow label="Title">
              <FormTextInput
                value={title}
                onChangeText={setTitle}
                placeholder="Short task title (optional)"
              />
            </FormRow>
            {(() => {
              const selectedBot = bots?.find((b: any) => b.id === botId);
              const botWsId = selectedBot?.shared_workspace_id;
              return (
                <>
                  <WorkspaceFilePrompt
                    workspaceId={workspaceId ?? botWsId}
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
                        placeholder={workflowId ? "Optional — workflow will be triggered directly" : promptTemplateId ? "Using linked template..." : "Task prompt..."}
                        rows={isWide ? 12 : 6}
                        fieldType="task_prompt"
                        botId={botId}
                        channelId={task?.channel_id ?? undefined}
                      />
                    </>
                  )}
                </>
              );
            })()}

            {task?.result && (
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 6 }}>Result</div>
                <div style={{
                  padding: 12, borderRadius: 8, background: t.inputBg, border: `1px solid ${t.surfaceRaised}`,
                  fontSize: 12, color: t.success, whiteSpace: "pre-wrap",
                  maxHeight: 300, overflow: "auto", fontFamily: "monospace",
                }}>
                  {task.result}
                </div>
              </div>
            )}

            {task?.error && (
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 6 }}>Error</div>
                <div style={{
                  padding: 12, borderRadius: 8, background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
                  fontSize: 12, color: t.danger, whiteSpace: "pre-wrap",
                  maxHeight: 200, overflow: "auto", fontFamily: "monospace",
                }}>
                  {task.error}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Metadata fields */}
        <div style={{
          ...(isWide ? { flex: 2 } : {}),
          padding: "16px 20px",
          borderTop: isWide ? "none" : `1px solid ${t.surfaceOverlay}`,
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Section title="Configuration">
              <FormRow label="Bot">
                <SelectInput value={botId} onChange={setBotId} options={botOptions} />
              </FormRow>

              <FormRow label="Channel">
                {task?.channel_id ? (
                  <Link to={`/channels/${task.channel_id}` as any}
                    style={{ fontSize: 13, color: t.accent, padding: "7px 0" } as any}
                  >
                    {channels?.find((c: any) => String(c.id) === String(task.channel_id))?.display_name
                      || channels?.find((c: any) => String(c.id) === String(task.channel_id))?.name
                      || task.channel_id}
                  </Link>
                ) : (
                  <span style={{ fontSize: 13, color: t.textDim, padding: "7px 0" }}>
                    No channel
                  </span>
                )}
              </FormRow>

              <FormRow label="Status">
                <SelectInput value={status} onChange={setStatus} options={STATUS_OPTIONS} />
              </FormRow>

              <FormRow label="Task Type">
                <SelectInput value={taskType} onChange={setTaskType} options={TASK_TYPE_OPTIONS_FULL} />
              </FormRow>

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
              {workflowId && (
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

            <Section title="Scheduling">
              <ScheduledAtPicker value={scheduledAt} onChange={setScheduledAt} />
              <RecurrencePicker value={recurrence} onChange={setRecurrence} />
              <ScheduleSummary scheduledAt={scheduledAt} recurrence={recurrence} />
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
            </Section>

            {task && (
              <Section title="Timing">
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <InfoRow label="Created" value={fmtDatetime(task.created_at)} />
                  <InfoRow label="Scheduled" value={fmtDatetime(task.scheduled_at)} />
                  <InfoRow label="Run At" value={fmtDatetime(task.run_at)} />
                  <InfoRow label="Completed" value={fmtDatetime(task.completed_at)} />
                  <InfoRow label="Retry Count" value={String(task.retry_count)} />
                  {task.run_count > 0 && (
                    <InfoRow label="Run Count" value={String(task.run_count)} />
                  )}
                </div>
              </Section>
            )}

            {task && (
              <Section title="Dispatch">
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <InfoRow label="Type" value={task.dispatch_type} />
                  {task.dispatch_config && (
                    <div>
                      <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>Config</div>
                      <pre style={{
                        fontSize: 10, color: t.textMuted, background: t.inputBg, padding: 8,
                        borderRadius: 6, overflow: "auto", maxHeight: 120, margin: 0,
                      }}>
                        {JSON.stringify(task.dispatch_config, null, 2)}
                      </pre>
                    </div>
                  )}
                  {task.callback_config?.workflow_run_id ? (
                    <WorkflowRunLink
                      runId={task.callback_config.workflow_run_id}
                      stepIndex={task.callback_config.workflow_step_index}
                      t={t}
                    />
                  ) : task.callback_config ? (
                    <div>
                      <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>Callback Config</div>
                      <pre style={{
                        fontSize: 10, color: t.textMuted, background: t.inputBg, padding: 8,
                        borderRadius: 6, overflow: "auto", maxHeight: 120, margin: 0,
                      }}>
                        {JSON.stringify(task.callback_config, null, 2)}
                      </pre>
                    </div>
                  ) : null}
                </div>
              </Section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
