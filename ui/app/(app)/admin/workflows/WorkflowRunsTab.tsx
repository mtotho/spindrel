import { useState, useMemo, useEffect } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  useWorkflow,
  useWorkflowRuns,
  useWorkflowRun,
  useTriggerWorkflow,
  useCancelWorkflowRun,
  useApproveWorkflowStep,
  useSkipWorkflowStep,
  useRetryWorkflowStep,
} from "@/src/api/hooks/useWorkflows";
import { useBots } from "@/src/api/hooks/useBots";
import {
  Play, X, Check, SkipForward, RotateCcw, Clock,
  CheckCircle2, XCircle, Loader2, ShieldCheck, CircleDot, Minus,
  ChevronDown, ChevronRight, ArrowLeft, ExternalLink, AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { Link } from "expo-router";
import type { WorkflowRun, WorkflowStepState } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Status styling
// ---------------------------------------------------------------------------

function getStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "running":
      return { bg: t.accentSubtle, border: t.accentBorder, text: t.accent, icon: Loader2 };
    case "complete":
    case "done":
      return { bg: t.successSubtle, border: t.successBorder, text: t.success, icon: CheckCircle2 };
    case "failed":
      return { bg: t.dangerSubtle, border: t.dangerBorder, text: t.danger, icon: XCircle };
    case "cancelled":
      return { bg: t.surfaceRaised, border: t.surfaceBorder, text: t.textDim, icon: X };
    case "awaiting_approval":
      return { bg: t.warningSubtle, border: t.warningBorder, text: t.warning, icon: ShieldCheck };
    case "skipped":
      return { bg: t.surfaceRaised, border: t.surfaceBorder, text: t.textDim, icon: Minus };
    case "pending":
      return { bg: t.surfaceRaised, border: t.surfaceBorder, text: t.textDim, icon: Clock };
    default:
      return { bg: t.surfaceRaised, border: t.surfaceBorder, text: t.textDim, icon: CircleDot };
  }
}

function StatusBadge({ status, t }: { status: string; t: ThemeTokens }) {
  const s = getStatusStyle(status, t);
  const Icon = s.icon;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: s.bg, border: `1px solid ${s.border}`, color: s.text,
    }}>
      <Icon size={12} />
      {status.replace(/_/g, " ")}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Condition → human-readable explanation
// ---------------------------------------------------------------------------

function describeCondition(when: any): string {
  if (!when) return "";
  if (when.step && when.status) return `Requires step "${when.step}" to be ${when.status}`;
  if (when.step && when.output_contains) return `Requires "${when.step}" output to contain "${when.output_contains}"`;
  if (when.step && when.output_not_contains) return `Requires "${when.step}" output to NOT contain "${when.output_not_contains}"`;
  if (when.param) return `Requires param "${when.param}" ${when.equals != null ? `= "${when.equals}"` : when.not_equals != null ? `!= "${when.not_equals}"` : "to be set"}`;
  if (when.all) return (when.all as any[]).map(describeCondition).join(" AND ");
  if (when.any) return (when.any as any[]).map(describeCondition).join(" OR ");
  if (when.not) return `NOT (${describeCondition(when.not)})`;
  return JSON.stringify(when);
}

// ---------------------------------------------------------------------------
// Elapsed time for running steps
// ---------------------------------------------------------------------------

