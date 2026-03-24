import { useState, useMemo, useCallback } from "react";
import { View, Text, Pressable, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, ChevronRight, Plus, X, Trash2,
  Clock, AlertCircle, CheckCircle2, Loader2, RefreshCw, Calendar,
} from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useTask, useCreateTask, useUpdateTask, useDeleteTask, type TaskDetail } from "@/src/api/hooks/useTasks";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { FormRow, TextInput, SelectInput, Toggle, Section, Row, Col } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { MobileMenuButton } from "@/src/components/layout/MobileMenuButton";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";

interface TaskItem {
  id: string;
  status: string;
  bot_id: string;
  prompt: string;
  result?: string;
  error?: string;
  dispatch_type: string;
  task_type?: string;
  recurrence?: string;
  channel_id?: string;
  created_at?: string;
  scheduled_at?: string;
  run_at?: string;
  completed_at?: string;
}

interface TasksResponse {
  tasks: TaskItem[];
  total: number;
}

type ViewMode = "day" | "week";
type TaskTypeFilter = "all" | "scheduled" | "heartbeat" | "delegation" | "harness" | "exec" | "callback" | "api" | "recurrence";

const TASK_TYPE_FILTERS: { key: TaskTypeFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "scheduled", label: "Scheduled" },
  { key: "heartbeat", label: "Heartbeat" },
  { key: "delegation", label: "Delegation" },
  { key: "harness", label: "Harness" },
  { key: "exec", label: "Exec" },
  { key: "callback", label: "Callback" },
  { key: "api", label: "API" },
  { key: "recurrence", label: "Recurrence" },
];

const TYPE_BADGE_COLORS: Record<string, { bg: string; fg: string }> = {
  scheduled: { bg: "#1e3a5f", fg: "#93c5fd" },
  heartbeat: { bg: "#3b2e1a", fg: "#fbbf24" },
  delegation: { bg: "#2d1b4e", fg: "#c084fc" },
  harness: { bg: "#1a3333", fg: "#5eead4" },
  exec: { bg: "#333", fg: "#a3a3a3" },
  callback: { bg: "#2e1a1a", fg: "#f87171" },
  api: { bg: "#1a2e1a", fg: "#86efac" },
  recurrence: { bg: "#92400e", fg: "#fcd34d" },
  agent: { bg: "#222", fg: "#666" },
};

const STATUS_CFG: Record<string, { bg: string; fg: string; icon: any }> = {
  pending: { bg: "#333", fg: "#999", icon: Clock },
  running: { bg: "#1e3a5f", fg: "#93c5fd", icon: Loader2 },
  complete: { bg: "#166534", fg: "#86efac", icon: CheckCircle2 },
  failed: { bg: "#7f1d1d", fg: "#fca5a5", icon: AlertCircle },
};

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

function startOfDay(d: Date) {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}

