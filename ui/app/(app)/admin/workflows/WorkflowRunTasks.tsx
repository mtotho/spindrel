import { useState, useMemo } from "react";
import { Pressable, ActivityIndicator } from "react-native";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { Link } from "expo-router";
import { type ThemeTokens } from "@/src/theme/tokens";
import { useWorkflowRunTasks } from "@/src/api/hooks/useWorkflows";
import { TaskStatusBadge, TypeBadge, displayTitle } from "@/src/components/shared/TaskConstants";
import { formatStepDuration } from "./WorkflowRunHelpers";

// ---------------------------------------------------------------------------
// WorkflowRunTasks — collapsible panel showing tasks spawned by a workflow run
// ---------------------------------------------------------------------------

export default function WorkflowRunTasks({ runId, steps, t }: {
  runId: string;
  steps: { id?: string }[];
  t: ThemeTokens;
}) {
  const [expanded, setExpanded] = useState(true);
  const { data, isLoading } = useWorkflowRunTasks(runId);
  const tasks = useMemo(() => {
    const raw = data?.tasks ?? [];
    return [...raw].sort((a, b) =>
      (a.workflow_step_index ?? 999) - (b.workflow_step_index ?? 999),
    );
  }, [data?.tasks]);

  const stepLabel = (stepIndex?: number | null) => {
    if (stepIndex == null) return null;
    return steps[stepIndex]?.id || `step_${stepIndex}`;
  };

  return (
    <div style={{
      borderRadius: 8, overflow: "hidden", flexShrink: 0, marginBottom: 12,
      border: `1px solid ${t.surfaceBorder}`, background: t.surface,
    }}>
      {/* Header toggle */}
      <Pressable
        onPress={() => setExpanded((v) => !v)}
        style={{
          flexDirection: "row", alignItems: "center", gap: 6,
          paddingVertical: 8, paddingHorizontal: 12,
        }}
      >
        {expanded
          ? <ChevronDown size={14} color={t.textMuted} />
          : <ChevronRight size={14} color={t.textMuted} />
        }
        <span style={{
          fontSize: 11, fontWeight: 600, color: t.textMuted,
          textTransform: "uppercase", letterSpacing: 0.5,
        }}>
          Tasks ({tasks.length})
        </span>
      </Pressable>

      {/* Rows */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${t.surfaceBorder}` }}>
          {tasks.length === 0 ? (
            <div style={{ padding: "10px 14px", fontSize: 12, color: t.textDim, fontStyle: "italic", display: "flex", alignItems: "center", gap: 6 }}>
              {isLoading ? <><ActivityIndicator color={t.textDim} style={{ width: 12, height: 12 }} /> Loading...</> : "No tasks yet"}
            </div>
          ) : (
            tasks.map((task) => {
              const duration = formatStepDuration(task.run_at || task.created_at, task.completed_at);
              const step = stepLabel(task.workflow_step_index);
              // Prefer trace view (logs) when available; fall back to task editor
              const href = task.correlation_id
                ? `/admin/logs/${task.correlation_id}`
                : `/admin/tasks/${task.id}`;
              return (
                <Link key={task.id} href={href as any}>
                  <div
                    onMouseEnter={(e) => { e.currentTarget.style.background = t.surfaceRaised; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                    style={{
                      display: "flex", alignItems: "center", gap: 10,
                      padding: "8px 14px",
                      borderBottom: `1px solid ${t.surfaceBorder}`,
                      cursor: "pointer", transition: "background 0.1s",
                    }}
                  >
                    {/* Step label */}
                    {step && (
                      <span style={{
                        fontSize: 11, fontWeight: 600, color: t.accent,
                        fontFamily: "monospace", flexShrink: 0,
                      }}>
                        {step}
                      </span>
                    )}
                    {/* Title */}
                    <span style={{
                      fontSize: 12, color: t.text, flex: 1, minWidth: 0,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {displayTitle(task)}
                    </span>
                    {/* Status */}
                    <TaskStatusBadge status={task.status} />
                    {/* Type */}
                    {task.task_type && <TypeBadge type={task.task_type} />}
                    {/* Trace indicator */}
                    {task.correlation_id && (
                      <FileText size={10} color={t.textDim} style={{ flexShrink: 0 }} />
                    )}
                    {/* Duration */}
                    {duration && (
                      <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>
                        {duration}
                      </span>
                    )}
                  </div>
                </Link>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
