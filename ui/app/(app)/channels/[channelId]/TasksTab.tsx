import { useState } from "react";
import { ActivityIndicator } from "react-native";
import { Plus } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section, EmptyState } from "@/src/components/shared/FormControls";
import { ActionButton, StatusBadge } from "@/src/components/shared/SettingsControls";
import { TaskEditor as TaskEditorShared } from "@/src/components/shared/TaskEditor";
import { apiFetch } from "@/src/api/client";
import { useQuery, useQueryClient } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Tasks Tab
// ---------------------------------------------------------------------------
export function TasksTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const t = useThemeTokens();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-tasks", channelId],
    queryFn: () => apiFetch<{ tasks: any[] }>(`/api/v1/admin/channels/${channelId}/tasks`),
  });
  const tasks = data?.tasks ?? [];

  type EditorState =
    | { mode: "closed" }
    | { mode: "create" }
    | { mode: "edit"; taskId: string };

  const [editorState, setEditorState] = useState<EditorState>({ mode: "closed" });

  const statusVariants: Record<string, "neutral" | "info" | "success" | "danger" | "warning"> = {
    pending: "neutral",
    running: "info",
    complete: "success",
    failed: "danger",
    active: "warning",
    cancelled: "neutral",
  };

  const handleEditorSaved = () => {
    setEditorState({ mode: "closed" });
    queryClient.invalidateQueries({ queryKey: ["channel-tasks", channelId] });
  };

  const editorOpen = editorState.mode !== "closed";
  const editorTaskId = editorState.mode === "edit" ? editorState.taskId : null;

  return (
    <>
      <Section title={`Tasks (${tasks.length})`} action={
        <ActionButton
          label="New Task"
          onPress={() => setEditorState({ mode: "create" })}
          size="small"
          icon={<Plus size={12} />}
        />
      }>
        {isLoading ? (
          <ActivityIndicator color={t.accent} />
        ) : !tasks.length ? (
          <EmptyState message="No tasks yet." />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {tasks.map((task: any) => {
              const sv = statusVariants[task.status] || "neutral";
              return (
                <div
                  key={task.id}
                  onClick={() => setEditorState({ mode: "edit", taskId: task.id })}
                  style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "10px 12px", background: t.surfaceRaised, borderRadius: 8, border: `1px solid ${t.surfaceOverlay}`,
                    cursor: "pointer",
                  }}
                >
                  <div>
                    <div style={{ fontSize: 12, color: t.text, fontFamily: "monospace" }}>
                      {task.id?.substring(0, 12)}...
                    </div>
                    <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>
                      {task.dispatch_type || "none"} {"\u00b7"} {new Date(task.created_at).toLocaleString()}
                    </div>
                    {task.prompt && (
                      <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4, maxWidth: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {task.prompt.substring(0, 100)}
                      </div>
                    )}
                  </div>
                  <StatusBadge label={task.status} variant={sv} />
                </div>
              );
            })}
          </div>
        )}
      </Section>

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
