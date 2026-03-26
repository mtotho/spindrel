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
import { FormRow, SelectInput, Toggle, Section } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function toLocalDatetimeString(d: Date): string {
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${mo}-${da}T${h}:${mi}`;
}

function fmtDatetime(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

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
  { label: "Heartbeat", value: "heartbeat" },
  { label: "Delegation", value: "delegation" },
  { label: "Harness", value: "harness" },
  { label: "Exec", value: "exec" },
  { label: "Callback", value: "callback" },
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
  { label: "Weekly", value: "+7d" },
];

// ---------------------------------------------------------------------------
// EnableToggle
// ---------------------------------------------------------------------------
function EnableToggle({ enabled, onChange, compact }: { enabled: boolean; onChange: (v: boolean) => void; compact?: boolean }) {
  return (
    <button
      onClick={() => onChange(!enabled)}
      title={enabled ? "Enabled" : "Disabled"}
      style={{
        display: "flex", alignItems: "center", gap: compact ? 0 : 6,
        padding: compact ? "5px 6px" : "5px 12px", fontSize: 12, fontWeight: 600,
        border: "none", cursor: "pointer", borderRadius: 6, flexShrink: 0,
        background: enabled ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
        color: enabled ? "#86efac" : "#fca5a5",
      }}
    >
      <div style={{
        width: 28, height: 16, borderRadius: 8, position: "relative",
        background: enabled ? "#22c55e" : "#555",
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
              background: !value ? "#3b82f6" : "#1a1a1a",
              color: !value ? "#fff" : "#888",
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
                background: value === p.value ? "#3b82f6" : "#1a1a1a",
                color: value === p.value ? "#fff" : "#888",
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
        <input
          type="datetime-local"
          value={isRelative ? "" : value}
          onChange={(e) => onChange(e.target.value)}
          style={{
            background: "#111", border: "1px solid #333", borderRadius: 8,
            padding: "7px 12px", color: "#e5e5e5", fontSize: 13,
            outline: "none", colorScheme: "dark",
          }}
        />
        {isRelative && (
          <div style={{ fontSize: 10, color: "#666" }}>
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
                background: value === p.value ? (p.value ? "#92400e" : "#333") : "#1a1a1a",
                color: value === p.value ? (p.value ? "#fcd34d" : "#e5e5e5") : "#888",
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
              background: showCustom ? "#92400e" : "#1a1a1a",
              color: showCustom ? "#fcd34d" : "#888",
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
              background: "#111", border: "1px solid #333", borderRadius: 8,
              padding: "7px 12px", color: "#e5e5e5", fontSize: 13, outline: "none",
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
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: "#666" }}>{label}</span>
      <span style={{ fontSize: 11, color: "#ccc", fontFamily: "monospace" }}>{value}</span>
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
  const [botId, setBotId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [status, setStatus] = useState("pending");
  const [taskType, setTaskType] = useState("scheduled");
  const [scheduledAt, setScheduledAt] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [triggerRagLoop, setTriggerRagLoop] = useState(false);
  const [modelOverride, setModelOverride] = useState("");
  const [initialized, setInitialized] = useState(false);

  // Populate form when existing task loads (edit mode)
  if (!isCreate && !cloneFromId && existingTask && !initialized) {
    setTitle(existingTask.title || "");
    setPrompt(existingTask.prompt || "");
    setPromptTemplateId(existingTask.prompt_template_id ?? null);
    setBotId(existingTask.bot_id || "");
    setChannelId(existingTask.channel_id || "");
    setStatus(existingTask.status || "pending");
    setTaskType(existingTask.task_type || "scheduled");
    setScheduledAt(existingTask.scheduled_at ? toLocalDatetimeString(new Date(existingTask.scheduled_at)) : "");
    setRecurrence(existingTask.recurrence || "");
    setTriggerRagLoop(existingTask.callback_config?.trigger_rag_loop ?? false);
    setModelOverride(existingTask.callback_config?.model_override || "");
    setInitialized(true);
  }

  // Populate form when cloning
  if (isCreate && cloneFromId && existingTask && !initialized) {
    setTitle(existingTask.title || "");
    setPrompt(existingTask.prompt || "");
    setPromptTemplateId(existingTask.prompt_template_id ?? null);
    setBotId(existingTask.bot_id || "");
    setChannelId(existingTask.channel_id || "");
    setTaskType(existingTask.task_type || "scheduled");
    setScheduledAt(existingTask.scheduled_at ? toLocalDatetimeString(new Date(existingTask.scheduled_at)) : "");
    setRecurrence(existingTask.recurrence || "");
    setTriggerRagLoop(existingTask.callback_config?.trigger_rag_loop ?? false);
    setModelOverride(existingTask.callback_config?.model_override || "");
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

  const handleSave = useCallback(async () => {
    if (!prompt.trim() || !botId) return;
    try {
      if (isCreate) {
        await createMut.mutateAsync({
          prompt,
          title: title || null,
          prompt_template_id: promptTemplateId,
          bot_id: botId,
          channel_id: channelId || null,
          scheduled_at: scheduledAt || null,
          recurrence: recurrence || null,
          task_type: taskType,
          trigger_rag_loop: triggerRagLoop,
          model_override: modelOverride || null,
        });
      } else {
        await updateMut.mutateAsync({
          prompt,
          title: title || null,
          prompt_template_id: promptTemplateId,
          bot_id: botId,
          status,
          scheduled_at: scheduledAt || null,
          recurrence: recurrence || null,
          task_type: taskType,
          trigger_rag_loop: triggerRagLoop,
          model_override: modelOverride || null,
        });
      }
      invalidateExtra();
      onSaved();
    } catch {
      // error is shown via mutation state
    }
  }, [prompt, title, botId, channelId, scheduledAt, recurrence, taskType, triggerRagLoop, modelOverride, status, isCreate, createMut, updateMut, onSaved, invalidateExtra, promptTemplateId]);

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

  const title = cloneFromId ? "New Task (Clone)" : isCreate ? "New Task" : "Edit Task";

  return ReactDOM.createPortal(
    <div style={{
      position: "fixed", inset: 0, zIndex: 10000,
      background: "#0a0a0a", display: "flex", flexDirection: "column",
    }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px", borderBottom: "1px solid #333", flexShrink: 0,
        gap: 8,
      }}>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0 }}
        >
          <ChevronLeft size={22} color="#999" />
        </button>

        <span style={{ color: "#e5e5e5", fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
          {title}
        </span>
        {cloneFromId && (
          <span style={{
            fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
            background: "#92400e", color: "#fcd34d",
          }}>
            CLONE
          </span>
        )}
        {!isCreate && existingTask && isWide && (
          <span style={{ color: "#555", fontSize: 11, fontFamily: "monospace" }}>
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
              border: "1px solid #1e3a5f", borderRadius: 6,
              background: "transparent", color: "#93c5fd", cursor: "pointer", flexShrink: 0,
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
              border: "1px solid #333", borderRadius: 6,
              background: "transparent", color: "#999", cursor: "pointer", flexShrink: 0,
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
              border: "1px solid #7f1d1d", borderRadius: 6,
              background: "transparent", color: "#fca5a5", cursor: "pointer", flexShrink: 0,
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
          disabled={saving || !prompt.trim() || !botId}
          style={{
            padding: isWide ? "6px 20px" : "6px 12px", fontSize: 13, fontWeight: 600,
            border: "none", borderRadius: 6, flexShrink: 0,
            background: (!prompt.trim() || !botId) ? "#333" : "#3b82f6",
            color: (!prompt.trim() || !botId) ? "#666" : "#fff",
            cursor: (!prompt.trim() || !botId) ? "not-allowed" : "pointer",
          }}
        >
          {saving ? "..." : isCreate ? "Create" : "Save"}
        </button>
      </div>

      {/* Error display */}
      {(createMut.error || updateMut.error || deleteMut.error) && (
        <div style={{ padding: "8px 20px", background: "#7f1d1d", color: "#fca5a5", fontSize: 12 }}>
          {(createMut.error || updateMut.error || deleteMut.error)?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      {(((!isCreate && !cloneFromId) || cloneFromId) && loadingTask) ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <ActivityIndicator color="#3b82f6" />
        </div>
      ) : (
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{
          ...(isWide ? { flexDirection: "row", flex: 1 } : {}),
        }}>
          {/* Prompt + Result/Error */}
          <div style={{
            ...(isWide ? { flex: 3, borderRight: "1px solid #2a2a2a" } : {}),
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
                    background: "#111", border: "1px solid #333", borderRadius: 8,
                    padding: "7px 12px", color: "#e5e5e5", fontSize: 13,
                    outline: "none", width: "100%",
                  }}
                />
              </FormRow>
              <PromptTemplateLink
                templateId={promptTemplateId}
                onLink={(id) => setPromptTemplateId(id)}
                onUnlink={() => setPromptTemplateId(null)}
                workspaceId={selectedBot?.shared_workspace_id ?? undefined}
              />
              <LlmPrompt
                value={prompt}
                onChange={setPrompt}
                label="Prompt"
                placeholder={promptTemplateId ? "Using linked template..." : "Task prompt... (type @ for autocomplete)"}
                rows={isWide ? 12 : 6}
              />

              {!isCreate && existingTask?.result && (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "#999", marginBottom: 6 }}>Result</div>
                  <div style={{
                    padding: 12, borderRadius: 8, background: "#111", border: "1px solid #1a1a1a",
                    fontSize: 12, color: "#86efac", whiteSpace: "pre-wrap",
                    maxHeight: 300, overflow: "auto", fontFamily: "monospace",
                  }}>
                    {existingTask.result}
                  </div>
                </div>
              )}

              {!isCreate && existingTask?.error && (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "#999", marginBottom: 6 }}>Error</div>
                  <div style={{
                    padding: 12, borderRadius: 8, background: "#1a0a0a", border: "1px solid #7f1d1d",
                    fontSize: 12, color: "#fca5a5", whiteSpace: "pre-wrap",
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
            borderTop: isWide ? "none" : "1px solid #2a2a2a",
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
              </Section>

              {/* Read-only timing info in edit mode */}
              {!isCreate && existingTask && (
                <Section title="Timing">
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <InfoRow label="Created" value={fmtDatetime(existingTask.created_at)} />
                    <InfoRow label="Scheduled" value={fmtDatetime(existingTask.scheduled_at)} />
                    <InfoRow label="Run At" value={fmtDatetime(existingTask.run_at)} />
                    <InfoRow label="Completed" value={fmtDatetime(existingTask.completed_at)} />
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
                    {existingTask.dispatch_config && (
                      <div>
                        <div style={{ fontSize: 11, color: "#666", marginBottom: 4 }}>Config</div>
                        <pre style={{
                          fontSize: 10, color: "#888", background: "#111", padding: 8,
                          borderRadius: 6, overflow: "auto", maxHeight: 120, margin: 0,
                        }}>
                          {JSON.stringify(existingTask.dispatch_config, null, 2)}
                        </pre>
                      </div>
                    )}
                    {existingTask.callback_config && (
                      <div>
                        <div style={{ fontSize: 11, color: "#666", marginBottom: 4 }}>Callback Config</div>
                        <pre style={{
                          fontSize: 10, color: "#888", background: "#111", padding: 8,
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
