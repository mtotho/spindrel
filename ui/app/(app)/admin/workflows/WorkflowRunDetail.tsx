import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator, useWindowDimensions } from "react-native";
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
import { Link } from "expo-router";

import {
  StatusBadge, fmtTime, MetaItem, StepNavItem, StepNavStrip,
} from "./WorkflowRunHelpers";
import WorkflowRunFeed from "./WorkflowRunFeed";

// ---------------------------------------------------------------------------
// Run detail (split-panel: step nav + feed)
// ---------------------------------------------------------------------------

export default function WorkflowRunDetail({ runId, workflowId, onBack, onNavigateToRun }: {
  runId: string;
  workflowId: string;
  onBack: () => void;
  onNavigateToRun: (id: string) => void;
}) {
  const t = useThemeTokens();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;

  const { data: run, isLoading } = useWorkflowRun(runId);
  const { data: workflow } = useWorkflow(workflowId);
  const cancelMut = useCancelWorkflowRun();
  const triggerMut = useTriggerWorkflow(workflowId);
  const approveMut = useApproveWorkflowStep();
  const skipMut = useSkipWorkflowStep();
  const retryMut = useRetryWorkflowStep();

  const [activeStepIndex, setActiveStepIndex] = useState<number | null>(null);

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
      onNavigateToRun(newRun.id);
    } catch {
      // handled by mutation
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        paddingBottom: 12, flexShrink: 0,
      }}>
        <Pressable
          onPress={onBack}
          style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
        >
          <ArrowLeft size={16} color={t.textMuted} />
          <Text style={{ color: t.textMuted, fontSize: 13 }}>All runs</Text>
        </Pressable>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <StatusBadge status={run.status} t={t} />
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
        display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
        gap: 8, padding: 12, borderRadius: 8, flexShrink: 0,
        background: t.codeBg, border: `1px solid ${t.surfaceBorder}`,
        marginBottom: 12,
      }}>
        <MetaItem label="Run ID" value={run.id.slice(0, 8)} t={t} mono />
        <MetaItem label="Bot" value={run.bot_id} t={t} />
        <MetaItem label="Triggered by" value={run.triggered_by || "\u2014"} t={t} />
        <MetaItem label="Started" value={fmtTime(run.created_at)} t={t} />
        {run.completed_at && <MetaItem label="Completed" value={fmtTime(run.completed_at)} t={t} />}
        {run.channel_id && (
          <div>
            <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>Channel</div>
            <Link href={`/channels/${run.channel_id}` as any}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 12, color: t.accent, marginTop: 1 }}>
                <MessageSquare size={11} />
                {run.channel_id.slice(0, 8)}
              </span>
            </Link>
          </div>
        )}
      </div>

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
          background: t.codeBg, border: `1px solid ${t.surfaceBorder}`,
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>
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

      {/* Mobile: horizontal step strip */}
      {isMobile && (
        <div style={{
          flexShrink: 0, marginBottom: 8,
          borderRadius: 8, overflow: "hidden",
          border: `1px solid ${t.surfaceBorder}`, background: t.codeBg,
        }}>
          <StepNavStrip
            steps={steps}
            stepStates={run.step_states}
            activeIndex={activeStepIndex ?? -1}
            onSelect={(i) => setActiveStepIndex(i)}
            t={t}
          />
        </div>
      )}

      {/* Split panel */}
      <div style={{
        display: "flex",
        flexDirection: isMobile ? "column" : "row",
        flex: 1, minHeight: 0,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8, overflow: "hidden",
        background: t.codeBg,
      }}>
        {/* Step nav sidebar (desktop) */}
        {!isMobile && (
          <div style={{
            width: 200, flexShrink: 0, overflow: "auto",
            borderRight: `1px solid ${t.surfaceBorder}`,
            display: "flex", flexDirection: "column",
          }}>
            <div style={{
              padding: "8px 10px", fontSize: 10, fontWeight: 600,
              color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5,
              borderBottom: `1px solid ${t.surfaceBorder}`,
            }}>
              Steps
            </div>
            {run.step_states.map((state, i) => (
              <StepNavItem
                key={i}
                stepId={steps[i]?.id || `step_${i}`}
                state={state}
                isActive={activeStepIndex === i}
                onPress={() => setActiveStepIndex(i)}
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
          isApproving={approveMut.isPending}
          isSkipping={skipMut.isPending}
          isRetrying={retryMut.isPending}
        />
      </div>
    </div>
  );
}
