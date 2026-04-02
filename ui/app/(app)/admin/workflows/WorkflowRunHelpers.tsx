import { useState, useEffect, useMemo } from "react";
import { Pressable } from "react-native";
import { type ThemeTokens } from "@/src/theme/tokens";
import {
  X, Check, SkipForward, RotateCcw, Clock,
  CheckCircle2, XCircle, Loader2, ShieldCheck, CircleDot, Minus,
  ChevronDown, ChevronRight, ExternalLink, AlertTriangle,
} from "lucide-react";
import { Link } from "expo-router";
import type { WorkflowStepState } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Status styling
// ---------------------------------------------------------------------------

export function getStatusStyle(status: string, t: ThemeTokens) {
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

export function StatusBadge({ status, t }: { status: string; t: ThemeTokens }) {
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

export function describeCondition(when: any): string {
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

export function useElapsed(startedAt?: string | null, isRunning?: boolean) {
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
// Helpers
// ---------------------------------------------------------------------------

export function fmtTime(iso: string): string {
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

export function MetaItem({ label, value, t, mono }: { label: string; value: string; t: ThemeTokens; mono?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 12, color: t.text, fontFamily: mono ? "monospace" : undefined, marginTop: 1 }}>{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step card with expand/collapse
// ---------------------------------------------------------------------------

export function StepCard({
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

  const renderedPrompt = useMemo(() => {
    if (!stepDef?.prompt) return null;
    let p = stepDef.prompt;
    for (const [k, v] of Object.entries(runParams)) {
      p = p.replaceAll(`{{${k}}}`, String(v));
    }
    return p.slice(0, 800);
  }, [stepDef?.prompt, runParams]);

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
          {!expanded && skipReason && (
            <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>
              Skipped: {skipReason}
            </div>
          )}
          {!expanded && state.result && (
            <div style={{
              fontSize: 11, color: t.success, marginTop: 2,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {state.result.slice(0, 120)}
            </div>
          )}
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

          {isStepRunning && elapsed && parseInt(elapsed) > 0 && (
            (() => {
              const startMs = new Date(state.started_at!).getTime();
              const elapsedMs = Date.now() - startMs;
              if (elapsedMs > 300000) {
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

          {stepDef?.when && state.status !== "skipped" && (
            <div style={{
              marginTop: 8, padding: 6, borderRadius: 4,
              fontSize: 11, color: t.textDim, fontStyle: "italic",
              background: t.codeBg, border: `1px solid ${t.codeBorder}`,
            }}>
              Condition: {describeCondition(stepDef.when)}
            </div>
          )}

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
                background: t.codeBg, border: `1px solid ${t.codeBorder}`,
                fontSize: 12, color: t.textMuted,
                fontFamily: "monospace", whiteSpace: "pre-wrap",
                maxHeight: 200, overflow: "auto",
                lineHeight: 1.5,
              }}>
                {renderedPrompt}
              </div>
            </details>
          )}

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