function addDays(d: Date, n: number) {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function fmtDate(d: Date) {
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function fmtDatetime(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function getTaskTime(t: TaskItem): Date {
  return new Date(t.scheduled_at || t.created_at || Date.now());
}

function isToday(d: Date) {
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

// ---------------------------------------------------------------------------
// Current time indicator line
// ---------------------------------------------------------------------------
function NowLine() {
  const now = new Date();
  const minutesSinceMidnight = now.getHours() * 60 + now.getMinutes();
  const pct = (minutesSinceMidnight / 1440) * 100;
  return (
    <div style={{
      position: "absolute", left: 0, right: 0, top: `${pct}%`,
      display: "flex", alignItems: "center", zIndex: 5, pointerEvents: "none",
    }}>
      <div style={{ width: 8, height: 8, borderRadius: 4, background: "#ef4444", marginLeft: -4 }} />
      <div style={{ flex: 1, height: 1, background: "#ef4444" }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hour labels
// ---------------------------------------------------------------------------
function HourLabels() {
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => {
        const pct = (h / 24) * 100;
        return (
          <div key={h} style={{
            position: "absolute", left: 0, top: `${pct}%`,
            fontSize: 10, color: "#444", width: 40, textAlign: "right", paddingRight: 8,
            transform: "translateY(-50%)",
          }}>
            {h === 0 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h - 12} PM`}
          </div>
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Hour grid lines
// ---------------------------------------------------------------------------
function HourGrid() {
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => (
        <div key={h} style={{
          position: "absolute", left: 48, right: 0,
          top: `${(h / 24) * 100}%`,
          borderTop: "1px solid #1a1a1a",
        }} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Task type badge
// ---------------------------------------------------------------------------
function TypeBadge({ type }: { type: string }) {
  const c = TYPE_BADGE_COLORS[type] || TYPE_BADGE_COLORS.agent;
  return (
    <span style={{
      display: "inline-block",
      background: c.bg, color: c.fg,
      padding: "1px 6px", borderRadius: 4, fontSize: 9, fontWeight: 600,
      textTransform: "uppercase", letterSpacing: 0.5,
    }}>
      {type}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Task card on timeline
// ---------------------------------------------------------------------------
function TaskCard({ task, isPast, onPress }: { task: TaskItem; isPast: boolean; onPress: () => void }) {
  const s = STATUS_CFG[task.status] || STATUS_CFG.pending;
  const Icon = s.icon;
  const isRecurring = !!task.recurrence;
  const time = task.scheduled_at || task.created_at;

  return (
    <div
      onClick={onPress}
      style={{
        padding: "8px 12px", borderRadius: 8,
        background: isPast ? "#111" : "#1a1a1a",
        border: `1px solid ${isPast ? "#1a1a1a" : "#2a2a2a"}`,
        opacity: isPast ? 0.5 : 1,
        transition: "opacity 0.2s",
        marginBottom: 4,
        cursor: "pointer",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon size={13} color={s.fg} />
        <span style={{ fontSize: 12, fontWeight: 600, color: s.fg }}>{task.status}</span>

        {task.task_type && <TypeBadge type={task.task_type} />}

        {isRecurring && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            background: "#92400e", color: "#fcd34d",
            padding: "1px 7px", borderRadius: 10, fontSize: 10, fontWeight: 700,
          }}>
            <RefreshCw size={9} color="#fcd34d" />
            {task.recurrence}
          </span>
        )}

        <span style={{ fontSize: 11, color: "#555", marginLeft: "auto" }}>
          {time ? fmtTime(time) : "\u2014"}
        </span>
      </div>

      <div style={{ fontSize: 11, color: "#999", marginTop: 4, fontFamily: "monospace" }}>
        {task.bot_id}
      </div>
      {task.prompt && (
        <div style={{
          fontSize: 11, color: isPast ? "#555" : "#888", marginTop: 4,
          whiteSpace: "pre-wrap", maxHeight: 40, overflow: "hidden",
        }}>
          {task.prompt.substring(0, 150)}{task.prompt.length > 150 ? "..." : ""}
        </div>
      )}
      {task.error && (
        <div style={{ fontSize: 10, color: "#fca5a5", marginTop: 4 }}>
          {task.error.substring(0, 100)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Day column
// ---------------------------------------------------------------------------
function DayColumn({ date, tasks, onTaskPress }: { date: Date; tasks: TaskItem[]; onTaskPress: (t: TaskItem) => void }) {
  const now = new Date();
  const showNow = isToday(date);

  // Group tasks by hour
  const hourGroups = useMemo(() => {
    const groups: Record<number, TaskItem[]> = {};
    for (const t of tasks) {
      const taskTime = getTaskTime(t);
      const hour = taskTime.getHours();
      (groups[hour] ??= []).push(t);
    }
    return groups;
  }, [tasks]);

  return (
    <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
      {/* Day header */}
      <div style={{
        padding: "8px 12px", borderBottom: "1px solid #2a2a2a",
        background: showNow ? "rgba(59,130,246,0.08)" : "transparent",
        position: "sticky", top: 0, zIndex: 3,
      }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: showNow ? "#3b82f6" : "#e5e5e5" }}>
          {fmtDate(date)}
        </div>
        <div style={{ fontSize: 10, color: "#555" }}>
          {tasks.length} task{tasks.length !== 1 ? "s" : ""}
        </div>
      </div>

      {/* Timeline body */}
      <div style={{ position: "relative", height: 1440, paddingLeft: 48 }}>
        <HourGrid />
        <HourLabels />
        {showNow && <NowLine />}

        {/* Render tasks at their time positions */}
        {Object.entries(hourGroups).map(([hourStr, hTasks]) => {
          const hour = Number(hourStr);
          const pct = (hour / 24) * 100;
          return (
            <div key={hour} style={{
              position: "absolute", left: 52, right: 8, top: `${pct}%`,
              zIndex: 2,
            }}>
              {hTasks.map((t) => (
                <TaskCard
                  key={t.id}
                  task={t}
                  isPast={getTaskTime(t) < now && t.status !== "running"}
                  onPress={() => onTaskPress(t)}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Enable/disable toggle for header bar
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
// Task Editor (near-fullscreen overlay)
// ---------------------------------------------------------------------------
function TaskEditor({
  taskId,
  onClose,
  onSaved,
}: {
  taskId: string | null; // null = create mode
  onClose: () => void;
  onSaved: () => void;
}) {
  const isCreate = !taskId;
  const { data: existingTask, isLoading: loadingTask } = useTask(taskId ?? undefined);
  const createMut = useCreateTask();
  const updateMut = useUpdateTask(taskId ?? undefined);
  const deleteMut = useDeleteTask();
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const { width: winWidth } = useWindowDimensions();
  const isWide = winWidth >= 768;

  // Form state
  const [prompt, setPrompt] = useState("");
  const [botId, setBotId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [status, setStatus] = useState("pending");
  const [taskType, setTaskType] = useState("scheduled");
  const [scheduledAt, setScheduledAt] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [triggerRagLoop, setTriggerRagLoop] = useState(false);
  const [modelOverride, setModelOverride] = useState("");
  const [initialized, setInitialized] = useState(false);

  // Populate form when existing task loads
  if (!isCreate && existingTask && !initialized) {
    setPrompt(existingTask.prompt || "");
    setBotId(existingTask.bot_id || "");
    setChannelId(existingTask.channel_id || "");
    setStatus(existingTask.status || "pending");
    setTaskType(existingTask.task_type || "scheduled");
    setScheduledAt(existingTask.scheduled_at ? new Date(existingTask.scheduled_at).toISOString().slice(0, 16) : "");
    setRecurrence(existingTask.recurrence || "");
    setTriggerRagLoop(existingTask.callback_config?.trigger_rag_loop ?? false);
    setModelOverride(existingTask.callback_config?.model_override || "");
    setInitialized(true);
  }

  // Set defaults for create mode
  if (isCreate && !initialized && bots && bots.length > 0) {
    setBotId(bots[0].id);
    setInitialized(true);
  }

  const saving = createMut.isPending || updateMut.isPending;

  const handleSave = useCallback(async () => {
    if (!prompt.trim() || !botId) return;
    try {
      if (isCreate) {
        await createMut.mutateAsync({
          prompt,
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
          bot_id: botId,
          status,
          scheduled_at: scheduledAt || null,
          recurrence: recurrence || null,
          task_type: taskType,
          trigger_rag_loop: triggerRagLoop,
          model_override: modelOverride || null,
        });
      }
      onSaved();
    } catch {
      // error is shown via mutation state
    }
  }, [prompt, botId, channelId, scheduledAt, recurrence, taskType, triggerRagLoop, modelOverride, status, isCreate, createMut, updateMut, onSaved]);

  const handleDelete = useCallback(async () => {
    if (!taskId || !confirm("Delete this task?")) return;
    await deleteMut.mutateAsync(taskId);
    onSaved();
  }, [taskId, deleteMut, onSaved]);

  if (typeof document === "undefined") return null;
  const ReactDOM = require("react-dom");

  const botOptions = (bots || []).map((b) => ({ label: b.name || b.id, value: b.id }));
  const channelOptions = [
    { label: "\u2014 None \u2014", value: "" },
    ...(channels || []).map((c: any) => ({
      label: c.display_name || c.name || c.id,
      value: String(c.id),
    })),
  ];

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
        {/* Back / close button */}
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0 }}
        >
          <ChevronLeft size={22} color="#999" />
        </button>

        {/* Title */}
        <span style={{ color: "#e5e5e5", fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
          {isCreate ? "New Task" : "Edit Task"}
        </span>
        {!isCreate && existingTask && isWide && (
          <span style={{ color: "#555", fontSize: 11, fontFamily: "monospace" }}>
            {taskId?.slice(0, 8)}
          </span>
        )}

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Actions */}
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
            onChange={(on) => setStatus(on ? "pending" : "cancelled")}
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
      {(!isCreate && loadingTask) ? (
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
              <LlmPrompt
                value={prompt}
                onChange={setPrompt}
                label="Prompt"
                placeholder="Task prompt... (type @ for autocomplete)"
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

              {/* Read-only timing info in edit mode */}
              {!isCreate && existingTask && (
                <Section title="Timing">
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <InfoRow label="Created" value={fmtDatetime(existingTask.created_at)} />
                    <InfoRow label="Scheduled" value={fmtDatetime(existingTask.scheduled_at)} />
                    <InfoRow label="Run At" value={fmtDatetime(existingTask.run_at)} />
                    <InfoRow label="Completed" value={fmtDatetime(existingTask.completed_at)} />
                    <InfoRow label="Retry Count" value={String(existingTask.retry_count)} />
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

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: "#666" }}>{label}</span>
      <span style={{ fontSize: 11, color: "#ccc", fontFamily: "monospace" }}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Tasks screen
// ---------------------------------------------------------------------------
export default function TasksScreen() {
  const [viewMode, setViewMode] = useState<ViewMode>("day");
  const [baseDate, setBaseDate] = useState(() => startOfDay(new Date()));
  const [typeFilter, setTypeFilter] = useState<TaskTypeFilter>("scheduled");
  const [editorTaskId, setEditorTaskId] = useState<string | null | undefined>(undefined); // undefined=closed, null=create, string=edit
  const qc = useQueryClient();
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";

  const rangeDays = viewMode === "day" ? 1 : 7;
  const rangeStart = baseDate;
  const rangeEnd = addDays(baseDate, rangeDays);

  const typeParam = typeFilter !== "all" ? `&task_type=${typeFilter}` : "";

  const { data, isLoading } = useQuery({
    queryKey: ["admin-tasks-timeline", rangeStart.toISOString(), rangeEnd.toISOString(), typeFilter],
    queryFn: () => apiFetch<TasksResponse>(
      `/api/v1/admin/tasks?after=${rangeStart.toISOString()}&before=${rangeEnd.toISOString()}&limit=200${typeParam}`
    ),
  });

  const tasksByDay = useMemo(() => {
    const map: Record<string, TaskItem[]> = {};
    for (let i = 0; i < rangeDays; i++) {
      const d = addDays(baseDate, i);
      map[d.toDateString()] = [];
    }
    for (const t of data?.tasks ?? []) {
      const d = startOfDay(getTaskTime(t)).toDateString();
      (map[d] ??= []).push(t);
    }
    return map;
  }, [data, baseDate, rangeDays]);

  const goToday = () => setBaseDate(startOfDay(new Date()));
  const goPrev = () => setBaseDate(addDays(baseDate, -rangeDays));
  const goNext = () => setBaseDate(addDays(baseDate, rangeDays));

  const handleEditorClose = () => setEditorTaskId(undefined);
  const handleEditorSaved = () => {
    setEditorTaskId(undefined);
    qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
  };

  return (
    <View className="flex-1 bg-surface">
      {/* Header bar */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: isMobile ? "10px 12px" : "12px 20px", borderBottom: "1px solid #2a2a2a",
        gap: 8, flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <MobileMenuButton />
          <Calendar size={16} color="#3b82f6" />
          {!isMobile && (
            <span style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Tasks</span>
          )}
          <span style={{ fontSize: 11, color: "#555" }}>
            {data ? `${data.total}` : ""}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {/* New Task */}
          <button
            onClick={() => setEditorTaskId(null)}
            title="New Task"
            style={{
              display: "flex", alignItems: "center", gap: isMobile ? 0 : 6,
              padding: isMobile ? "5px 8px" : "5px 14px", fontSize: 12, fontWeight: 600,
              border: "none", cursor: "pointer", borderRadius: 6, background: "#3b82f6", color: "#fff",
            }}
          >
            <Plus size={14} />
            {!isMobile && "New Task"}
          </button>

          {/* View mode toggle */}
          <div style={{ display: "flex", background: "#1a1a1a", borderRadius: 6, overflow: "hidden" }}>
            {(["day", "week"] as ViewMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setViewMode(m)}
                style={{
                  padding: isMobile ? "5px 10px" : "5px 14px", fontSize: 11, fontWeight: 500,
                  border: "none", cursor: "pointer",
                  background: viewMode === m ? "#3b82f6" : "transparent",
                  color: viewMode === m ? "#fff" : "#999",
                  textTransform: "capitalize",
                }}
              >
                {isMobile ? m[0].toUpperCase() : m}
              </button>
            ))}
          </div>

          {/* Navigation */}
          <button onClick={goToday} style={{
            padding: "5px 8px", fontSize: 11, border: "1px solid #333", borderRadius: 6,
            background: "transparent", color: "#999", cursor: "pointer",
          }}>
            Today
          </button>
          <button onClick={goPrev} style={{ background: "none", border: "none", cursor: "pointer", padding: 2 }}>
            <ChevronLeft size={16} color="#999" />
          </button>
          <span style={{ fontSize: 12, color: "#e5e5e5", fontWeight: 500, textAlign: "center" }}>
            {viewMode === "day"
              ? fmtDate(baseDate)
              : isMobile
                ? fmtDate(baseDate)
                : `${fmtDate(baseDate)} \u2014 ${fmtDate(addDays(baseDate, 6))}`}
          </span>
          <button onClick={goNext} style={{ background: "none", border: "none", cursor: "pointer", padding: 2 }}>
            <ChevronRight size={16} color="#999" />
          </button>
        </div>
      </div>

      {/* Type filter pills */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "8px 20px", borderBottom: "1px solid #1a1a1a",
        overflowX: "auto",
      }}>
        {TASK_TYPE_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setTypeFilter(f.key)}
            style={{
              padding: "4px 12px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
              borderRadius: 12,
              background: typeFilter === f.key ? "#3b82f6" : "#1a1a1a",
              color: typeFilter === f.key ? "#fff" : "#888",
              whiteSpace: "nowrap",
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Timeline body */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <ScrollView className="flex-1" contentContainerStyle={{ minHeight: 1500 }}>
          <div style={{
            display: "flex", flex: 1, minHeight: 1500,
            borderLeft: "1px solid #2a2a2a",
          }}>
            {Object.entries(tasksByDay).map(([dayStr, tasks]) => (
              <DayColumn
                key={dayStr}
                date={new Date(dayStr)}
                tasks={tasks}
                onTaskPress={(t) => setEditorTaskId(t.id)}
              />
            ))}
          </div>
        </ScrollView>
      )}

      {/* Task Editor overlay */}
      {editorTaskId !== undefined && (
        <TaskEditor
          taskId={editorTaskId}
          onClose={handleEditorClose}
          onSaved={handleEditorSaved}
        />
      )}
    </View>
  );
}
