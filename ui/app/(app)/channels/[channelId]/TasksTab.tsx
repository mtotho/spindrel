import { useState, useMemo } from "react";
import { ActivityIndicator } from "react-native";
import { Plus } from "lucide-react";
import { useRouter } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";
import { EmptyState } from "@/src/components/shared/FormControls";
import { ActionButton } from "@/src/components/shared/SettingsControls";
import { TaskEditor as TaskEditorShared } from "@/src/components/shared/TaskEditor";
import { TaskCardRow } from "@/src/components/shared/TaskCardRow";
import type { TaskItem } from "@/src/components/shared/TaskConstants";
import { apiFetch } from "@/src/api/client";
import { useQuery, useQueryClient } from "@tanstack/react-query";

// Task types that users create and can edit inline
const EDITABLE_TASK_TYPES = new Set(["scheduled", "agent"]);

type StatusFilter = "all" | "active" | "failed";

const STATUS_PILL_KEYS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "failed", label: "Failed" },
];

export function TasksTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const t = useThemeTokens();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-tasks", channelId],
    queryFn: () => apiFetch<{ tasks: TaskItem[] }>(`/api/v1/admin/channels/${channelId}/tasks`),
  });
  const allTasks = data?.tasks ?? [];

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const tasks = useMemo(() => {
    if (statusFilter === "all") return allTasks;
    if (statusFilter === "active") return allTasks.filter(tk => ["pending", "running", "active"].includes(tk.status));
    if (statusFilter === "failed") return allTasks.filter(tk => tk.status === "failed");
    return allTasks;
  }, [allTasks, statusFilter]);

  // Counts for filter pill badges
  const activeCt = useMemo(() => allTasks.filter(tk => ["pending", "running", "active"].includes(tk.status)).length, [allTasks]);
  const failedCt = useMemo(() => allTasks.filter(tk => tk.status === "failed").length, [allTasks]);

  type EditorState =
    | { mode: "closed" }
    | { mode: "create" }
    | { mode: "edit"; taskId: string };

  const [editorState, setEditorState] = useState<EditorState>({ mode: "closed" });

  const handleEditorSaved = () => {
    setEditorState({ mode: "closed" });
    queryClient.invalidateQueries({ queryKey: ["channel-tasks", channelId] });
  };

  const editorOpen = editorState.mode !== "closed";
  const editorTaskId = editorState.mode === "edit" ? editorState.taskId : null;

  return (
    <>
      {/* Header: filter pills + new task button */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 12, flexWrap: "wrap", gap: 8,
      }}>
        <div style={{ display: "flex", gap: 4 }}>
          {STATUS_PILL_KEYS.map((pill) => {
            const ct = pill.key === "all" ? allTasks.length : pill.key === "active" ? activeCt : failedCt;
            const active = statusFilter === pill.key;
            return (
              <button
                key={pill.key}
                onClick={() => setStatusFilter(pill.key)}
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "4px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600,
                  border: `1px solid ${active ? t.accent : t.surfaceBorder}`,
                  background: active ? t.accentMuted : t.surfaceRaised,
                  color: active ? t.accent : t.textMuted,
                  cursor: "pointer",
                }}
              >
                {pill.label}
                {ct > 0 && (
                  <span style={{
                    fontSize: 10, fontWeight: 700,
                    background: active ? t.accent : t.surfaceBorder,
                    color: active ? t.accentMuted : t.textDim,
                    padding: "0 5px", borderRadius: 8, minWidth: 18, textAlign: "center",
                  }}>{ct}</span>
                )}
              </button>
            );
          })}
        </div>
        <ActionButton
          label="New Task"
          onPress={() => setEditorState({ mode: "create" })}
          size="small"
          icon={<Plus size={12} />}
        />
      </div>

      {/* Task list */}
      {isLoading ? (
        <ActivityIndicator color={t.accent} />
      ) : !tasks.length ? (
        <EmptyState message={statusFilter === "all" ? "No tasks yet." : `No ${statusFilter} tasks.`} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {tasks.map((task) => (
            <TaskCardRow
              key={task.id}
              task={task}
              onPress={() => {
                if (EDITABLE_TASK_TYPES.has(task.task_type ?? "")) {
                  setEditorState({ mode: "edit", taskId: task.id });
                } else {
                  router.push(`/admin/tasks/${task.id}`);
                }
              }}
              showBotDot={false}
              showBotName={false}
            />
          ))}
        </div>
      )}

      {editorOpen && (
        <TaskEditorShared
          taskId={editorTaskId}
          onClose={() => setEditorState({ mode: "closed" })}
          onSaved={handleEditorSaved}
          defaultChannelId={channelId}
          defaultBotId={botId}
          extraQueryKeysToInvalidate={[["channel-tasks", channelId]]}
        />
      )}
    </>
  );
}
