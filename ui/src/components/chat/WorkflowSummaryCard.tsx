/**
 * Rich completion card for workflow terminal events (completed/failed).
 * Shows a step-by-step breakdown with durations, status, and result previews.
 */

import { useState } from "react";
import { useWorkflowRun } from "../../api/hooks/useWorkflows";
import { ExternalLink, Loader2 } from "lucide-react";
import type { ThemeTokens } from "../../theme/tokens";

// Inline helpers (avoids cross-boundary import from admin/workflows)
function fmtDuration(startIso?: string | null, endIso?: string | null): string | null {
  if (!startIso) return null;
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 0) return null;
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

const STATUS_CONFIG: Record<string, { icon: string; color: string }> = {
  done:     { icon: "\u2713", color: "#10b981" },
  failed:   { icon: "\u2717", color: "#ef4444" },
  skipped:  { icon: "\u2014", color: "#6b7280" },
  running:  { icon: "\u25b6", color: "#6366f1" },
  pending:  { icon: "\u25cb", color: "#6b7280" },
};

export function WorkflowSummaryCard({
  runId,
  workflowId,
  workflowName,
  t,
}: {
  runId: string;
  workflowId?: string;
  workflowName: string;
  t: ThemeTokens;
}) {
  const { data: run, isLoading } = useWorkflowRun(runId);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());

  if (isLoading || !run) {
    return (
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "8px 0" }}>
        <Loader2 size={12} color={t.textDim} className="animate-spin" />
        <span style={{ fontSize: 12, color: t.textDim }}>Loading workflow results…</span>
      </div>
    );
  }

  const steps = (run.workflow_snapshot as any)?.steps as { id: string }[] | undefined;
  const isComplete = run.status === "complete";
  const overallDuration = fmtDuration(run.created_at, run.completed_at);
  const doneCount = run.step_states.filter((s) => s.status === "done").length;
  const totalCount = run.step_states.length;
  const headerColor = isComplete ? "#10b981" : "#ef4444";
  const headerIcon = isComplete ? "\u2713" : "\u2717";

  const runDetailHref = workflowId
    ? `/admin/workflows/${workflowId}?tab=runs&run=${runId}`
    : null;

  const toggleStep = (idx: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <div style={{ padding: "4px 0" }}>
      {/* Header line */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
        paddingBottom: 6,
      }}>
        <span style={{ color: headerColor, fontWeight: 700 }}>{headerIcon}</span>
        <span style={{ fontWeight: 600, color: t.text, fontSize: 13 }}>
          {workflowName}
        </span>
        <span style={{
          fontSize: 10, fontWeight: 600, color: headerColor,
          background: `${headerColor}18`, border: `1px solid ${headerColor}30`,
          borderRadius: 10, padding: "0px 6px",
        }}>
          {isComplete ? "completed" : "failed"}
        </span>
        {overallDuration && (
          <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
            {overallDuration}
          </span>
        )}
        <span style={{ fontSize: 11, color: t.textMuted }}>
          ({doneCount}/{totalCount})
        </span>
        {runDetailHref && (
          <span
            onClick={() => { window.location.href = runDetailHref; }}
            title="View full run details"
            style={{
              display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
              cursor: "pointer", color: t.textDim, fontSize: 11,
              opacity: 0.6, transition: "opacity 0.15s",
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.opacity = "1"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.opacity = "0.6"; }}
          >
            <ExternalLink size={10} />
            <span>detail</span>
          </span>
        )}
      </div>

      {/* Step rows */}
      <div style={{
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 6,
        overflow: "hidden",
        background: t.surfaceRaised,
      }}>
        {run.step_states.map((state, idx) => {
          const stepId = steps?.[idx]?.id ?? `step-${idx}`;
          const cfg = STATUS_CONFIG[state.status] ?? STATUS_CONFIG.pending;
          const duration = fmtDuration(state.started_at, state.completed_at);
          const resultText = state.result || state.error || null;
          const isExpanded = expandedSteps.has(idx);
          const previewText = resultText
            ? (resultText.length > 100 ? resultText.slice(0, 100) + "\u2026" : resultText)
            : null;

          return (
            <div key={idx}>
              <div
                onClick={() => resultText && toggleStep(idx)}
                onMouseEnter={(e) => { if (resultText) (e.currentTarget as HTMLElement).style.background = t.surfaceOverlay; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                  padding: "5px 10px",
                  cursor: resultText ? "pointer" : "default",
                  borderTop: idx > 0 ? `1px solid ${t.surfaceBorder}` : undefined,
                  fontSize: 12,
                  transition: "background 0.1s",
                }}
              >
                <span style={{ color: cfg.color, fontWeight: 600, width: 14, textAlign: "center", flexShrink: 0 }}>
                  {cfg.icon}
                </span>
                <span style={{
                  fontFamily: "monospace", fontWeight: 500, color: t.text,
                  minWidth: 80, flexShrink: 0,
                }}>
                  {stepId}
                </span>
                {duration && (
                  <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace", flexShrink: 0 }}>
                    {duration}
                  </span>
                )}
                {state.status === "skipped" && !duration && (
                  <span style={{ fontSize: 11, color: t.textDim }}>skip</span>
                )}
                {previewText && !isExpanded && (
                  <span style={{
                    fontSize: 11, color: state.error ? t.danger : t.textDim,
                    fontStyle: "italic",
                    flex: 1, minWidth: 0,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>
                    &ldquo;{previewText}&rdquo;
                  </span>
                )}
              </div>
              {isExpanded && resultText && (
                <div style={{
                  padding: "4px 10px 8px 32px",
                  fontSize: 12, lineHeight: "1.5",
                  color: state.error ? t.danger : t.textMuted,
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                  borderTop: `1px solid ${t.surfaceBorder}`,
                  background: t.surface,
                }}>
                  {resultText}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Run error at bottom if present */}
      {run.error && (
        <div style={{
          marginTop: 6, padding: "6px 10px", borderRadius: 4,
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
          fontSize: 12, color: t.danger,
        }}>
          {run.error}
        </div>
      )}
    </div>
  );
}
