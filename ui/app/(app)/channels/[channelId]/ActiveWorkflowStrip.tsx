import { useEffect, useRef, useState } from "react";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  useChannelWorkflowRuns, useCancelWorkflowRun,
  useApproveWorkflowStep, useSkipWorkflowStep,
} from "@/src/api/hooks/useWorkflows";
import { useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  Loader2, CheckCircle2, XCircle, ShieldCheck, ExternalLink, X,
} from "lucide-react";
import type { WorkflowRun } from "@/src/types/api";

const TERMINAL_STATUSES = new Set(["complete", "failed", "cancelled"]);

export function ActiveWorkflowStrip({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const qc = useQueryClient();
  const { data: runs } = useChannelWorkflowRuns(channelId);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  // Track runs that just completed so we can auto-dismiss after 5s
  const prevRunsRef = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    if (!runs) return;
    const prev = prevRunsRef.current;
    const timers: ReturnType<typeof setTimeout>[] = [];
    for (const run of runs) {
      const wasActive = prev.get(run.id);
      if (wasActive && (wasActive === "running" || wasActive === "awaiting_approval") &&
          TERMINAL_STATUSES.has(run.status)) {
        // Run just finished — auto-dismiss after 5s
        const id = run.id;
        timers.push(setTimeout(() => {
          setDismissed((s) => new Set(s).add(id));
          qc.invalidateQueries({ queryKey: ["channel-workflow-runs", channelId] });
        }, 5000));
      }
    }
    prevRunsRef.current = new Map(runs.map((r) => [r.id, r.status]));
    return () => timers.forEach(clearTimeout);
  }, [runs, channelId, qc]);

  // Reset dismissed set on channel switch
  useEffect(() => {
    setDismissed(new Set());
    prevRunsRef.current = new Map();
  }, [channelId]);

  if (!runs || runs.length === 0) return null;

  // Filter out dismissed AND any stale terminal runs (defensive against cached data)
  const visible = runs.filter((r) => !dismissed.has(r.id) && !TERMINAL_STATUSES.has(r.status));
  if (visible.length === 0) return null;

  return (
    <div style={{ borderTop: `1px solid ${t.surfaceBorder}` }}>
      {visible.map((run) => (
        <RunStrip
          key={run.id}
          run={run}
          t={t}
          onDismiss={() => setDismissed((s) => new Set(s).add(run.id))}
        />
      ))}
    </div>
  );
}

/** Minimal elapsed timer — returns formatted string like "1m 23s". */
function useElapsed(startIso: string | undefined | null, isRunning: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!isRunning || !startIso) return;
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [isRunning, startIso]);
  if (!startIso) return null;
  const secs = Math.floor((now - new Date(startIso).getTime()) / 1000);
  if (secs < 0) return null;
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

/** Find the current step name from the workflow snapshot. */
function getCurrentStepId(run: WorkflowRun): string | null {
  const steps = (run.workflow_snapshot as any)?.steps as { id: string }[] | undefined;
  if (!steps) return null;
  // For running: find first step with status "running"
  const runningIdx = run.step_states.findIndex((s) => s.status === "running");
  if (runningIdx >= 0 && steps[runningIdx]) return steps[runningIdx].id;
  // For approval: use current_step_index
  if (run.status === "awaiting_approval" && steps[run.current_step_index]) {
    return steps[run.current_step_index].id;
  }
  return null;
}

