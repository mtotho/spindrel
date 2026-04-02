import { useRef, useEffect, useState, useMemo, useCallback } from "react";
import { Pressable } from "react-native";
import { type ThemeTokens } from "@/src/theme/tokens";
import {
  Check, SkipForward, RotateCcw,
  ExternalLink, AlertTriangle, ArrowDown,
  Copy,
} from "lucide-react";
import { Link } from "expo-router";
import type { WorkflowStepState } from "@/src/types/api";
import {
  getStatusStyle, StatusBadge, describeCondition, useElapsed,
  fmtTime, formatStepDuration,
} from "./WorkflowRunHelpers";

// ---------------------------------------------------------------------------
// Feed
// ---------------------------------------------------------------------------

export default function WorkflowRunFeed({
  stepStates, steps, runStatus, runParams, runId, t,
  activeStepIndex, onStepVisible,
  onApprove, onSkip, onRetry,
  isApproving, isSkipping, isRetrying,
}: {
  stepStates: WorkflowStepState[];
  steps: { id?: string; prompt?: string; requires_approval?: boolean; on_failure?: string; when?: any }[];
  runStatus: string;
  runParams: Record<string, any>;
  runId: string;
  t: ThemeTokens;
  activeStepIndex: number | null;
  onStepVisible?: (index: number) => void;
  onApprove: (stepIndex: number) => void;
  onSkip: (stepIndex: number) => void;
  onRetry: (stepIndex: number) => void;
  isApproving: boolean;
  isSkipping: boolean;
  isRetrying: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stepRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [showJumpPill, setShowJumpPill] = useState(false);
  const hasScrolledRef = useRef(false);

  // Find first running step
  const runningIndex = useMemo(
    () => stepStates.findIndex((s) => s.status === "running"),
    [stepStates],
  );

  // Auto-scroll to running step on mount
  useEffect(() => {
    if (hasScrolledRef.current) return;
    const targetIdx = runningIndex >= 0 ? runningIndex : -1;
    if (targetIdx >= 0) {
      const el = stepRefs.current[targetIdx];
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        hasScrolledRef.current = true;
      }
    }
  }, [runningIndex]);

  // Scroll to step when nav clicks change activeStepIndex
  useEffect(() => {
    if (activeStepIndex == null) return;
    const el = stepRefs.current[activeStepIndex];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [activeStepIndex]);

  // Track whether running step is visible for "jump to active" pill
  useEffect(() => {
    if (runningIndex < 0) { setShowJumpPill(false); return; }
    const el = stepRefs.current[runningIndex];
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => setShowJumpPill(!entry.isIntersecting),
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [runningIndex]);

  const jumpToActive = useCallback(() => {
    if (runningIndex < 0) return;
    const el = stepRefs.current[runningIndex];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [runningIndex]);

  return (
    <div
      ref={containerRef}
      style={{
        flex: 1, overflow: "auto", position: "relative",
        display: "flex", flexDirection: "column", gap: 0,
      }}
    >
      {stepStates.map((state, i) => (
        <FeedSection
          key={i}
          ref={(el) => { stepRefs.current[i] = el; }}
          index={i}
          state={state}
          stepDef={steps[i]}
          runStatus={runStatus}
          runParams={runParams}
          runId={runId}
          t={t}
          isLast={i === stepStates.length - 1}
          onApprove={() => onApprove(i)}
          onSkip={() => onSkip(i)}
          onRetry={() => onRetry(i)}
          isApproving={isApproving}
          isSkipping={isSkipping}
          isRetrying={isRetrying}
        />
      ))}

      {/* Jump to active pill */}
      {showJumpPill && (
        <Pressable
          onPress={jumpToActive}
          style={{
            position: "sticky", bottom: 12,
            alignSelf: "center",
            flexDirection: "row", alignItems: "center", gap: 5,
            paddingVertical: 6, paddingHorizontal: 14, borderRadius: 20,
            backgroundColor: t.accent,
            shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 8, shadowOffset: { width: 0, height: 2 },
            elevation: 4,
          }}
        >
          <ArrowDown size={13} color="#fff" />
          <span style={{ fontSize: 12, fontWeight: 600, color: "#fff" }}>
            Jump to active step
          </span>
        </Pressable>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feed section (one per step)
// ---------------------------------------------------------------------------

import { forwardRef } from "react";

const FeedSection = forwardRef<HTMLDivElement, {
  index: number;
  state: WorkflowStepState;
  stepDef?: { id?: string; prompt?: string; requires_approval?: boolean; on_failure?: string; when?: any };
  runStatus: string;
  runParams: Record<string, any>;
  runId: string;
  t: ThemeTokens;
  isLast: boolean;
  onApprove: () => void;
  onSkip: () => void;
  onRetry: () => void;
  isApproving: boolean;
  isSkipping: boolean;
  isRetrying: boolean;
}>(function FeedSection({
  index, state, stepDef, runStatus, runParams, runId, t, isLast,
  onApprove, onSkip, onRetry, isApproving, isSkipping, isRetrying,
}, ref) {
  const stepId = stepDef?.id || `step_${index}`;
  const s = getStatusStyle(state.status, t);
  const isRunning = state.status === "running";
  const elapsed = useElapsed(state.started_at, isRunning);
  const duration = formatStepDuration(state.started_at, state.completed_at);

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

  // Stuck detection (>5 min)
  const isStuck = useMemo(() => {
    if (!isRunning || !state.started_at) return false;
    return (Date.now() - new Date(state.started_at).getTime()) > 300000;
  }, [isRunning, state.started_at, elapsed]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      ref={ref}
      style={{
        borderBottom: isLast ? "none" : `1px solid ${t.surfaceBorder}`,
        padding: "16px 16px",
      }}
    >
      {/* Step header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
      }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
          {stepId}
        </span>
        <StatusBadge status={state.status} t={t} />
        {isRunning && elapsed && (
          <span style={{ fontSize: 12, color: t.accent, fontWeight: 600 }}>
            {elapsed}
          </span>
        )}
        {!isRunning && duration && state.completed_at && (
          <span style={{ fontSize: 12, color: t.textDim }}>
            {duration}
          </span>
        )}
      </div>

      {/* Stuck warning */}
      {isStuck && (
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          marginBottom: 8, padding: 8, borderRadius: 6,
          background: t.warningSubtle, border: `1px solid ${t.warningBorder}`,
        }}>
          <AlertTriangle size={13} color={t.warning} />
          <span style={{ fontSize: 11, color: t.warning, fontWeight: 600 }}>
            Running for {elapsed} -- this step may be stuck.
          </span>
        </div>
      )}

      {/* Content block based on status */}
      {state.status === "done" && state.result && (
        <div style={{
          padding: 10, borderRadius: 6,
          background: t.successSubtle, border: `1px solid ${t.successBorder}`,
          fontSize: 13, color: t.text, whiteSpace: "pre-wrap",
          maxHeight: 400, overflow: "auto", lineHeight: 1.5,
        }}>
          {state.result}
        </div>
      )}

      {isRunning && (
        <div style={{
          padding: 10, borderRadius: 6,
          background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
          fontSize: 12, color: t.textDim, fontStyle: "italic",
        }}>
          Running...
        </div>
      )}

      {state.status === "skipped" && (
        <div style={{
          padding: 10, borderRadius: 6,
          background: t.codeBg, border: `1px solid ${t.surfaceBorder}`,
          fontSize: 12, color: t.textDim, fontStyle: "italic",
        }}>
          {skipReason ? `Skipped: ${skipReason}` : "Skipped"}
        </div>
      )}

      {state.status === "failed" && (
        <div style={{
          padding: 10, borderRadius: 6,
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
          fontSize: 13, color: t.danger, fontFamily: "monospace", whiteSpace: "pre-wrap",
        }}>
          {state.error || "Step failed"}
        </div>
      )}

      {state.status === "pending" && !isAwaitingApproval && (
        <div style={{
          padding: 10, borderRadius: 6,
          background: t.codeBg, border: `1px solid ${t.surfaceBorder}`,
          fontSize: 12, color: t.textMuted, fontStyle: "italic",
        }}>
          Waiting...
        </div>
      )}

      {isAwaitingApproval && (
        <div style={{
          padding: 10, borderRadius: 6,
          background: t.warningSubtle, border: `1px solid ${t.warningBorder}`,
          fontSize: 12, color: t.warning,
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          <span style={{ fontWeight: 600 }}>Awaiting approval</span>
          <div style={{ display: "flex", gap: 8 }}>
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
          </div>
        </div>
      )}

      {/* Failed step with result (partial output before failure) */}
      {state.status === "failed" && state.result && (
        <div style={{
          marginTop: 8, padding: 10, borderRadius: 6,
          background: t.successSubtle, border: `1px solid ${t.successBorder}`,
          fontSize: 12, color: t.text, whiteSpace: "pre-wrap",
          maxHeight: 200, overflow: "auto",
        }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: t.success, display: "block", marginBottom: 4 }}>
            Partial result
          </span>
          {state.result}
        </div>
      )}

      {/* Retry button for failed steps */}
      {canRetry && (
        <div style={{ marginTop: 8 }}>
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
        </div>
      )}

      {/* Prompt toggle */}
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
            maxHeight: 200, overflow: "auto", lineHeight: 1.5,
          }}>
            {renderedPrompt}
          </div>
        </details>
      )}

      {/* Condition (when not skipped -- skipped already shows reason inline) */}
      {stepDef?.when && state.status !== "skipped" && (
        <div style={{
          marginTop: 8, padding: 6, borderRadius: 4,
          fontSize: 11, color: t.textDim, fontStyle: "italic",
          background: t.codeBg, border: `1px solid ${t.codeBorder}`,
        }}>
          Condition: {describeCondition(stepDef.when)}
        </div>
      )}

      {/* Metadata row */}
      <div style={{ display: "flex", gap: 10, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        {state.started_at && (
          <span style={{ fontSize: 10, color: t.textMuted }}>
            Started {fmtTime(state.started_at)}
          </span>
        )}
        {state.completed_at && (
          <span style={{ fontSize: 10, color: t.textMuted }}>
            Completed {fmtTime(state.completed_at)}
          </span>
        )}
        {state.retry_count != null && state.retry_count > 0 && (
          <span style={{ fontSize: 10, color: t.warning }}>
            {state.retry_count} {state.retry_count === 1 ? "retry" : "retries"}
          </span>
        )}
        {state.task_id && (
          <CopyBadge value={state.task_id} label={`Task: ${state.task_id.slice(0, 8)}`} t={t} />
        )}
        {state.correlation_id && (
          <Link href={`/admin/logs/${state.correlation_id}` as any}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 10, color: t.accent }}>
              <ExternalLink size={9} />
              Trace
            </span>
          </Link>
        )}
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Copyable badge (for task ID)
// ---------------------------------------------------------------------------

function CopyBadge({ value, label, t }: { value: string; label: string; t: ThemeTokens }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <Pressable onPress={handleCopy} style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 3,
        fontSize: 10, color: t.textMuted, fontFamily: "monospace",
        padding: "1px 5px", borderRadius: 3,
        background: t.codeBg, border: `1px solid ${t.codeBorder}`,
        cursor: "pointer",
      }}>
        <Copy size={8} />
        {copied ? "Copied!" : label}
      </span>
    </Pressable>
  );
}
