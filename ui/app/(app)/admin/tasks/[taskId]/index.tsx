import { useCallback } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useQueryClient } from "@tanstack/react-query";
import { useTask, useUpdateTask, useDeleteTask } from "@/src/api/hooks/useTasks";
import { useWorkflowRun } from "@/src/api/hooks/useWorkflows";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useState } from "react";
import { ChevronLeft, Trash2, Zap } from "lucide-react";
import { Link } from "expo-router";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { PromptTemplateLink } from "@/src/components/shared/PromptTemplateLink";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { FormRow, TextInput, SelectInput, Toggle, Section } from "@/src/components/shared/FormControls";
import { DateTimePicker } from "@/src/components/shared/DateTimePicker";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { useThemeTokens } from "@/src/theme/tokens";

const STATUS_OPTIONS = [
  { label: "Pending", value: "pending" },
  { label: "Active (Schedule)", value: "active" },
  { label: "Running", value: "running" },
  { label: "Complete", value: "complete" },
  { label: "Failed", value: "failed" },
  { label: "Cancelled", value: "cancelled" },
];

const TASK_TYPE_OPTIONS = [
  { label: "Scheduled", value: "scheduled" },
  { label: "Heartbeat", value: "heartbeat" },
  { label: "Delegation", value: "delegation" },
  { label: "Harness", value: "harness" },
  { label: "Exec", value: "exec" },
  { label: "Callback", value: "callback" },
  { label: "API", value: "api" },
  { label: "Workflow", value: "workflow" },
  { label: "Agent", value: "agent" },
];

function fmtDatetime(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function InfoRow({ label, value }: { label: string; value: string }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: t.textDim }}>{label}</span>
      <span style={{ fontSize: 11, color: t.text, fontFamily: "monospace" }}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scheduled At picker — datetime-local + quick offset presets
// ---------------------------------------------------------------------------
const SCHEDULE_PRESETS = [
  { label: "+30m", value: "+30m" },
  { label: "+1h", value: "+1h" },
  { label: "+2h", value: "+2h" },
  { label: "+6h", value: "+6h" },
  { label: "+1d", value: "+1d" },
  { label: "+7d", value: "+7d" },
];

function ScheduledAtPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const t = useThemeTokens();
  const isRelative = /^\+\d+[smhd]$/.test(value);

  return (
    <FormRow label="Scheduled At">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
          <button
            onClick={() => onChange("")}
            style={{
              padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
              borderRadius: 6,
              background: !value ? t.accent : t.surfaceRaised,
              color: !value ? "#fff" : t.textMuted,
            }}
          >
            Now
          </button>
          {SCHEDULE_PRESETS.map((p) => (
            <button
              key={p.value}
              onClick={() => onChange(p.value)}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
                borderRadius: 6,
                background: value === p.value ? t.accent : t.surfaceRaised,
                color: value === p.value ? "#fff" : t.textMuted,
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
        <DateTimePicker
          value={isRelative ? "" : value}
          onChange={onChange}
          placeholder="Pick a date & time..."
        />
        {isRelative && (
          <div style={{ fontSize: 10, color: t.textDim }}>
            Relative: runs {value} from now
          </div>
        )}
      </div>
    </FormRow>
  );
}

// ---------------------------------------------------------------------------
// Recurrence picker — preset pills + custom input
// ---------------------------------------------------------------------------
const RECURRENCE_PRESETS = [
  { label: "None", value: "" },
  { label: "30 min", value: "+30m" },
  { label: "1 hour", value: "+1h" },
  { label: "2 hours", value: "+2h" },
  { label: "6 hours", value: "+6h" },
  { label: "12 hours", value: "+12h" },
  { label: "Daily", value: "+1d" },
  { label: "Weekly", value: "+7d" },
];

function RecurrencePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const t = useThemeTokens();
  const isPreset = RECURRENCE_PRESETS.some((p) => p.value === value);
  const showCustom = !!value && !isPreset;

  return (
    <FormRow label="Recurrence">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {RECURRENCE_PRESETS.map((p) => (
            <button
              key={p.value}
              onClick={() => onChange(p.value)}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
                borderRadius: 6,
                background: value === p.value ? (p.value ? t.warningSubtle : t.surfaceBorder) : t.surfaceRaised,
                color: value === p.value ? (p.value ? t.warning : t.text) : t.textMuted,
              }}
            >
              {p.label}
            </button>
          ))}
          <button
            onClick={() => { if (!showCustom) onChange("+3h"); }}
            style={{
              padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
              borderRadius: 6,
              background: showCustom ? t.warningSubtle : t.surfaceRaised,
              color: showCustom ? t.warning : t.textMuted,
            }}
          >
            Custom
          </button>
        </div>
        {showCustom && (
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="+3h, +45m, etc."
            style={{
              background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 8,
              padding: "7px 12px", color: t.text, fontSize: 13, outline: "none",
              maxWidth: 200,
            }}
          />
        )}
      </div>
    </FormRow>
  );
}

