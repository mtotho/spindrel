import { useRef, useEffect, useState, useMemo, useCallback, forwardRef } from "react";

import { type ThemeTokens } from "@/src/theme/tokens";
import {
  Check, SkipForward, RotateCcw,
  ExternalLink, AlertTriangle, ArrowDown,
  Copy, Zap, Terminal,
} from "lucide-react";
import { Link } from "react-router-dom";
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
  pendingApproveStep, pendingSkipStep, pendingRetryStep,
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
  pendingApproveStep: number | null;
  pendingSkipStep: number | null;
  pendingRetryStep: number | null;
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
          isApproving={pendingApproveStep === i}
          isSkipping={pendingSkipStep === i}
          isRetrying={pendingRetryStep === i}
        />
      ))}

      {/* Jump to active pill */}
      {showJumpPill && (
        <button type="button"
          onClick={jumpToActive}
          style={{
            position: "sticky", bottom: 12,
            alignSelf: "center",
            flexDirection: "row", alignItems: "center", gap: 5,
            paddingBlock: 6, paddingInline: 14, borderRadius: 20,
            backgroundColor: t.accent,
            boxShadow: "0px 2px 8px rgba(0,0,0,0.15)",
          }}
        >
          <ArrowDown size={13} color="#fff" />
          <span style={{ fontSize: 12, fontWeight: 600, color: "#fff" }}>
            Jump to active step
          </span>
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsible result block — collapses long results by default
// ---------------------------------------------------------------------------

const COLLAPSE_THRESHOLD = 300; // chars

function CollapsibleResult({ result, t, variant }: {
  result: string;
  t: ThemeTokens;
  variant: "success" | "partial";
}) {
  const [expanded, setExpanded] = useState(result.length <= COLLAPSE_THRESHOLD);
  const isSuccess = variant === "success";
  const bg = isSuccess ? t.successSubtle : t.warningSubtle;
  const border = isSuccess ? t.successBorder : t.warningBorder;
  const labelColor = isSuccess ? t.success : t.warning;

  return (
    <div style={{
      padding: 10, borderRadius: 6,
      background: bg,
      border: `1px solid ${border}`,
      fontSize: 13, color: t.text, lineHeight: 1.5,
    }}>
      {variant === "partial" && (
        <span style={{ fontSize: 11, fontWeight: 600, color: labelColor, display: "block", marginBottom: 4 }}>
          Partial result
        </span>
      )}
      <div style={{
        whiteSpace: "pre-wrap",
        maxHeight: expanded ? 400 : 80,
        overflow: "hidden",
        position: "relative",
      }}>
        {result}
        {!expanded && result.length > COLLAPSE_THRESHOLD && (
          <div style={{
            position: "absolute", bottom: 0, left: 0, right: 0,
            height: 40,
            background: `linear-gradient(transparent, ${bg})`,
          }} />
        )}
      </div>
      {result.length > COLLAPSE_THRESHOLD && (
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            background: "none", border: "none", color: t.accent,
            fontSize: 11, cursor: "pointer", padding: 0, marginTop: 4,
          }}
        >
          {expanded ? "Collapse" : `Show all (${result.length} chars)`}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feed section (one per step)
// ---------------------------------------------------------------------------

const FeedSection = forwardRef<HTMLDivElement, {
  index: number;
  state: WorkflowStepState;
  stepDef?: { id?: string; type?: string; prompt?: string; tool_name?: string; requires_approval?: boolean; on_failure?: string; when?: any };
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
  const isPending = state.status === "pending";
  const elapsed = useElapsed(state.started_at, isRunning);
  const duration = formatStepDuration(state.started_at, state.completed_at);

  const isAwaitingApproval = runStatus === "awaiting_approval" &&
    state.status === "pending" && stepDef?.requires_approval;
  const canRetry = state.status === "failed";

  // Status-colored left border
  const borderColor = (() => {
    switch (state.status) {
      case "done": return t.success;
      case "complete": return t.success;
      case "running": return t.accent;
      case "failed": return t.danger;
      case "awaiting_approval": return t.warning;
      case "skipped": return t.surfaceBorder;
      default: return t.surfaceBorder;
    }
  })();

  const renderedPrompt = useMemo(() => {
    if (stepDef?.type === "tool") {
      return stepDef.tool_name ? `Tool: ${stepDef.tool_name}` : null;
    }
    if (!stepDef?.prompt) return null;
    let p = stepDef.prompt;
    for (const [k, v] of Object.entries(runParams)) {
      p = p.replaceAll(`{{${k}}}`, String(v));
    }
    return p.slice(0, 800);
  }, [stepDef?.prompt, stepDef?.type, stepDef?.tool_name, runParams]);

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
        borderLeft: `3px solid ${borderColor}`,
        padding: "16px 16px",
        opacity: isPending && !isAwaitingApproval ? 0.55 : 1,
      }}
    >
      {/* Step header */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8,
        padding: "4px 8px", borderRadius: 4,
        background: isPending && !isAwaitingApproval ? "transparent" : s.bg,
      }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
          {stepId}
        </span>
        {(stepDef?.type === "tool" || stepDef?.type === "exec") && (
          <span style={{
            fontSize: 10, padding: "1px 5px", borderRadius: 3,
            display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
            whiteSpace: "nowrap",
            ...(stepDef.type === "tool"
              ? { background: t.purpleSubtle, border: `1px solid ${t.purpleBorder}`, color: t.purple }
              : { background: t.warningSubtle, border: `1px solid ${t.warningBorder}`, color: t.warning }
            ),
          }}>
            {stepDef.type === "tool" ? <Zap size={10} /> : <Terminal size={10} />}
            {stepDef.type}
          </span>
        )}
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
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
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
        <CollapsibleResult result={state.result} t={t} variant="success" />
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
          <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
            <button
              onClick={onApprove}
              disabled={isApproving}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
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
                display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
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
        <div style={{ marginTop: 8 }}>
          <CollapsibleResult result={state.result} t={t} variant="partial" />
        </div>
      )}

      {/* Retry button for failed steps */}
      {canRetry && (
        <div style={{ marginTop: 8 }}>
          <button
            onClick={onRetry}
            disabled={isRetrying}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
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
      <div style={{ display: "flex", flexDirection: "row", gap: 10, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
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
          <TaskLink taskId={state.task_id} correlationId={state.correlation_id} t={t} />
        )}
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Clickable task link (navigates to task detail + copy button)
// ---------------------------------------------------------------------------

function TaskLink({ taskId, correlationId, t }: { taskId: string; correlationId?: string | null; t: ThemeTokens }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    navigator.clipboard.writeText(taskId);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Prefer trace view when available — task editor is useless for ephemeral tasks
  const href = correlationId
    ? `/admin/logs/${correlationId}`
    : `/admin/tasks/${taskId}`;

  return (
    <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
      <Link to={href}>
        <span style={{
          display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
          fontSize: 10, color: t.accent, fontFamily: "monospace",
          padding: "1px 5px", borderRadius: 3,
          background: t.codeBg, border: `1px solid ${t.codeBorder}`,
          cursor: "pointer",
        }}>
          <ExternalLink size={8} />
          Task: {taskId.slice(0, 8)}
        </span>
      </Link>
      <button type="button" onClick={handleCopy as any} style={{ padding: 2 }}>
        <Copy size={9} color={copied ? t.success : t.textMuted} />
      </button>
    </span>
  );
}
