import { useState, useCallback } from "react";
import { ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ChevronLeft, Trash2, Copy, FileText } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useTask, useCreateTask, useUpdateTask, useDeleteTask, type TaskDetail } from "@/src/api/hooks/useTasks";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { PromptTemplateLink } from "@/src/components/shared/PromptTemplateLink";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { FormRow, TextInput, SelectInput, Toggle, Section } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { formatDateTime, isoToLocalInput, localInputToISO, getTimezoneAbbr } from "@/src/utils/time";
import { useThemeTokens } from "../../theme/tokens";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
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
  { label: "Delegation", value: "delegation" },
  { label: "Harness", value: "harness" },
  { label: "Exec", value: "exec" },
  { label: "API", value: "api" },
  { label: "Agent", value: "agent" },
];

const SCHEDULE_PRESETS = [
  { label: "+30m", value: "+30m" },
  { label: "+1h", value: "+1h" },
  { label: "+2h", value: "+2h" },
  { label: "+6h", value: "+6h" },
  { label: "+1d", value: "+1d" },
  { label: "+7d", value: "+7d" },
];

const RECURRENCE_PRESETS = [
  { label: "None", value: "" },
  { label: "30 min", value: "+30m" },
  { label: "1 hour", value: "+1h" },
  { label: "2 hours", value: "+2h" },
  { label: "6 hours", value: "+6h" },
  { label: "12 hours", value: "+12h" },
  { label: "Daily", value: "+1d" },
  { label: "Weekly", value: "+1w" },
];

// ---------------------------------------------------------------------------
// EnableToggle
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// ScheduledAtPicker
// ---------------------------------------------------------------------------
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
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            type="datetime-local"
            value={isRelative ? "" : value}
            onChange={(e) => onChange(e.target.value)}
            style={{
              background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 8,
              padding: "7px 12px", color: t.text, fontSize: 13,
              outline: "none", colorScheme: "dark",
            }}
          />
          <span style={{ fontSize: 10, color: t.textDim, whiteSpace: "nowrap" }}>
            {getTimezoneAbbr()}
          </span>
        </div>
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
// RecurrencePicker
// ---------------------------------------------------------------------------
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
                color: value === p.value ? (p.value ? t.warningMuted : t.text) : t.textMuted,
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
              color: showCustom ? t.warningMuted : t.textMuted,
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