function RunStrip({ run, t, onDismiss }: { run: WorkflowRun; t: ThemeTokens; onDismiss: () => void }) {
  const router = useRouter();
  const cancelMut = useCancelWorkflowRun();
  const approveMut = useApproveWorkflowStep();
  const skipMut = useSkipWorkflowStep();
  const done = run.step_states.filter((s) => s.status === "done").length;
  const failed = run.step_states.filter((s) => s.status === "failed").length;
  const skipped = run.step_states.filter((s) => s.status === "skipped").length;
  const total = run.step_states.length;
  const isApproval = run.status === "awaiting_approval";
  const isActive = run.status === "running" || isApproval;

  const currentStepId = getCurrentStepId(run);
  const elapsed = useElapsed(run.created_at, isActive);
  const approvalBusy = approveMut.isPending || skipMut.isPending;

  const bgColor = isApproval ? t.warningSubtle : t.surfaceRaised;
  const borderColor = isApproval ? t.warningBorder : t.surfaceBorder;

  let StatusIcon = Loader2;
  let statusColor = t.accent;
  let statusLabel = "running";
  if (run.status === "complete") { StatusIcon = CheckCircle2; statusColor = t.success; statusLabel = "complete"; }
  else if (run.status === "failed") { StatusIcon = XCircle; statusColor = t.danger; statusLabel = "failed"; }
  else if (run.status === "cancelled") { StatusIcon = XCircle; statusColor = t.textDim; statusLabel = "cancelled"; }
  else if (isApproval) { StatusIcon = ShieldCheck; statusColor = t.warning; statusLabel = "approve"; }

  // Build the label text: "Running: stepId" or "Approve: stepId"
  const labelPrefix = isApproval ? "Approve" : "Running";
  const labelText = currentStepId ? `${labelPrefix}: ${currentStepId}` : statusLabel;

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 10,
      padding: "6px 12px",
      background: bgColor,
      borderBottom: `1px solid ${borderColor}`,
      fontSize: 12,
    }}>
      <StatusIcon size={14} color={statusColor} />
      <span style={{ fontWeight: 600, color: t.text }}>
        {run.workflow_id}
      </span>
      <span style={{ color: isApproval ? t.warning : t.textDim, fontWeight: currentStepId ? 500 : 400 }}>
        {labelText}
      </span>
      {elapsed && (
        <span style={{ color: t.textMuted, fontSize: 11, fontFamily: "monospace" }}>
          {elapsed}
        </span>
      )}

      {/* Mini step bar */}
      <div style={{
        display: "flex", gap: 1, height: 4, borderRadius: 2,
        overflow: "hidden", flex: 1, maxWidth: 120,
      }}>
        {run.step_states.map((s, i) => {
          const color =
            s.status === "done" ? t.success :
            s.status === "running" ? t.accent :
            s.status === "failed" ? t.danger :
            s.status === "awaiting_approval" ? t.warning :
            s.status === "skipped" ? t.surfaceBorder :
            t.surfaceOverlay;
          return <div key={i} style={{ flex: 1, background: color, borderRadius: 1 }} />;
        })}
      </div>

      <span style={{ color: t.textDim, whiteSpace: "nowrap" }}>
        {done + failed + skipped}/{total}
      </span>

      {/* Approve/Skip buttons for approval state */}
      {isApproval && (
        <>
          <button
            onClick={() => approveMut.mutate({ runId: run.id, stepIndex: run.current_step_index })}
            disabled={approvalBusy}
            style={{
              display: "flex", alignItems: "center",
              padding: "6px 12px", borderRadius: 10,
              backgroundColor: t.successSubtle, border: `1px solid ${t.successBorder}`,
              color: t.success, fontSize: 11, fontWeight: 600,
              cursor: approvalBusy ? "default" : "pointer",
              opacity: approvalBusy ? 0.5 : 1,
            }}
          >
            Approve
          </button>
          <button
            onClick={() => skipMut.mutate({ runId: run.id, stepIndex: run.current_step_index })}
            disabled={approvalBusy}
            style={{
              display: "flex", alignItems: "center",
              padding: "6px 12px", borderRadius: 10,
              backgroundColor: t.surfaceOverlay, border: `1px solid ${t.surfaceBorder}`,
              color: t.textDim, fontSize: 11, fontWeight: 600,
              cursor: approvalBusy ? "default" : "pointer",
              opacity: approvalBusy ? 0.5 : 1,
            }}
          >
            Skip
          </button>
        </>
      )}

      <button
        onClick={() => router.push(`/admin/workflows/${run.workflow_id}?tab=runs&run=${run.id}` as any)}
        style={{
          display: "flex", alignItems: "center", gap: 3,
          background: "none", border: "none", cursor: "pointer",
          padding: "6px 8px", borderRadius: 4,
        }}
        aria-label="View workflow run"
      >
        <ExternalLink size={11} color={t.accent} />
        <span style={{ fontSize: 11, color: t.accent }}>View</span>
      </button>

      {/* Cancel button for active runs */}
      {isActive && (
        <button
          onClick={() => cancelMut.mutate(run.id)}
          disabled={cancelMut.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 3,
            padding: "6px 10px", borderRadius: 4,
            backgroundColor: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
            color: t.danger, fontSize: 11, fontWeight: 600,
            cursor: cancelMut.isPending ? "default" : "pointer",
            opacity: cancelMut.isPending ? 0.5 : 1,
          }}
        >
          Cancel
        </button>
      )}

      {/* Dismiss button */}
      <button
        onClick={onDismiss}
        aria-label="Dismiss workflow"
        style={{ background: "none", border: "none", cursor: "pointer", padding: 6, borderRadius: 4 }}
      >
        <X size={13} color={t.textDim} />
      </button>
    </div>
  );
}
