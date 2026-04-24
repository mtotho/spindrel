import { useState, useMemo } from "react";
import type { ReactNode } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { EmptyState } from "@/src/components/shared/FormControls";
import { ActionButton, SettingsSegmentedControl } from "@/src/components/shared/SettingsControls";
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

const ACTIVE_STATUSES = new Set(["pending", "running", "active"]);

function TaskGroup({
  label,
  count,
  children,
}: {
  label: string;
  count: number;
  children: ReactNode;
}) {
  if (count === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
          {label}
        </span>
        <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] font-semibold text-text-dim">
          {count}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">{children}</div>
    </div>
  );
}

export function TasksTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-tasks", channelId],
    queryFn: () => apiFetch<{ tasks: TaskItem[] }>(`/api/v1/admin/channels/${channelId}/tasks`),
  });
  const allTasks = data?.tasks ?? [];

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const tasks = useMemo(() => {
    if (statusFilter === "all") return allTasks;
    if (statusFilter === "active") return allTasks.filter(tk => ACTIVE_STATUSES.has(tk.status));
    if (statusFilter === "failed") return allTasks.filter(tk => tk.status === "failed");
    return allTasks;
  }, [allTasks, statusFilter]);

  // Counts for filter pill badges
  const activeCt = useMemo(() => allTasks.filter(tk => ACTIVE_STATUSES.has(tk.status)).length, [allTasks]);
  const failedCt = useMemo(() => allTasks.filter(tk => tk.status === "failed").length, [allTasks]);
  const otherTasks = useMemo(
    () => allTasks.filter((tk) => !ACTIVE_STATUSES.has(tk.status) && tk.status !== "failed"),
    [allTasks],
  );

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
  const renderTask = (task: TaskItem) => (
    <TaskCardRow
      key={task.id}
      task={task}
      onClick={() => {
        if (EDITABLE_TASK_TYPES.has(task.task_type ?? "")) {
          setEditorState({ mode: "edit", taskId: task.id });
        } else {
          navigate(`/admin/tasks/${task.id}`);
        }
      }}
      showBotDot={false}
      showBotName={false}
    />
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SettingsSegmentedControl
          value={statusFilter}
          onChange={setStatusFilter}
          options={STATUS_PILL_KEYS.map((pill) => ({
            key: pill.key,
            label: pill.label,
            count: pill.key === "all" ? allTasks.length : pill.key === "active" ? activeCt : failedCt,
          }))}
        />
        <ActionButton
          label="New Task"
          onPress={() => setEditorState({ mode: "create" })}
          size="small"
          icon={<Plus size={12} />}
        />
      </div>

      {isLoading ? (
        <div className="flex min-h-24 items-center justify-center text-text-dim">
          <Spinner />
        </div>
      ) : !tasks.length ? (
        <EmptyState message={statusFilter === "all" ? "No tasks yet." : `No ${statusFilter} tasks.`} />
      ) : statusFilter === "all" ? (
        <div className="flex flex-col gap-5">
          <TaskGroup label="Needs attention" count={failedCt}>
            {allTasks.filter((task) => task.status === "failed").map(renderTask)}
          </TaskGroup>
          <TaskGroup label="Active" count={activeCt}>
            {allTasks.filter((task) => ACTIVE_STATUSES.has(task.status)).map(renderTask)}
          </TaskGroup>
          <TaskGroup label="Other tasks" count={otherTasks.length}>
            {otherTasks.map(renderTask)}
          </TaskGroup>
        </div>
      ) : (
        <TaskGroup label={statusFilter === "active" ? "Active tasks" : "Failed tasks"} count={tasks.length}>
          {tasks.map(renderTask)}
        </TaskGroup>
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
    </div>
  );
}
