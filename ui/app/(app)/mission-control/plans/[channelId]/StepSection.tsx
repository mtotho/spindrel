import { Pressable } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import type { MCPlanStep } from "@/src/api/hooks/useMissionControl";
import {
  StepIcon,
  StepStatusBadge,
} from "@/src/components/mission-control/PlanComponents";
import { getStepStatusStyle } from "@/src/components/mission-control/planConstants";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  ShieldAlert,
  SkipForward,
  ExternalLink,
  Layers,
  Check,
} from "lucide-react";
import { formatDuration, fmtTime } from "./planHelpers";

// ---------------------------------------------------------------------------
// Step feed section (one step = one section, like WorkflowRunFeed)
// ---------------------------------------------------------------------------
export function StepSection({
  step,
  plan,
  onApproveStep,
  onSkipStep,
  isApprovePending,
  isSkipPending,
  isLast,
}: {
  step: MCPlanStep;
  plan: { status: string; channel_id: string; id: string; steps: MCPlanStep[] };
  onApproveStep: () => void;
  onSkipStep: () => void;
  isApprovePending: boolean;
  isSkipPending: boolean;
  isLast: boolean;
}) {
  const t = useThemeTokens();
  const ss = getStepStatusStyle(step.status, t);

  const isTerminal = step.status === "done" || step.status === "skipped" || step.status === "failed";
  const isGated = step.requires_approval && !isTerminal;
  const isAwaitingApproval = plan.status === "awaiting_approval";
  const nextStep = plan.steps.find((s) => s.status === "pending" || s.status === "in_progress");
  const isNext = nextStep?.position === step.position && (plan.status === "executing" || isAwaitingApproval);
  const needsStepApproval = isAwaitingApproval && isNext && isGated;
  const canSkip = step.status === "pending" && (plan.status === "executing" || plan.status === "awaiting_approval");

  const duration = step.started_at && step.completed_at
    ? formatDuration(step.started_at, step.completed_at)
    : null;

  return (
    <div style={{ borderBottom: isLast ? "none" : `1px solid ${t.surfaceBorder}`, padding: "14px 16px" }}>
      {/* Step header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <StepIcon status={step.status} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>
          Step {step.position}
        </span>
        <StepStatusBadge status={step.status} />
        {step.status === "in_progress" && step.started_at && (
          <span style={{ fontSize: 11, color: t.accent, fontWeight: 600 }}>
            {fmtTime(step.started_at)}
          </span>
        )}
        {duration && (
          <span style={{ fontSize: 11, color: t.textDim }}>{duration}</span>
        )}
      </div>

      {/* Step content */}
      <div style={{
        fontSize: 13,
        color: step.status === "skipped" ? t.textDim : t.text,
        lineHeight: 1.5,
        textDecorationLine: step.status === "skipped" ? "line-through" : "none",
        marginBottom: 8,
      }}>
        {step.content}
      </div>

      {/* Approval gate UI */}
      {needsStepApproval && (
        <div style={{
          padding: 10,
          borderRadius: 6,
          background: "rgba(168,85,247,0.06)",
          border: "1px solid rgba(168,85,247,0.15)",
          display: "flex",
          flexDirection: "column",
          gap: 8,
          marginBottom: 8,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <ShieldAlert size={13} color="#a855f7" />
            <span style={{ fontSize: 12, fontWeight: 600, color: "#a855f7" }}>
              Awaiting approval
            </span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={onApproveStep}
              disabled={isApprovePending}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "5px 12px", fontSize: 12, fontWeight: 600,
                border: "none", borderRadius: 6,
                background: t.success, color: "#fff", cursor: "pointer",
                opacity: isApprovePending ? 0.6 : 1,
              }}
            >
              <Check size={13} />
              Approve
            </button>
            <button
              onClick={onSkipStep}
              disabled={isSkipPending}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "5px 12px", fontSize: 12, fontWeight: 600,
                border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                background: "transparent", color: t.textMuted, cursor: "pointer",
                opacity: isSkipPending ? 0.6 : 1,
              }}
            >
              <SkipForward size={13} />
              Skip
            </button>
          </div>
        </div>
      )}

      {/* Result summary */}
      {step.result_summary && (
        <div style={{
          padding: 10,
          borderRadius: 6,
          background: step.status === "failed" ? t.dangerSubtle : t.successSubtle,
          border: `1px solid ${step.status === "failed" ? t.dangerBorder : t.successBorder}`,
          fontSize: 12,
          color: t.text,
          whiteSpace: "pre-wrap",
          lineHeight: 1.5,
          maxHeight: 300,
          overflow: "auto",
          marginBottom: 8,
        }}>
          {step.status === "failed" && (
            <div style={{ fontSize: 11, fontWeight: 600, color: t.danger, marginBottom: 4 }}>Error</div>
          )}
          {step.result_summary}
        </div>
      )}

      {/* Metadata row */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        {step.started_at && (
          <span style={{ fontSize: 10, color: t.textMuted }}>
            Started {fmtTime(step.started_at)}
          </span>
        )}
        {step.completed_at && (
          <span style={{ fontSize: 10, color: t.textMuted }}>
            Completed {fmtTime(step.completed_at)}
          </span>
        )}
        {isGated && !needsStepApproval && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            fontSize: 10, color: "#a855f7",
          }}>
            <ShieldAlert size={9} />
            Requires approval
          </span>
        )}
        {canSkip && !needsStepApproval && (
          <button
            onClick={onSkipStep}
            disabled={isSkipPending}
            style={{
              display: "inline-flex", alignItems: "center", gap: 3,
              fontSize: 10, color: t.textDim, background: "none",
              border: "none", cursor: "pointer", padding: 0,
              opacity: isSkipPending ? 0.4 : 0.7,
            }}
          >
            <SkipForward size={9} />
            Skip
          </button>
        )}
        {step.task_id && (
          <Pressable
            onPress={() => writeToClipboard(step.task_id!)}
            style={{ flexDirection: "row", alignItems: "center", gap: 3 }}
          >
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 3,
              fontSize: 10, color: t.textMuted, fontFamily: "monospace",
              padding: "1px 5px", borderRadius: 3,
              background: t.codeBg, border: `1px solid ${t.codeBorder}`,
              cursor: "pointer",
            }}>
              <ExternalLink size={8} />
              Task: {step.task_id.slice(0, 8)}
            </span>
          </Pressable>
        )}
        {step.linked_card_id && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            fontSize: 10, color: t.accent, fontFamily: "monospace",
            padding: "1px 5px", borderRadius: 3,
            background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
          }}>
            <Layers size={8} />
            Card: {step.linked_card_id.slice(0, 8)}
          </span>
        )}
      </div>
    </div>
  );
}
