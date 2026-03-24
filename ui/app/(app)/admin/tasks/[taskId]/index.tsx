import { useCallback } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import { useTask, useUpdateTask, useDeleteTask } from "@/src/api/hooks/useTasks";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useState } from "react";
import { X, Trash2 } from "lucide-react";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { FormRow, TextInput, SelectInput, Toggle, Section } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";

const STATUS_OPTIONS = [
  { label: "Pending", value: "pending" },
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

function fmtDatetime(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: "#666" }}>{label}</span>
      <span style={{ fontSize: 11, color: "#ccc", fontFamily: "monospace" }}>{value}</span>
    </div>
  );
}

function EnableToggle({ enabled, onChange }: { enabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!enabled)}
      style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "5px 12px", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer",
        borderRadius: 6,
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
      {enabled ? "Enabled" : "Disabled"}
    </button>
  );
}

export default function TaskDetailScreen() {
  const { taskId } = useLocalSearchParams<{ taskId: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: task, isLoading } = useTask(taskId);
  const updateMut = useUpdateTask(taskId);
  const deleteMut = useDeleteTask();
  const { data: bots } = useBots();
  const { data: channels } = useChannels();

  const { width: winWidth } = useWindowDimensions();
  const isWide = winWidth >= 768;

  const [prompt, setPrompt] = useState("");
  const [botId, setBotId] = useState("");
  const [status, setStatus] = useState("pending");
  const [taskType, setTaskType] = useState("scheduled");
  const [scheduledAt, setScheduledAt] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [triggerRagLoop, setTriggerRagLoop] = useState(false);
  const [modelOverride, setModelOverride] = useState("");
  const [initialized, setInitialized] = useState(false);

  if (task && !initialized) {
    setPrompt(task.prompt || "");
    setBotId(task.bot_id || "");
    setStatus(task.status || "pending");
    setTaskType(task.task_type || "scheduled");
    setScheduledAt(task.scheduled_at ? new Date(task.scheduled_at).toISOString().slice(0, 16) : "");
    setRecurrence(task.recurrence || "");
    setTriggerRagLoop(task.callback_config?.trigger_rag_loop ?? false);
    setModelOverride(task.callback_config?.model_override || "");
    setInitialized(true);
  }

  const handleSave = useCallback(async () => {
    if (!prompt.trim() || !botId) return;
    await updateMut.mutateAsync({
      prompt,
      bot_id: botId,
      status,
      scheduled_at: scheduledAt || null,
      recurrence: recurrence || null,
      task_type: taskType,
      trigger_rag_loop: triggerRagLoop,
      model_override: modelOverride || null,
    });
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
  }, [prompt, botId, status, scheduledAt, recurrence, taskType, triggerRagLoop, modelOverride, updateMut, qc]);

  const handleDelete = useCallback(async () => {
    if (!taskId || !confirm("Delete this task?")) return;
    await deleteMut.mutateAsync(taskId);
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
    router.back();
  }, [taskId, deleteMut, qc, router]);

  const goBack = () => router.back();

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
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "12px 20px", borderBottom: "1px solid #333", flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ color: "#e5e5e5", fontSize: 16, fontWeight: 700 }}>Edit Task</span>
          <span style={{ color: "#555", fontSize: 12, fontFamily: "monospace" }}>
            {taskId?.slice(0, 8)}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={handleDelete}
            disabled={deleteMut.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 13, border: "1px solid #7f1d1d", borderRadius: 6,
              background: "transparent", color: "#fca5a5", cursor: "pointer",
            }}
          >
            <Trash2 size={14} />
            Delete
          </button>
          <EnableToggle
            enabled={status !== "cancelled"}
            onChange={(on) => setStatus(on ? "pending" : "cancelled")}
          />
          <button
            onClick={handleSave}
            disabled={updateMut.isPending || !prompt.trim() || !botId}
            style={{
              padding: "6px 20px", fontSize: 13, fontWeight: 600, border: "none", borderRadius: 6,
              background: (!prompt.trim() || !botId) ? "#333" : "#3b82f6",
              color: (!prompt.trim() || !botId) ? "#666" : "#fff",
              cursor: (!prompt.trim() || !botId) ? "not-allowed" : "pointer",
            }}
          >
            {updateMut.isPending ? "Saving..." : "Save"}
          </button>
          <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 4 }}>
            <X size={20} color="#999" />
          </button>
        </div>
      </div>

      {/* Error display */}
      {(updateMut.error || deleteMut.error) && (
        <div style={{ padding: "8px 20px", background: "#7f1d1d", color: "#fca5a5", fontSize: 12 }}>
          {(updateMut.error || deleteMut.error)?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        ...(isWide ? { flexDirection: "row", flex: 1 } : {}),
      }}>
        {/* Prompt + Result/Error */}
        <div style={{
          ...(isWide ? { flex: 3, borderRight: "1px solid #2a2a2a" } : {}),
          display: "flex", flexDirection: "column",
        }}>
          <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 16 }}>
            <LlmPrompt
              value={prompt}
              onChange={setPrompt}
              label="Prompt"
              placeholder="Task prompt..."
              rows={isWide ? 12 : 6}
            />

            {task?.result && (
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#999", marginBottom: 6 }}>Result</div>
                <div style={{
                  padding: 12, borderRadius: 8, background: "#111", border: "1px solid #1a1a1a",
                  fontSize: 12, color: "#86efac", whiteSpace: "pre-wrap",
                  maxHeight: 300, overflow: "auto", fontFamily: "monospace",
                }}>
                  {task.result}
                </div>
              </div>
            )}

            {task?.error && (
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#999", marginBottom: 6 }}>Error</div>
                <div style={{
                  padding: 12, borderRadius: 8, background: "#1a0a0a", border: "1px solid #7f1d1d",
                  fontSize: 12, color: "#fca5a5", whiteSpace: "pre-wrap",
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
          borderTop: isWide ? "none" : "1px solid #2a2a2a",
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
              <FormRow label="Scheduled At" description="ISO datetime or +30m, +2h, +1d">
                <TextInput
                  value={scheduledAt}
                  onChangeText={setScheduledAt}
                  placeholder="e.g. +2h or 2026-03-25T10:00"
                />
              </FormRow>

              <FormRow label="Recurrence" description="Repeat interval: +1h, +1d, etc.">
                <TextInput
                  value={recurrence}
                  onChangeText={setRecurrence}
                  placeholder="e.g. +1h, +1d"
                />
              </FormRow>
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
                </div>
              </Section>
            )}

            {task && (
              <Section title="Dispatch">
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <InfoRow label="Type" value={task.dispatch_type} />
                  {task.dispatch_config && (
                    <div>
                      <div style={{ fontSize: 11, color: "#666", marginBottom: 4 }}>Config</div>
                      <pre style={{
                        fontSize: 10, color: "#888", background: "#111", padding: 8,
                        borderRadius: 6, overflow: "auto", maxHeight: 120, margin: 0,
                      }}>
                        {JSON.stringify(task.dispatch_config, null, 2)}
                      </pre>
                    </div>
                  )}
                  {task.callback_config && (
                    <div>
                      <div style={{ fontSize: 11, color: "#666", marginBottom: 4 }}>Callback Config</div>
                      <pre style={{
                        fontSize: 10, color: "#888", background: "#111", padding: 8,
                        borderRadius: 6, overflow: "auto", maxHeight: 120, margin: 0,
                      }}>
                        {JSON.stringify(task.callback_config, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              </Section>
            )}
          </div>
        </div>
      </ScrollView>
    </View>
  );
}
