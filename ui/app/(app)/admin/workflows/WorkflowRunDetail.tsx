import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useMemo } from "react";

import { useThemeTokens } from "@/src/theme/tokens";
import {
  useWorkflow,
  useWorkflowRun,
  useTriggerWorkflow,
  useCancelWorkflowRun,
  useApproveWorkflowStep,
  useSkipWorkflowStep,
  useRetryWorkflowStep,
} from "@/src/api/hooks/useWorkflows";
import {
  X, RefreshCw, ArrowLeft, MessageSquare,
} from "lucide-react";
import { Link } from "react-router-dom";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";

import {
  StatusBadge, fmtTime, MetaItem, StepNavItem, useElapsed, formatStepDuration,
} from "./WorkflowRunHelpers";
import WorkflowRunFeed from "./WorkflowRunFeed";
import WorkflowRunTasks from "./WorkflowRunTasks";

// ---------------------------------------------------------------------------
// Run detail (split-panel: step nav + feed)
// ---------------------------------------------------------------------------

export default function WorkflowRunDetail({ runId, workflowId, onBack, onNavigateToRun, embedded }: {
  runId: string;
  workflowId: string;
  onBack: () => void;
  onNavigateToRun: (id: string) => void;
  embedded?: boolean;
}) {
  const t = useThemeTokens();
  const { width } = useWindowSize();
  const isMobile = embedded ? false : width < 768;

  const { data: run, isLoading } = useWorkflowRun(runId);
  const { data: workflow } = useWorkflow(workflowId);
  const cancelMut = useCancelWorkflowRun();
  const triggerMut = useTriggerWorkflow(workflowId);
  const approveMut = useApproveWorkflowStep();
  const skipMut = useSkipWorkflowStep();
  const retryMut = useRetryWorkflowStep();

  const [activeStepIndex, setActiveStepIndex] = useState<number | null>(null);
  const [runAgainError, setRunAgainError] = useState<string | null>(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  const isActive = run?.status === "running" || run?.status === "awaiting_approval";
  const runElapsed = useElapsed(run?.created_at ?? null, isActive);
  const runDuration = run?.completed_at ? formatStepDuration(run.created_at, run.completed_at) : null;

  if (isLoading || !run) {
    return (
      <div style={{ display: "flex", alignItems: "center", padding: 24 }}>
        <Spinner />
      </div>
    );
  }

  const steps = workflow?.steps || [];

  const handleRunAgain = async () => {
    setRunAgainError(null);
    try {
      const newRun = await triggerMut.mutateAsync({
        params: run.params,
        bot_id: run.bot_id,
        channel_id: run.channel_id || undefined,
        session_mode: run.session_mode || undefined,
      });
      onNavigateToRun(newRun.id);
    } catch (err: any) {
      const msg = err?.message || err?.data?.detail || "Failed to trigger workflow";
      setRunAgainError(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      {/* Header */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
        paddingBottom: 12, flexShrink: 0,
      }}>
        {!embedded ? (
          <button type="button"
            onClick={onBack}
            style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}
          >
            <ArrowLeft size={16} color={t.textMuted} />
            <span style={{ color: t.textMuted, fontSize: 13 }}>All runs</span>
          </button>
        ) : (
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: t.text, fontFamily: "monospace" }}>
              {run.id.slice(0, 8)}
            </span>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "row", gap: 8, alignItems: "center" }}>
          <StatusBadge status={run.status} t={t} />
          {(runDuration || runElapsed) && (
            <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              {runDuration || runElapsed}
            </span>
          )}
          {!isActive && (
            <button
              onClick={handleRunAgain}
              disabled={triggerMut.isPending}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                padding: "4px 10px", fontSize: 11, fontWeight: 600,
                border: `1px solid ${t.accentBorder}`, borderRadius: 5,
                background: t.accentSubtle, color: t.accent, cursor: "pointer",
                opacity: triggerMut.isPending ? 0.6 : 1,
              }}
            >
              {triggerMut.isPending
                ? <Spinner />
                : <RefreshCw size={12} />
              }
              {triggerMut.isPending ? "Starting..." : "Run Again"}
            </button>
          )}
          {isActive && (
            <>
              <button
                onClick={() => setShowCancelConfirm(true)}
                disabled={cancelMut.isPending}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  padding: "4px 10px", fontSize: 11, fontWeight: 600,
                  border: `1px solid ${t.dangerBorder}`, borderRadius: 5,
                  background: t.dangerSubtle, color: t.danger, cursor: "pointer",
                }}
              >
                <X size={12} />
                Cancel
              </button>
              <ConfirmDialog
                open={showCancelConfirm}
                title="Cancel Workflow"
                message="Cancel this workflow run? In-flight steps will be abandoned."
                confirmLabel="Cancel Run"
                variant="danger"
                onConfirm={() => {
                  cancelMut.mutate(runId);
                  setShowCancelConfirm(false);
                }}
                onCancel={() => setShowCancelConfirm(false)}
              />
            </>
          )}
        </div>
      </div>

      {/* Run metadata */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
        gap: 8, padding: 12, borderRadius: 8, flexShrink: 0,
        background: t.surface,
        marginBottom: 12,
      }}>
        {!embedded && <MetaItem label="Run ID" value={run.id.slice(0, 8)} t={t} mono />}
        <MetaItem label="Bot" value={run.bot_id} t={t} />
        <MetaItem label="Triggered by" value={run.triggered_by || "\u2014"} t={t} />
        <MetaItem label="Context" value={run.session_mode || "isolated"} t={t} />
        <MetaItem label="Started" value={fmtTime(run.created_at)} t={t} />
        {run.completed_at && <MetaItem label="Completed" value={fmtTime(run.completed_at)} t={t} />}
        {run.channel_id && (
          <div>
            <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>Channel</div>
            <Link to={`/channels/${run.channel_id}` as any}>
              <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3, fontSize: 12, color: t.accent, marginTop: 1 }}>
                <MessageSquare size={11} />
                {run.channel_id.slice(0, 8)}
              </span>
            </Link>
          </div>
        )}
      </div>

      {/* Run Again error */}
      {runAgainError && (
        <div style={{
          padding: 10, borderRadius: 8, flexShrink: 0, marginBottom: 12,
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
          color: t.danger, fontSize: 12,
          display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
        }}>
          <span>Run Again failed: {runAgainError}</span>
          <button
            onClick={() => setRunAgainError(null)}
            style={{ background: "none", border: "none", color: t.danger, cursor: "pointer", padding: 2 }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Error */}
      {run.error && (
        <div style={{
          padding: 10, borderRadius: 8, flexShrink: 0, marginBottom: 12,
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
          color: t.danger, fontSize: 12, fontFamily: "monospace", whiteSpace: "pre-wrap",
        }}>
          {run.error}
        </div>
      )}

      {/* Params */}
      {Object.keys(run.params).length > 0 && (
        <div style={{
          padding: 10, borderRadius: 8, flexShrink: 0, marginBottom: 12,
          background: t.surface,
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Parameters
          </div>
          <div style={{ display: "flex", flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
            {Object.entries(run.params).map(([k, v]) => (
              <span key={k} style={{ fontSize: 12, color: t.text }}>
                <span style={{ color: t.textDim }}>{k}:</span>{" "}
                <span style={{ fontFamily: "monospace" }}>{String(v)}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tasks spawned by this run */}
      <WorkflowRunTasks runId={runId} steps={steps} t={t} />

      {/* Mobile: vertical step list with names + status */}
      {isMobile && (
        <div style={{
          flexShrink: 0, marginBottom: 8,
          borderRadius: 8, overflow: "hidden",
          border: `1px solid ${t.surfaceBorder}`, background: t.surface,
        }}>
          <div style={{
            display: "flex", flexDirection: "column",
          }}>
            {run.step_states.map((state, i) => {
              const stepId = steps[i]?.id || `step_${i}`;
              const isActive = activeStepIndex === i;
              const dotColor =
                state.status === "done" ? t.success :
                state.status === "running" ? t.accent :
                state.status === "failed" ? t.danger :
                state.status === "awaiting_approval" ? t.warning :
                state.status === "skipped" ? t.textDim :
                t.inputBorder;
              return (
                <button type="button"
                  key={i}
                  onClick={() => setActiveStepIndex(i)}
                  style={{
                    display: "flex",
                    flexDirection: "row", alignItems: "center", gap: 8,
                    paddingBlock: 8, paddingInline: 12,
                    borderLeftWidth: 2,
                    borderLeftColor: isActive ? t.accent : "transparent",
                    backgroundColor: isActive ? t.accentSubtle : "transparent",
                    borderBottomWidth: i < run.step_states.length - 1 ? 1 : 0,
                    borderBottomColor: t.surfaceBorder,
                  }}
                >
                  <div style={{
                    width: 8, height: 8, borderRadius: 4, flexShrink: 0,
                    background: dotColor,
                  }} />
                  <span style={{
                    fontSize: 12, color: isActive ? t.text : t.textDim,
                    fontWeight: isActive ? "600" : "400",
                    flex: 1,
                  }}>
                    {stepId}
                  </span>
                  <StatusBadge status={state.status} t={t} />
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Split panel */}
      <div style={{
        display: "flex",
        flexDirection: isMobile ? "column" : "row",
        flex: 1, minHeight: 0,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8, overflow: "hidden",
        background: t.surface,
      }}>
        {/* Step nav sidebar (desktop) */}
        {!isMobile && (
          <div style={{
            width: 200, flexShrink: 0, overflow: "auto",
            borderRight: `1px solid ${t.surfaceBorder}`,
            background: t.surfaceRaised,
            display: "flex", flexDirection: "column",
          }}>
            <div style={{
              padding: "8px 10px", fontSize: 10, fontWeight: 600,
              color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5,
              borderBottom: `1px solid ${t.surfaceBorder}`,
              background: t.surfaceOverlay,
            }}>
              Steps
            </div>
            {run.step_states.map((state, i) => (
              <StepNavItem
                key={i}
                stepId={steps[i]?.id || `step_${i}`}
                state={state}
                isActive={activeStepIndex === i}
                onClick={() => setActiveStepIndex(i)}
                t={t}
              />
            ))}
          </div>
        )}

        {/* Feed */}
        <WorkflowRunFeed
          stepStates={run.step_states}
          steps={steps}
          runStatus={run.status}
          runParams={run.params}
          runId={runId}
          t={t}
          activeStepIndex={activeStepIndex}
          onApprove={(i) => approveMut.mutate({ runId, stepIndex: i })}
          onSkip={(i) => skipMut.mutate({ runId, stepIndex: i })}
          onRetry={(i) => retryMut.mutate({ runId, stepIndex: i })}
          pendingApproveStep={approveMut.isPending ? approveMut.variables?.stepIndex ?? null : null}
          pendingSkipStep={skipMut.isPending ? skipMut.variables?.stepIndex ?? null : null}
          pendingRetryStep={retryMut.isPending ? retryMut.variables?.stepIndex ?? null : null}
        />
      </div>
    </div>
  );
}