function useElapsed(startedAt?: string | null, isRunning?: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!isRunning || !startedAt) return;
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [isRunning, startedAt]);

  if (!startedAt) return null;
  const start = new Date(startedAt).getTime();
  const end = isRunning ? now : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export default function WorkflowRunsTab({ workflowId, initialRunId }: { workflowId: string; initialRunId?: string }) {
  const t = useThemeTokens();
  const { data: runs, isLoading } = useWorkflowRuns(workflowId);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId ?? null);
  const [showTrigger, setShowTrigger] = useState(false);

  if (selectedRunId) {
    return (
      <RunDetail
        runId={selectedRunId}
        workflowId={workflowId}
        onBack={() => setSelectedRunId(null)}
      />
    );
  }

  return (
    <View style={{ gap: 12 }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={{ color: t.textMuted, fontSize: 12 }}>
          {runs ? `${runs.length} run${runs.length !== 1 ? "s" : ""}` : ""}
        </Text>
        <button
          onClick={() => setShowTrigger(!showTrigger)}
          style={{
            display: "flex", alignItems: "center", gap: 5,
            padding: "5px 12px", fontSize: 12, fontWeight: 600,
            border: "none", borderRadius: 6,
            background: t.accent, color: "#fff", cursor: "pointer",
          }}
        >
          <Play size={13} />
          Trigger Run
        </button>
      </div>

      {/* Trigger form */}
      {showTrigger && (
        <TriggerForm
          workflowId={workflowId}
          t={t}
          onTriggered={(runId) => {
            setShowTrigger(false);
            setSelectedRunId(runId);
          }}
          onCancel={() => setShowTrigger(false)}
        />
      )}

      {/* Run list */}
      {isLoading ? (
        <View style={{ alignItems: "center", padding: 24 }}>
          <ActivityIndicator color={t.accent} />
        </View>
      ) : !runs || runs.length === 0 ? (
        <div style={{
          padding: 32, textAlign: "center", color: t.textDim, fontSize: 13,
          background: t.surfaceRaised, borderRadius: 8, border: `1px solid ${t.surfaceBorder}`,
        }}>
          No runs yet. Trigger one to get started.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {runs.map((run) => (
            <RunCard key={run.id} run={run} t={t} onSelect={() => setSelectedRunId(run.id)} />
          ))}
        </div>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Run card (list item)
// ---------------------------------------------------------------------------

function RunCard({ run, t, onSelect }: { run: WorkflowRun; t: ThemeTokens; onSelect: () => void }) {
  const doneSteps = run.step_states.filter((s) =>
    s.status === "done" || s.status === "skipped" || s.status === "failed"
  ).length;
  const totalSteps = run.step_states.length;

  return (
    <Pressable
      onPress={onSelect}
      style={{
        backgroundColor: t.surfaceRaised, borderRadius: 8,
        borderWidth: 1, borderColor: t.surfaceBorder, padding: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <StatusBadge status={run.status} t={t} />
          <span style={{ fontSize: 12, color: t.textDim, fontFamily: "monospace" }}>
            {run.id.slice(0, 8)}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: t.textDim }}>
            {doneSteps}/{totalSteps} steps
          </span>
          <ChevronRight size={14} color={t.textDim} />
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
        <span style={{ fontSize: 11, color: t.textDim }}>
          bot: {run.bot_id}
        </span>
        {run.triggered_by && (
          <span style={{ fontSize: 11, color: t.textDim }}>
            via {run.triggered_by}
          </span>
        )}
        <span style={{ fontSize: 11, color: t.textDim }}>
          {fmtTime(run.created_at)}
        </span>
      </div>
      {/* Mini step bar */}
      <div style={{ display: "flex", gap: 2, marginTop: 8, height: 4, borderRadius: 2, overflow: "hidden" }}>
        {run.step_states.map((s, i) => {
          const color =
            s.status === "done" ? t.success :
            s.status === "running" ? t.accent :
            s.status === "failed" ? t.danger :
            s.status === "skipped" ? t.surfaceBorder :
            t.surfaceOverlay;
          return <div key={i} style={{ flex: 1, background: color, borderRadius: 1 }} />;
        })}
      </div>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Run detail (step-by-step viewer)
// ---------------------------------------------------------------------------

function RunDetail({ runId, workflowId, onBack }: {
  runId: string;
  workflowId: string;
  onBack: () => void;
}) {
  const t = useThemeTokens();
  const { data: run, isLoading } = useWorkflowRun(runId);
  const { data: workflow } = useWorkflow(workflowId);
  const cancelMut = useCancelWorkflowRun();
  const triggerMut = useTriggerWorkflow(workflowId);
  const approveMut = useApproveWorkflowStep();
  const skipMut = useSkipWorkflowStep();
  const retryMut = useRetryWorkflowStep();

  if (isLoading || !run) {
    return (
      <View style={{ alignItems: "center", padding: 24 }}>
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  const steps = workflow?.steps || [];
  const isActive = run.status === "running" || run.status === "awaiting_approval";

  const handleRunAgain = async () => {
    try {
      const newRun = await triggerMut.mutateAsync({
        params: run.params,
        bot_id: run.bot_id,
      });
      // Navigate to the new run — use onBack then ... actually just reload with new ID
      // We can't easily change selectedRunId from here, so use window location
      window.location.href = `/admin/workflows/${workflowId}?tab=runs&run=${newRun.id}`;
    } catch {
      // handled by mutation
    }
  };

  return (
    <View style={{ gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Pressable
          onPress={onBack}
          style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
        >
          <ArrowLeft size={16} color={t.textMuted} />
          <Text style={{ color: t.textMuted, fontSize: 13 }}>All runs</Text>
        </Pressable>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <StatusBadge status={run.status} t={t} />
          {/* Run Again button for terminal runs */}
          {!isActive && (
            <button
              onClick={handleRunAgain}
              disabled={triggerMut.isPending}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "4px 10px", fontSize: 11, fontWeight: 600,
                border: `1px solid ${t.accentBorder}`, borderRadius: 5,
                background: t.accentSubtle, color: t.accent, cursor: "pointer",
                opacity: triggerMut.isPending ? 0.6 : 1,
              }}
            >
              <RefreshCw size={12} />
              Run Again
            </button>
          )}
          {isActive && (
            <button
              onClick={() => cancelMut.mutate(runId)}
              disabled={cancelMut.isPending}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "4px 10px", fontSize: 11, fontWeight: 600,
                border: `1px solid ${t.dangerBorder}`, borderRadius: 5,
                background: t.dangerSubtle, color: t.danger, cursor: "pointer",
              }}
            >
              <X size={12} />
              Cancel
            </button>
          )}
        </div>
      </div>

      {/* Run metadata */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
        gap: 8, padding: 12, borderRadius: 8,
        background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
      }}>
        <MetaItem label="Run ID" value={run.id.slice(0, 8)} t={t} mono />
        <MetaItem label="Bot" value={run.bot_id} t={t} />
        <MetaItem label="Triggered by" value={run.triggered_by || "—"} t={t} />
        <MetaItem label="Started" value={fmtTime(run.created_at)} t={t} />
        {run.completed_at && <MetaItem label="Completed" value={fmtTime(run.completed_at)} t={t} />}
        {run.session_id && <MetaItem label="Session" value={run.session_id.slice(0, 8)} t={t} mono />}
      </div>

      {/* Error */}
      {run.error && (
        <div style={{
          padding: 10, borderRadius: 8,
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
          color: t.danger, fontSize: 12, fontFamily: "monospace", whiteSpace: "pre-wrap",
        }}>
          {run.error}
        </div>
      )}

      {/* Params */}
      {Object.keys(run.params).length > 0 && (
        <div style={{
          padding: 10, borderRadius: 8,
          background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: t.textDim, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Parameters
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {Object.entries(run.params).map(([k, v]) => (
              <span key={k} style={{ fontSize: 12, color: t.text }}>
                <span style={{ color: t.textDim }}>{k}:</span>{" "}
                <span style={{ fontFamily: "monospace" }}>{String(v)}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Step timeline */}
      <div style={{ fontSize: 11, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
        Steps
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {run.step_states.map((state, i) => (
          <StepCard
            key={i}
            index={i}
            state={state}
            stepDef={steps[i]}
            runStatus={run.status}
            runParams={run.params}
            runId={runId}
            t={t}
            onApprove={() => approveMut.mutate({ runId, stepIndex: i })}
            onSkip={() => skipMut.mutate({ runId, stepIndex: i })}
            onRetry={() => retryMut.mutate({ runId, stepIndex: i })}
            isApproving={approveMut.isPending}
            isSkipping={skipMut.isPending}
            isRetrying={retryMut.isPending}
          />
        ))}
      </div>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Step card with expand/collapse
// ---------------------------------------------------------------------------

function StepCard({
  index, state, stepDef, runStatus, runParams, runId, t,
  onApprove, onSkip, onRetry,
  isApproving, isSkipping, isRetrying,
}: {
  index: number;
  state: WorkflowStepState;
  stepDef?: { id?: string; prompt?: string; requires_approval?: boolean; on_failure?: string; when?: any };
  runStatus: string;
  runParams: Record<string, any>;
  runId: string;
  t: ThemeTokens;
  onApprove: () => void;
  onSkip: () => void;
  onRetry: () => void;
  isApproving: boolean;
  isSkipping: boolean;
  isRetrying: boolean;
}) {
  const [expanded, setExpanded] = useState(
    state.status === "running" || state.status === "failed" ||
    (runStatus === "awaiting_approval" && state.status === "pending")
  );
  const s = getStatusStyle(state.status, t);
  const Icon = s.icon;
  const stepId = stepDef?.id || `step_${index}`;
  const isStepRunning = state.status === "running";
  const elapsed = useElapsed(state.started_at, isStepRunning);

  const isAwaitingApproval = runStatus === "awaiting_approval" &&
    state.status === "pending" && stepDef?.requires_approval;
  const canRetry = state.status === "failed";

  // Render the prompt with params substituted for readability
  const renderedPrompt = useMemo(() => {
    if (!stepDef?.prompt) return null;
    let p = stepDef.prompt;
    for (const [k, v] of Object.entries(runParams)) {
      p = p.replaceAll(`{{${k}}}`, String(v));
    }
    return p.slice(0, 800);
  }, [stepDef?.prompt, runParams]);

  // Explain why step was skipped
  const skipReason = useMemo(() => {
    if (state.status !== "skipped" || !stepDef?.when) return null;
    return describeCondition(stepDef.when);
  }, [state.status, stepDef?.when]);

  return (
    <div style={{
      borderRadius: 8, overflow: "hidden",
      border: `1px solid ${s.border}`, background: t.surfaceRaised,
    }}>
      {/* Header (always visible) */}
      <Pressable
        onPress={() => setExpanded(!expanded)}
        style={{
          flexDirection: "row", alignItems: "center", gap: 8,
          padding: 10,
        }}
      >
        <div style={{
          width: 24, height: 24, borderRadius: 12, flexShrink: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          background: s.bg, border: `1px solid ${s.border}`,
        }}>
          <Icon size={13} color={s.text} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
              {stepId}
            </span>
            <StatusBadge status={state.status} t={t} />
            {isStepRunning && elapsed && (
              <span style={{ fontSize: 11, color: t.textDim }}>{elapsed}</span>
            )}
          </div>
          {/* Inline skip reason on collapsed card */}
          {!expanded && skipReason && (
            <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>
              Skipped: {skipReason}
            </div>
          )}
          {/* Inline result preview on collapsed card */}
          {!expanded && state.result && (
            <div style={{
              fontSize: 11, color: t.success, marginTop: 2,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {state.result.slice(0, 120)}
            </div>
          )}
          {/* Inline error preview on collapsed card */}
          {!expanded && state.error && !state.result && (
            <div style={{
              fontSize: 11, color: t.danger, marginTop: 2,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {state.error.slice(0, 120)}
            </div>
          )}
        </div>
        {expanded ? <ChevronDown size={14} color={t.textDim} /> : <ChevronRight size={14} color={t.textDim} />}
      </Pressable>

      {/* Expanded content */}
      {expanded && (
        <div style={{
          padding: "0 10px 10px 10px",
          borderTop: `1px solid ${t.surfaceBorder}`,
        }}>
          {/* Skip reason banner */}
          {skipReason && (
            <div style={{
              display: "flex", alignItems: "flex-start", gap: 6,
              marginTop: 8, padding: 8, borderRadius: 6,
              background: t.warningSubtle, border: `1px solid ${t.warningBorder}`,
            }}>
              <AlertTriangle size={13} color={t.warning} style={{ flexShrink: 0, marginTop: 1 }} />
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: t.warning }}>
                  Condition not met
                </div>
                <div style={{ fontSize: 11, color: t.text, marginTop: 2 }}>
                  {skipReason}
                </div>
              </div>
            </div>
          )}

          {/* Running too long warning */}
          {isStepRunning && elapsed && parseInt(elapsed) > 0 && (
            (() => {
              const startMs = new Date(state.started_at!).getTime();
              const elapsedMs = Date.now() - startMs;
              if (elapsedMs > 300000) { // 5 min
                return (
                  <div style={{
                    display: "flex", alignItems: "center", gap: 6,
                    marginTop: 8, padding: 8, borderRadius: 6,
                    background: t.warningSubtle, border: `1px solid ${t.warningBorder}`,
                  }}>
                    <AlertTriangle size={13} color={t.warning} />
                    <span style={{ fontSize: 11, color: t.warning, fontWeight: 600 }}>
                      Running for {elapsed} — this step may be stuck. Check the linked task for details.
                    </span>
                  </div>
                );
              }
              return null;
            })()
          )}

          {/* Timing + links */}
          <div style={{ display: "flex", gap: 12, marginTop: 8, flexWrap: "wrap" }}>
            {state.started_at && (
              <span style={{ fontSize: 11, color: t.textDim }}>
                Started: {fmtTime(state.started_at)}
              </span>
            )}
            {state.completed_at && (
              <span style={{ fontSize: 11, color: t.textDim }}>
                Completed: {fmtTime(state.completed_at)}
              </span>
            )}
            {isStepRunning && elapsed && (
              <span style={{ fontSize: 11, color: t.accent, fontWeight: 600 }}>
                Elapsed: {elapsed}
              </span>
            )}
            {state.retry_count != null && state.retry_count > 0 && (
              <span style={{ fontSize: 11, color: t.warning }}>
                Retries: {state.retry_count}
              </span>
            )}
            {state.task_id && (
              <Link href={`/admin/tasks/${state.task_id}` as any}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11, color: t.accent }}>
                  <ExternalLink size={10} />
                  Task: {state.task_id.slice(0, 8)}...
                </span>
              </Link>
            )}
            {state.correlation_id && (
              <Link href={`/admin/logs/${state.correlation_id}` as any}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11, color: t.accent }}>
                  <ExternalLink size={10} />
                  Trace
                </span>
              </Link>
            )}
          </div>

          {/* Condition (when clause) — show what this step requires */}
          {stepDef?.when && state.status !== "skipped" && (
            <div style={{
              marginTop: 8, padding: 6, borderRadius: 4,
              fontSize: 11, color: t.textDim, fontStyle: "italic",
              background: `${t.surfaceOverlay}80`,
            }}>
              Condition: {describeCondition(stepDef.when)}
            </div>
          )}

          {/* Step prompt (rendered with params) */}
          {renderedPrompt && (
            <details style={{ marginTop: 8 }}>
              <summary style={{
                fontSize: 11, color: t.textDim, cursor: "pointer",
                userSelect: "none",
              }}>
                Prompt
              </summary>
              <div style={{
                marginTop: 4, padding: 8, borderRadius: 6,
                background: `${t.surfaceOverlay}80`,
                fontSize: 12, color: t.textMuted,
                fontFamily: "monospace", whiteSpace: "pre-wrap",
                maxHeight: 200, overflow: "auto",
                lineHeight: 1.5,
              }}>
                {renderedPrompt}
              </div>
            </details>
          )}

          {/* Result */}
          {state.result && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: t.success, marginBottom: 4 }}>Result</div>
              <div style={{
                padding: 8, borderRadius: 6,
                background: t.successSubtle, border: `1px solid ${t.successBorder}`,
                fontSize: 12, color: t.text, whiteSpace: "pre-wrap", maxHeight: 300, overflow: "auto",
              }}>
                {state.result}
              </div>
            </div>
          )}

          {/* Error */}
          {state.error && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: t.danger, marginBottom: 4 }}>Error</div>
              <div style={{
                padding: 8, borderRadius: 6,
                background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
                fontSize: 12, color: t.danger, fontFamily: "monospace", whiteSpace: "pre-wrap",
              }}>
                {state.error}
              </div>
            </div>
          )}

          {/* Action buttons */}
          {(isAwaitingApproval || canRetry) && (
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              {isAwaitingApproval && (
                <>
                  <button
                    onClick={onApprove}
                    disabled={isApproving}
                    style={{
                      display: "flex", alignItems: "center", gap: 4,
                      padding: "5px 12px", fontSize: 12, fontWeight: 600,
                      border: "none", borderRadius: 6,
                      background: t.success, color: "#fff", cursor: "pointer",
                      opacity: isApproving ? 0.6 : 1,
                    }}
                  >
                    <Check size={13} />
                    Approve
                  </button>
                  <button
                    onClick={onSkip}
                    disabled={isSkipping}
                    style={{
                      display: "flex", alignItems: "center", gap: 4,
                      padding: "5px 12px", fontSize: 12, fontWeight: 600,
                      border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                      background: "transparent", color: t.textMuted, cursor: "pointer",
                      opacity: isSkipping ? 0.6 : 1,
                    }}
                  >
                    <SkipForward size={13} />
                    Skip
                  </button>
                </>
              )}
              {canRetry && (
                <button
                  onClick={onRetry}
                  disabled={isRetrying}
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "5px 12px", fontSize: 12, fontWeight: 600,
                    border: `1px solid ${t.accentBorder}`, borderRadius: 6,
                    background: t.accentSubtle, color: t.accent, cursor: "pointer",
                    opacity: isRetrying ? 0.6 : 1,
                  }}
                >
                  <RotateCcw size={13} />
                  Retry
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trigger form with proper param fields + bot dropdown
// ---------------------------------------------------------------------------

function TriggerForm({
  workflowId, t, onTriggered, onCancel,
}: {
  workflowId: string;
  t: ThemeTokens;
  onTriggered: (runId: string) => void;
  onCancel: () => void;
}) {
  const { data: workflow } = useWorkflow(workflowId);
  const { data: bots } = useBots();
  const triggerMut = useTriggerWorkflow(workflowId);

  const paramDefs = workflow?.params || {};
  const defaultBot = workflow?.defaults?.bot_id || "";
  const hasParams = Object.keys(paramDefs).length > 0;

  // Build param state from definitions
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [botId, setBotId] = useState("");

  // Initialize defaults when workflow loads
  useEffect(() => {
    if (!workflow) return;
    const defaults: Record<string, string> = {};
    for (const [k, v] of Object.entries(workflow.params || {})) {
      const def = v as any;
      if (def.default != null) defaults[k] = String(def.default);
    }
    setParamValues((prev) => ({ ...defaults, ...prev }));
  }, [workflow]);

  const handleTrigger = async () => {
    // Build params with type coercion
    const params: Record<string, any> = {};
    for (const [k, v] of Object.entries(paramDefs)) {
      const def = v as any;
      const val = paramValues[k];
      if (def.required && (!val || val.trim() === "")) {
        alert(`Parameter "${k}" is required`);
        return;
      }
      if (val !== undefined && val !== "") {
        if (def.type === "number") params[k] = Number(val);
        else if (def.type === "boolean") params[k] = val === "true";
        else params[k] = val;
      }
    }

    try {
      const run = await triggerMut.mutateAsync({
        params,
        bot_id: botId || defaultBot || undefined,
      });
      onTriggered(run.id);
    } catch {
      // handled by mutation
    }
  };

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 6, padding: "6px 10px", color: t.inputText,
    fontSize: 12, outline: "none", width: "100%",
  };

  return (
    <div style={{
      padding: 12, borderRadius: 8,
      background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>Trigger Workflow</div>

      {/* Param fields generated from definitions */}
      {hasParams && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {Object.entries(paramDefs).map(([name, def]: [string, any]) => (
            <div key={name} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <label style={{ fontSize: 12, color: t.textMuted }}>
                {name}
                {def.required && <span style={{ color: t.danger }}> *</span>}
                {def.description && (
                  <span style={{ color: t.textDim, fontWeight: "normal" }}> — {def.description}</span>
                )}
              </label>
              {def.type === "boolean" ? (
                <select
                  value={paramValues[name] || ""}
                  onChange={(e) => setParamValues((p) => ({ ...p, [name]: e.target.value }))}
                  style={{ ...inputStyle, padding: "6px 8px" }}
                >
                  <option value="">— select —</option>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : (
                <input
                  value={paramValues[name] || ""}
                  onChange={(e) => setParamValues((p) => ({ ...p, [name]: e.target.value }))}
                  placeholder={def.default != null ? `default: ${def.default}` : def.required ? "required" : "optional"}
                  style={inputStyle}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Bot selector dropdown */}
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <label style={{ fontSize: 12, color: t.textMuted }}>
          Bot {defaultBot && <span style={{ color: t.textDim }}>(default: {defaultBot})</span>}
        </label>
        <select
          value={botId}
          onChange={(e) => setBotId(e.target.value)}
          style={{ ...inputStyle, padding: "6px 8px" }}
        >
          <option value="">{defaultBot ? `Default (${defaultBot})` : "— select bot —"}</option>
          {bots?.map((b) => (
            <option key={b.id} value={b.id}>{b.name || b.id}</option>
          ))}
        </select>
      </div>

      {triggerMut.isError && (
        <div style={{ color: t.danger, fontSize: 12 }}>
          {triggerMut.error?.message || "Trigger failed"}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button
          onClick={onCancel}
          style={{
            padding: "5px 12px", fontSize: 12, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6, background: "transparent", color: t.textMuted, cursor: "pointer",
          }}
        >
          Cancel
        </button>
        <button
          onClick={handleTrigger}
          disabled={triggerMut.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "5px 12px", fontSize: 12, fontWeight: 600,
            border: "none", borderRadius: 6,
            background: t.accent, color: "#fff", cursor: "pointer",
            opacity: triggerMut.isPending ? 0.6 : 1,
          }}
        >
          <Play size={13} />
          {triggerMut.isPending ? "Triggering..." : "Run"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function MetaItem({ label, value, t, mono }: { label: string; value: string; t: ThemeTokens; mono?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 12, color: t.text, fontFamily: mono ? "monospace" : undefined, marginTop: 1 }}>{value}</div>
    </div>
  );
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    if (diffMs < 60000) return "just now";
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
    if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)}h ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}
