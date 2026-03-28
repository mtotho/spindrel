import { useState } from "react";
import { ActivityIndicator } from "react-native";
import { Plus } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section, EmptyState } from "@/src/components/shared/FormControls";
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

  const statusColors: Record<string, { bg: string; fg: string }> = {
    pending: { bg: t.surfaceBorder, fg: t.textMuted },
    running: { bg: "#1e3a5f", fg: "#93c5fd" },
    complete: { bg: "#166534", fg: "#86efac" },
    failed: { bg: "#7f1d1d", fg: "#fca5a5" },
    active: { bg: "#92400e", fg: "#fcd34d" },
    cancelled: { bg: t.surfaceBorder, fg: t.textDim },
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
        <button
          onClick={() => setEditorState({ mode: "create" })}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "4px 12px", fontSize: 11, fontWeight: 600,
            border: "none", cursor: "pointer", borderRadius: 6,
            background: t.accent, color: "#fff",
          }}
        >
          <Plus size={12} />
          New Task
        </button>
      }>
        {isLoading ? (
          <ActivityIndicator color={t.accent} />
        ) : !tasks.length ? (
          <EmptyState message="No tasks yet." />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {tasks.map((task: any) => {
              const sc = statusColors[task.status] || statusColors.pending;
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
                      {task.dispatch_type || "none"} \u00b7 {new Date(task.created_at).toLocaleString()}
                    </div>
                    {task.prompt && (
                      <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4, maxWidth: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {task.prompt.substring(0, 100)}
                      </div>
                    )}
                  </div>
                  <span style={{
                    fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
                    background: sc.bg, color: sc.fg,
                  }}>
                    {task.status}
                  </span>
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
