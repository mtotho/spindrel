import { Spinner } from "@/src/components/shared/Spinner";
import { useState, useMemo } from "react";

import { ChevronDown, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { type ThemeTokens } from "@/src/theme/tokens";
import { useWorkflowRunTasks } from "@/src/api/hooks/useWorkflows";
import { TaskStatusBadge, TypeBadge, displayTitle } from "@/src/components/shared/TaskConstants";
import { formatStepDuration } from "./WorkflowRunHelpers";
import { openTraceInspector } from "@/src/stores/traceInspector";

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
      <button type="button"
        onClick={() => setExpanded((v) => !v)}
        style={{
          display: "flex",
          flexDirection: "row", alignItems: "center", gap: 6,
          paddingBlock: 8, paddingInline: 12,
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
      </button>

      {/* Rows */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${t.surfaceBorder}` }}>
          {tasks.length === 0 ? (
            <div style={{ padding: "10px 14px", fontSize: 12, color: t.textDim, fontStyle: "italic", display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
              {isLoading ? <><Spinner /> Loading...</> : "No tasks yet"}
            </div>
          ) : (
            tasks.map((task) => {
              const duration = formatStepDuration(task.run_at || task.created_at, task.completed_at);
              const step = stepLabel(task.workflow_step_index);
              const row = (
                <div
                  onMouseEnter={(e) => { e.currentTarget.style.background = t.surfaceRaised; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                  style={{
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 10,
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
                  <TaskStatusBadge status={task.status} />
                  {task.task_type && <TypeBadge type={task.task_type} />}
                  <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>
                    {duration}
                  </span>
                </div>
              );
              if (task.correlation_id) {
                return (
                  <button
                    key={task.id}
                    type="button"
                    onClick={() => openTraceInspector({
                      correlationId: task.correlation_id!,
                      title: displayTitle(task),
                      subtitle: task.bot_id,
                    })}
                    className="block w-full bg-transparent p-0 text-left"
                  >
                    {row}
                  </button>
                );
              }
              return (
                <Link key={task.id} to={`/admin/automations/${task.id}`}>
                  {row}
                </Link>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