// ---------------------------------------------------------------------------
// InfoRow
// ---------------------------------------------------------------------------
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
  const t = useThemeTokens();
  const isCreate = !taskId;
  const loadTaskId = taskId ?? cloneFromId;
  const { data: existingTask, isLoading: loadingTask } = useTask(loadTaskId ?? undefined);
  const createMut = useCreateTask();
  const updateMut = useUpdateTask(taskId ?? undefined);
  const deleteMut = useDeleteTask();
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const { width: winWidth } = useWindowDimensions();
  const isWide = winWidth >= 768;
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
  const [initialized, setInitialized] = useState(false);

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

  const hasPrompt = !!prompt.trim() || !!promptTemplateId || !!workspaceFilePath;

  const handleSave = useCallback(async () => {
    if (!hasPrompt || !botId) return;
    try {
      const scheduledAtISO = localInputToISO(scheduledAt) || null;
      if (isCreate) {
        await createMut.mutateAsync({
          prompt,
          title: title || null,
          prompt_template_id: promptTemplateId,
          workspace_file_path: workspaceFilePath,
          workspace_id: workspaceId,
          bot_id: botId,
          channel_id: channelId || null,
          scheduled_at: scheduledAtISO,
          recurrence: recurrence || null,
          task_type: taskType,
          trigger_rag_loop: triggerRagLoop,
          model_override: modelOverride || null,
          fallback_models: fallbackModels.length > 0 ? fallbackModels : null,
          max_run_seconds: maxRunSeconds ? parseInt(maxRunSeconds) : null,
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
          task_type: taskType,
          trigger_rag_loop: triggerRagLoop,
          model_override: modelOverride || null,
          fallback_models: fallbackModels.length > 0 ? fallbackModels : null,
          max_run_seconds: maxRunSeconds ? parseInt(maxRunSeconds) : null,
        });
      }
      invalidateExtra();
      onSaved();
    } catch {
      // error is shown via mutation state
    }
  }, [prompt, title, botId, channelId, scheduledAt, recurrence, taskType, triggerRagLoop, modelOverride, fallbackModels, maxRunSeconds, status, isCreate, createMut, updateMut, onSaved, invalidateExtra, promptTemplateId, workspaceFilePath, workspaceId]);

  const handleDelete = useCallback(async () => {
    if (!taskId || !confirm("Delete this task?")) return;
    await deleteMut.mutateAsync(taskId);
    invalidateExtra();
    onSaved();
  }, [taskId, deleteMut, onSaved, invalidateExtra]);

  if (typeof document === "undefined") return null;
  const ReactDOM = require("react-dom");

  const router = useRouter();
  const selectedBot = bots?.find((b) => b.id === botId);
  const botOptions = (bots || []).map((b) => ({ label: b.name || b.id, value: b.id }));
  const channelOptions = [
    { label: "\u2014 None \u2014", value: "" },
    ...(channels || []).map((c: any) => ({
      label: c.display_name || c.name || c.id,
      value: String(c.id),
    })),
  ];

  const editorTitle = cloneFromId ? "New Task (Clone)" : isCreate ? "New Task" : "Edit Task";

  return ReactDOM.createPortal(
    <div style={{
      position: "fixed", inset: 0, zIndex: 10000,
      background: t.surface, display: "flex", flexDirection: "column",
    }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px", borderBottom: `1px solid ${t.surfaceBorder}`, flexShrink: 0,
        gap: 8,
      }}>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0 }}
        >
          <ChevronLeft size={22} color={t.textMuted} />
        </button>

        <span style={{ color: t.text, fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
          {editorTitle}
        </span>
        {cloneFromId && (
          <span style={{
            fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
            background: t.warningSubtle, color: t.warningMuted,
          }}>
            CLONE
          </span>
        )}
        {!isCreate && existingTask && isWide && (
          <span style={{ color: t.textDim, fontSize: 11, fontFamily: "monospace" }}>
            {taskId?.slice(0, 8)}
          </span>
        )}

        <div style={{ flex: 1 }} />

        {/* View Logs button (edit mode, when correlation_id available) */}
        {!isCreate && existingTask?.correlation_id && (
          <button
            onClick={() => {
              onClose();
              router.push(`/admin/logs/${existingTask.correlation_id}`);
            }}
            title="View Logs"
            style={{
              display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
              padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
              border: `1px solid ${t.accentMuted}`, borderRadius: 6,
              background: "transparent", color: t.accent, cursor: "pointer", flexShrink: 0,
            }}
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
            style={{
              display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
              padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
              border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
              background: "transparent", color: t.textMuted, cursor: "pointer", flexShrink: 0,
            }}
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
          disabled={saving || !hasPrompt || !botId}
          style={{
            padding: isWide ? "6px 20px" : "6px 12px", fontSize: 13, fontWeight: 600,
            border: "none", borderRadius: 6, flexShrink: 0,
            background: (!hasPrompt || !botId) ? t.surfaceBorder : t.accent,
            color: (!hasPrompt || !botId) ? t.textDim : "#fff",
            cursor: (!hasPrompt || !botId) ? "not-allowed" : "pointer",
          }}
        >
          {saving ? "..." : isCreate ? "Create" : "Save"}
        </button>
      </div>

      {/* Error display */}
      {(createMut.error || updateMut.error || deleteMut.error) && (
        <div style={{ padding: "8px 20px", background: t.dangerSubtle, color: t.danger, fontSize: 12 }}>
          {(createMut.error || updateMut.error || deleteMut.error)?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      {(((!isCreate && !cloneFromId) || cloneFromId) && loadingTask) ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <ActivityIndicator color={t.accent} />
        </div>
      ) : (
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
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Short task title (optional)"
                  style={{
                    background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 8,
                    padding: "7px 12px", color: t.text, fontSize: 13,
                    outline: "none", width: "100%",
                  }}
                />
              </FormRow>
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
                    placeholder={promptTemplateId ? "Using linked template..." : "Task prompt... (type @ for autocomplete)"}
                    rows={isWide ? 12 : 6}
                    generateContext="A prompt for an AI agent task. Describe what to accomplish, constraints, and expected output."
                  />
                </>
              )}

              {!isCreate && existingTask?.result && (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 6 }}>Result</div>
                  <div style={{
                    padding: 12, borderRadius: 8, background: t.inputBg, border: `1px solid ${t.surfaceRaised}`,
                    fontSize: 12, color: t.success, whiteSpace: "pre-wrap",
                    maxHeight: 300, overflow: "auto", fontFamily: "monospace",
                  }}>
                    {existingTask.result}
                  </div>
                </div>
              )}

              {!isCreate && existingTask?.error && (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 6 }}>Error</div>
                  <div style={{
                    padding: 12, borderRadius: 8, background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
                    fontSize: 12, color: t.danger, whiteSpace: "pre-wrap",
                    maxHeight: 200, overflow: "auto", fontFamily: "monospace",
                  }}>
                    {existingTask.error}
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
                    options={TASK_TYPE_OPTIONS}
                  />
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
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <InfoRow label="Type" value={existingTask.dispatch_type} />
                    {existingTask.delegation_session_id && (
                      <InfoRow label="Delegation Session" value={existingTask.delegation_session_id.slice(0, 8) + "..."} />
                    )}
                    {existingTask.dispatch_config && (
                      <div>
                        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>Dispatch Config</div>
                        <pre style={{
                          fontSize: 10, color: t.textMuted, background: t.inputBg, padding: 8,
                          borderRadius: 6, overflow: "auto", maxHeight: 120, margin: 0,
                        }}>
                          {JSON.stringify(existingTask.dispatch_config, null, 2)}
                        </pre>
                      </div>
                    )}
                    {existingTask.execution_config && (
                      <div>
                        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>Execution Config</div>
                        <pre style={{
                          fontSize: 10, color: t.textMuted, background: t.inputBg, padding: 8,
                          borderRadius: 6, overflow: "auto", maxHeight: 120, margin: 0,
                        }}>
                          {JSON.stringify(existingTask.execution_config, null, 2)}
                        </pre>
                      </div>
                    )}
                    {existingTask.callback_config && (
                      <div>
                        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>Callback Config</div>
                        <pre style={{
                          fontSize: 10, color: t.textMuted, background: t.inputBg, padding: 8,
                          borderRadius: 6, overflow: "auto", maxHeight: 120, margin: 0,
                        }}>
                          {JSON.stringify(existingTask.callback_config, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </Section>
              )}
            </div>
          </div>
        </ScrollView>
      )}
    </div>,
    document.body,
  );
}