function EnableToggle({ enabled, onChange, compact }: { enabled: boolean; onChange: (v: boolean) => void; compact?: boolean }) {
  const t = useThemeTokens();
  return (
    <button
      onClick={() => onChange(!enabled)}
      title={enabled ? "Enabled" : "Disabled"}
      style={{
        display: "flex", alignItems: "center", gap: compact ? 0 : 6,
        padding: compact ? "5px 6px" : "5px 12px", fontSize: 12, fontWeight: 600,
        border: "none", cursor: "pointer", borderRadius: 6, flexShrink: 0,
        background: enabled ? t.successSubtle : t.dangerSubtle,
        color: enabled ? t.success : t.danger,
      }}
    >
      <div style={{
        width: 28, height: 16, borderRadius: 8, position: "relative",
        background: enabled ? t.success : t.textDim,
        transition: "background 0.2s",
      }}>
        <div style={{
          width: 12, height: 12, borderRadius: 6, background: "#fff",
          position: "absolute", top: 2,
          left: enabled ? 14 : 2,
          transition: "left 0.2s",
        }} />
      </div>
      {!compact && (enabled ? "Enabled" : "Disabled")}
    </button>
  );
}

function WorkflowRunLink({ runId, stepIndex, t }: { runId: string; stepIndex?: number; t: ReturnType<typeof useThemeTokens> }) {
  const { data: run } = useWorkflowRun(runId);
  const href = run ? `/admin/workflows/${run.workflow_id}` : undefined;
  return (
    <div>
      <div style={{ fontSize: 11, color: t.textDim, marginBottom: 6, display: "flex", alignItems: "center", gap: 4 }}>
        <Zap size={11} color="#ea580c" />
        Workflow Step
      </div>
      <div style={{
        display: "flex", flexDirection: "column", gap: 6,
        padding: 8, borderRadius: 6, background: "rgba(249,115,22,0.06)",
        border: "1px solid rgba(249,115,22,0.15)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 11, color: t.textDim }}>Run</span>
          {href ? (
            <Link href={href as any} style={{ fontSize: 11, color: t.accent, fontFamily: "monospace" }}>
              {runId.slice(0, 8)}...
            </Link>
          ) : (
            <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>{runId.slice(0, 8)}...</span>
          )}
        </div>
        {stepIndex != null && (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
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
  const { taskId } = useLocalSearchParams<{ taskId: string }>();
  const goBackNav = useGoBack("/admin/tasks");
  const qc = useQueryClient();
  const { data: task, isLoading } = useTask(taskId);
  const updateMut = useUpdateTask(taskId);
  const deleteMut = useDeleteTask();
  const { data: bots } = useBots();
  const { data: channels } = useChannels();

  const { width: winWidth } = useWindowDimensions();
  const isWide = winWidth >= 768;

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
  const [initialized, setInitialized] = useState(false);

  if (task && !initialized) {
    setTitle(task.title || "");
    setPrompt(task.prompt || "");
    setPromptTemplateId(task.prompt_template_id || null);
    setWorkspaceFilePath(task.workspace_file_path ?? null);
    setWorkspaceId(task.workspace_id ?? null);
    setBotId(task.bot_id || "");
    setStatus(task.status || "pending");
    setTaskType(task.task_type || "scheduled");
    setScheduledAt(task.scheduled_at ? new Date(task.scheduled_at).toISOString().slice(0, 16) : "");
    setRecurrence(task.recurrence || "");
    setTriggerRagLoop(task.trigger_rag_loop ?? task.callback_config?.trigger_rag_loop ?? false);
    setModelOverride(task.model_override || task.callback_config?.model_override || "");
    setInitialized(true);
  }

  const hasPrompt = !!prompt.trim() || !!promptTemplateId || !!workspaceFilePath;

  const handleSave = useCallback(async () => {
    if (!hasPrompt || !botId) return;
    await updateMut.mutateAsync({
      prompt,
      title: title || null,
      prompt_template_id: promptTemplateId,
      workspace_file_path: workspaceFilePath,
      workspace_id: workspaceId,
      bot_id: botId,
      status,
      scheduled_at: scheduledAt || null,
      recurrence: recurrence || null,
      task_type: taskType,
      trigger_rag_loop: triggerRagLoop,
      model_override: modelOverride || null,
    });
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
  }, [prompt, title, promptTemplateId, workspaceFilePath, workspaceId, botId, status, scheduledAt, recurrence, taskType, triggerRagLoop, modelOverride, hasPrompt, updateMut, qc]);

  const handleDelete = useCallback(async () => {
    if (!taskId || !confirm("Delete this task?")) return;
    await deleteMut.mutateAsync(taskId);
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
    goBackNav();
  }, [taskId, deleteMut, qc, goBackNav]);

  const goBack = goBackNav;

  const botOptions = (bots || []).map((b) => ({ label: b.name || b.id, value: b.id }));
  const channelOptions = [
    { label: "\u2014 None \u2014", value: "" },
    ...(channels || []).map((c: any) => ({
      label: c.display_name || c.name || c.id,
      value: String(c.id),
    })),
  ];

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px", borderBottom: `1px solid ${t.surfaceBorder}`, flexShrink: 0,
        gap: 8,
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0 }}>
          <ChevronLeft size={22} color={t.textMuted} />
        </button>
        <span style={{ color: t.text, fontSize: 14, fontWeight: 700, flexShrink: 0 }}>Edit Task</span>
        {isWide && (
          <span style={{ color: t.textDim, fontSize: 11, fontFamily: "monospace" }}>
            {taskId?.slice(0, 8)}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <button
          onClick={handleDelete}
          disabled={deleteMut.isPending}
          title="Delete"
          style={{
            display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
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
          disabled={updateMut.isPending || !hasPrompt || !botId}
          style={{
            padding: isWide ? "6px 20px" : "6px 12px", fontSize: 13, fontWeight: 600,
            border: "none", borderRadius: 6, flexShrink: 0,
            background: (!hasPrompt || !botId) ? t.surfaceBorder : t.accent,
            color: (!hasPrompt || !botId) ? t.textDim : "#fff",
            cursor: (!hasPrompt || !botId) ? "not-allowed" : "pointer",
          }}
        >
          {updateMut.isPending ? "..." : "Save"}
        </button>
      </div>

      {/* Error display */}
      {(updateMut.error || deleteMut.error) && (
        <div style={{ padding: "8px 20px", background: t.dangerSubtle, color: t.danger, fontSize: 12 }}>
          {(updateMut.error || deleteMut.error)?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        ...(isWide ? { flexDirection: "row", flex: 1 } : {}),
      }}>
        {/* Prompt + Result/Error */}
        <div style={{
          ...(isWide ? { flex: 3, borderRight: `1px solid ${t.surfaceOverlay}` } : {}),
          display: "flex", flexDirection: "column",
        }}>
          <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 16 }}>
            <FormRow label="Title">
              <TextInput
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
                        placeholder={promptTemplateId ? "Using linked template..." : "Task prompt..."}
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
                <SelectInput
                  value={task?.channel_id || ""}
                  onChange={() => {}}
                  options={channelOptions}
                  style={{ opacity: 0.5, pointerEvents: "none" }}
                />
              </FormRow>

              <FormRow label="Status">
                <SelectInput value={status} onChange={setStatus} options={STATUS_OPTIONS} />
              </FormRow>

              <FormRow label="Task Type">
                <SelectInput value={taskType} onChange={setTaskType} options={TASK_TYPE_OPTIONS} />
              </FormRow>
            </Section>

            <Section title="Scheduling">
              <ScheduledAtPicker value={scheduledAt} onChange={setScheduledAt} />
              <RecurrencePicker value={recurrence} onChange={setRecurrence} />
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
      </ScrollView>
    </View>
  );
}
