import { useState, useCallback } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCPlan,
  useMCPlanApprove,
  useMCPlanReject,
  useMCPlanResume,
  useMCPlanStepApprove,
  useMCPlanStepSkip,
  useMCPlanUpdate,
  useMCPlanDelete,
} from "@/src/api/hooks/useMissionControl";
import { channelColor } from "@/src/components/mission-control/botColors";
import { StatusBadge, StepIcon, ProgressBar } from "@/src/components/mission-control/PlanComponents";
import {
  StepListEditor,
  makeStepKey,
  type StepDraft,
} from "@/src/components/mission-control/StepListEditor";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  Play,
  X,
  StepForward,
  ShieldCheck,
  ShieldAlert,
  Copy,
  Trash2,
  SkipForward,
  Pencil,
  ExternalLink,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Duration / time helpers
// ---------------------------------------------------------------------------
function formatDuration(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (ms < 0) return "";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (minutes < 60) return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

function timeAgo(isoDate: string): string {
  const ms = Date.now() - new Date(isoDate).getTime();
  if (ms < 0) return "just now";
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function PlanDetailPage() {
  const { channelId, planId } = useLocalSearchParams<{
    channelId: string;
    planId: string;
  }>();
  const goBack = useGoBack("/mission-control/plans");
  const t = useThemeTokens();

  const { data: plan, isLoading, error } = useMCPlan(channelId, planId);
  const { refreshing, onRefresh } = usePageRefresh([["mc-plan", channelId, planId], ["mc-plans"]]);

  const approve = useMCPlanApprove();
  const reject = useMCPlanReject();
  const resume = useMCPlanResume();
  const stepApprove = useMCPlanStepApprove();
  const skipStep = useMCPlanStepSkip();
  const updatePlan = useMCPlanUpdate();
  const deletePlan = useMCPlanDelete();

  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmReject, setConfirmReject] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editSteps, setEditSteps] = useState<StepDraft[]>([]);

  const startEdit = useCallback(() => {
    if (!plan) return;
    setEditTitle(plan.title);
    setEditNotes(plan.notes);
    setEditSteps(
      plan.steps.map((s) => ({
        key: makeStepKey(),
        content: s.content,
        requires_approval: s.requires_approval,
      }))
    );
    setEditing(true);
  }, [plan]);

  const saveEdit = useCallback(() => {
    if (!plan || !channelId || !planId) return;
    const canSave = editTitle.trim() && editSteps.length > 0 && editSteps.every((s) => s.content.trim());
    if (!canSave) return;
    updatePlan.mutate(
      {
        channelId,
        planId,
        title: editTitle.trim(),
        notes: editNotes.trim(),
        steps: editSteps.map((s) => ({
          content: s.content.trim(),
          requires_approval: s.requires_approval,
        })),
      },
      {
        onSuccess: () => setEditing(false),
        onError: (e: Error) => setActionError(`Save failed: ${e.message}`),
      }
    );
  }, [plan, channelId, planId, editTitle, editNotes, editSteps, updatePlan]);

  if (!channelId || !planId) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <Text className="text-text-muted">Invalid plan URL</Text>
      </View>
    );
  }

  const cc = plan ? channelColor(plan.channel_id) : "#888";

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title={plan?.title || "Plan Detail"}
        subtitle={plan?.channel_name}
        onBack={goBack}
      />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{
          paddingLeft: 24,
          paddingRight: 16,
          paddingTop: 20,
          gap: 20,
          paddingBottom: 48,
          maxWidth: 960,
        }}
      >
        {isLoading ? (
          <View className="items-center py-12">
            <ActivityIndicator size="large" />
          </View>
        ) : error ? (
          <View
            className="rounded-lg p-4"
            style={{ backgroundColor: "rgba(239,68,68,0.06)", borderWidth: 1, borderColor: "rgba(239,68,68,0.15)" }}
          >
            <Text style={{ fontSize: 13, fontWeight: "600", color: "#ef4444" }}>
              Failed to load plan
            </Text>
            <Text style={{ fontSize: 12, color: "#dc2626", marginTop: 4 }}>
              {(error as any)?.message || "Plan not found"}
            </Text>
          </View>
        ) : plan ? (
          <>
            {/* Metadata */}
            <View style={{ gap: 10 }}>
              {editing ? (
                <View style={{ gap: 4 }}>
                  <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "600" }}>Title</Text>
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    style={{
                      fontSize: 16,
                      fontWeight: "700",
                      color: t.text,
                      backgroundColor: t.surfaceOverlay,
                      border: `1px solid ${t.surfaceBorder}`,
                      borderRadius: 6,
                      padding: "8px 10px",
                      outline: "none",
                      fontFamily: "inherit",
                    }}
                  />
                </View>
              ) : (
                <Text style={{ fontSize: 18, fontWeight: "700", color: t.text }}>
                  {plan.title}
                </Text>
              )}
              <View className="flex-row items-center gap-3 flex-wrap">
                <StatusBadge status={plan.status} />
                <View className="flex-row items-center gap-1.5">
                  <View
                    style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: cc }}
                  />
                  <Text style={{ fontSize: 12, color: t.textDim }}>{plan.channel_name}</Text>
                </View>
                <Pressable
                  onPress={() => writeToClipboard(plan.id)}
                  className="flex-row items-center gap-1"
                >
                  <Text style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
                    {plan.id}
                  </Text>
                  <Copy size={10} color={t.textDim} />
                </Pressable>
              </View>

              {/* Dates */}
              <View className="flex-row items-center gap-4 flex-wrap">
                {plan.created_at && (
                  <Text style={{ fontSize: 11, color: t.textDim }}>
                    Created: {formatDate(plan.created_at)}
                  </Text>
                )}
                {plan.meta.approved && (
                  <Text style={{ fontSize: 11, color: t.textDim }}>
                    Approved: {plan.meta.approved}
                  </Text>
                )}
                {plan.updated_at && (
                  <Text style={{ fontSize: 11, color: t.textDim }}>
                    Updated: {formatDate(plan.updated_at)}
                  </Text>
                )}
              </View>

              <ProgressBar steps={plan.steps} />
            </View>

            {/* Actions */}
            <View className="flex-row items-center gap-2 flex-wrap">
              {plan.status === "draft" && !editing && (
                <>
                  <Pressable
                    onPress={() =>
                      approve.mutate(
                        { channelId: plan.channel_id, planId: plan.id },
                        { onError: (e: Error) => setActionError(`Approve failed: ${e.message}`) }
                      )
                    }
                    disabled={approve.isPending}
                    className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                    style={{
                      backgroundColor: "rgba(34,197,94,0.15)",
                      borderWidth: 1,
                      borderColor: "rgba(34,197,94,0.4)",
                      opacity: approve.isPending ? 0.5 : 1,
                    }}
                  >
                    <Play size={12} color="#22c55e" />
                    <Text style={{ fontSize: 12, fontWeight: "600", color: "#22c55e" }}>Approve</Text>
                  </Pressable>
                  <Pressable
                    onPress={() => {
                      if (!confirmReject) { setConfirmReject(true); return; }
                      setConfirmReject(false);
                      reject.mutate(
                        { channelId: plan.channel_id, planId: plan.id },
                        { onError: (e: Error) => setActionError(`Reject failed: ${e.message}`) }
                      );
                    }}
                    disabled={reject.isPending}
                    className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                    style={{
                      backgroundColor: confirmReject ? "rgba(239,68,68,0.25)" : "rgba(239,68,68,0.1)",
                      borderWidth: 1,
                      borderColor: confirmReject ? "rgba(239,68,68,0.6)" : "rgba(239,68,68,0.3)",
                      opacity: reject.isPending ? 0.5 : 1,
                    }}
                  >
                    <X size={12} color="#ef4444" />
                    <Text style={{ fontSize: 12, fontWeight: "600", color: "#ef4444" }}>
                      {confirmReject ? "Confirm" : "Reject"}
                    </Text>
                  </Pressable>
                  {confirmReject && (
                    <Pressable onPress={() => setConfirmReject(false)} className="rounded-lg px-2 py-1.5">
                      <Text style={{ fontSize: 11, color: t.textDim }}>Cancel</Text>
                    </Pressable>
                  )}
                </>
              )}
              {plan.status === "executing" && (
                <Pressable
                  onPress={() =>
                    resume.mutate(
                      { channelId: plan.channel_id, planId: plan.id },
                      { onError: (e: Error) => setActionError(`Resume failed: ${e.message}`) }
                    )
                  }
                  disabled={resume.isPending}
                  className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                  style={{
                    backgroundColor: "rgba(59,130,246,0.12)",
                    borderWidth: 1,
                    borderColor: "rgba(59,130,246,0.35)",
                    opacity: resume.isPending ? 0.5 : 1,
                  }}
                >
                  <StepForward size={12} color="#3b82f6" />
                  <Text style={{ fontSize: 12, fontWeight: "600", color: "#3b82f6" }}>Resume</Text>
                </Pressable>
              )}
              {/* Delete for terminal/draft */}
              {(plan.status === "draft" || plan.status === "complete" || plan.status === "abandoned") && (
                <>
                  <Pressable
                    onPress={() => {
                      if (!confirmDelete) { setConfirmDelete(true); return; }
                      setConfirmDelete(false);
                      deletePlan.mutate(
                        { channelId: plan.channel_id, planId: plan.id },
                        {
                          onSuccess: () => goBack(),
                          onError: (e: Error) => setActionError(`Delete failed: ${e.message}`),
                        }
                      );
                    }}
                    disabled={deletePlan.isPending}
                    className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                    style={{
                      backgroundColor: confirmDelete ? "rgba(239,68,68,0.2)" : "transparent",
                      borderWidth: 1,
                      borderColor: confirmDelete ? "rgba(239,68,68,0.4)" : t.surfaceBorder,
                      opacity: deletePlan.isPending ? 0.5 : 1,
                    }}
                  >
                    <Trash2 size={12} color={confirmDelete ? "#ef4444" : t.textDim} />
                    <Text style={{ fontSize: 12, fontWeight: "600", color: confirmDelete ? "#ef4444" : t.textDim }}>
                      {confirmDelete ? "Confirm Delete" : "Delete"}
                    </Text>
                  </Pressable>
                  {confirmDelete && (
                    <Pressable onPress={() => setConfirmDelete(false)} className="rounded-lg px-2 py-1.5">
                      <Text style={{ fontSize: 11, color: t.textDim }}>Cancel</Text>
                    </Pressable>
                  )}
                </>
              )}
              {/* Edit button for draft */}
              {plan.status === "draft" && !editing && (
                <Pressable
                  onPress={startEdit}
                  className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                  style={{
                    borderWidth: 1,
                    borderColor: t.surfaceBorder,
                  }}
                >
                  <Pencil size={12} color={t.textDim} />
                  <Text style={{ fontSize: 12, fontWeight: "600", color: t.textDim }}>Edit</Text>
                </Pressable>
              )}
              {/* Edit save/cancel */}
              {editing && (
                <>
                  <Pressable
                    onPress={saveEdit}
                    disabled={updatePlan.isPending}
                    className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                    style={{
                      backgroundColor: "rgba(34,197,94,0.15)",
                      borderWidth: 1,
                      borderColor: "rgba(34,197,94,0.4)",
                      opacity: updatePlan.isPending ? 0.5 : 1,
                    }}
                  >
                    <Text style={{ fontSize: 12, fontWeight: "600", color: "#22c55e" }}>Save</Text>
                  </Pressable>
                  <Pressable
                    onPress={() => setEditing(false)}
                    className="rounded-lg px-3 py-1.5"
                    style={{ borderWidth: 1, borderColor: t.surfaceBorder }}
                  >
                    <Text style={{ fontSize: 12, color: t.textDim }}>Cancel</Text>
                  </Pressable>
                </>
              )}
            </View>

            {/* Error */}
            {actionError && (
              <View
                className="rounded-lg px-3 py-2"
                style={{ backgroundColor: "rgba(239,68,68,0.1)" }}
              >
                <Text style={{ fontSize: 12, color: "#ef4444" }}>{actionError}</Text>
              </View>
            )}

            {/* Steps Timeline */}
            <View style={{ gap: 6 }}>
              <Text style={{ fontSize: 12, fontWeight: "700", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Steps
              </Text>
              {editing ? (
                <View style={{ gap: 4 }}>
                  <StepListEditor steps={editSteps} onChange={setEditSteps} />
                </View>
              ) : (
                <View style={{ gap: 4 }}>
                  {plan.steps.map((step) => {
                    const isTerminal = step.status === "done" || step.status === "skipped" || step.status === "failed";
                    const isGated = step.requires_approval && !isTerminal;
                    const isAwaitingApproval = plan.status === "awaiting_approval";
                    const nextStep = plan.steps.find((s) => s.status === "pending" || s.status === "in_progress");
                    const isNext = nextStep?.position === step.position && (plan.status === "executing" || isAwaitingApproval);
                    const needsStepApproval = isAwaitingApproval && isNext && isGated;
                    const canSkip = step.status === "pending" && (plan.status === "executing" || plan.status === "awaiting_approval");

                    return (
                      <View
                        key={step.position}
                        className="rounded-lg border border-surface-border"
                        style={{
                          padding: 12,
                          gap: 8,
                          backgroundColor: needsStepApproval
                            ? "rgba(168,85,247,0.04)"
                            : isNext
                              ? "rgba(59,130,246,0.04)"
                              : "transparent",
                        }}
                      >
                        {/* Step header */}
                        <View className="flex-row items-start gap-2">
                          <View style={{ marginTop: 1 }}>
                            <StepIcon status={step.status} />
                          </View>
                          <View style={{ flex: 1, gap: 4 }}>
                            <Text
                              style={{
                                fontSize: 13,
                                color: step.status === "failed" ? "#ef4444" : isTerminal ? t.textDim : t.text,
                                lineHeight: 18,
                                fontWeight: isNext ? "600" : "400",
                                textDecorationLine: step.status === "skipped" ? "line-through" : "none",
                              }}
                            >
                              {step.position}. {step.content}
                            </Text>

                            {/* Timestamps */}
                            <View className="flex-row items-center gap-3 flex-wrap">
                              {step.started_at && (
                                <Text style={{ fontSize: 10, color: t.textDim }}>
                                  Started: {formatDate(step.started_at)}
                                </Text>
                              )}
                              {step.completed_at && (
                                <Text style={{ fontSize: 10, color: t.textDim }}>
                                  Completed: {formatDate(step.completed_at)}
                                </Text>
                              )}
                              {step.started_at && step.completed_at && (
                                <Text style={{ fontSize: 10, color: "#3b82f6", fontWeight: "600" }}>
                                  {formatDuration(step.started_at, step.completed_at)}
                                </Text>
                              )}
                              {step.started_at && !step.completed_at && step.status === "in_progress" && (
                                <Text style={{ fontSize: 10, color: "#3b82f6" }}>
                                  started {timeAgo(step.started_at)}
                                </Text>
                              )}
                            </View>
                          </View>

                          <View className="flex-row items-center gap-1">
                            {isGated && <ShieldAlert size={13} color="#a855f7" />}
                            {step.task_id && (
                              <Pressable
                                onPress={() => writeToClipboard(step.task_id!)}
                                style={{ padding: 2 }}
                                accessibilityLabel="Copy task ID"
                              >
                                <ExternalLink size={11} color={t.textDim} />
                              </Pressable>
                            )}
                            {canSkip && (
                              <Pressable
                                onPress={() => {
                                  setActionError(null);
                                  skipStep.mutate(
                                    { channelId: plan.channel_id, planId: plan.id, position: step.position },
                                    { onError: (e: Error) => setActionError(`Skip failed: ${e.message}`) },
                                  );
                                }}
                                disabled={skipStep.isPending}
                                style={{ padding: 2, opacity: skipStep.isPending ? 0.4 : 0.6 }}
                                accessibilityLabel="Skip step"
                              >
                                <SkipForward size={13} color={t.textDim} />
                              </Pressable>
                            )}
                          </View>
                        </View>

                        {/* Step approve */}
                        {needsStepApproval && (
                          <View className="flex-row items-center gap-2" style={{ paddingLeft: 22 }}>
                            <Pressable
                              onPress={() => {
                                setActionError(null);
                                stepApprove.mutate(
                                  { channelId: plan.channel_id, planId: plan.id, position: step.position },
                                  { onError: (e: Error) => setActionError(`Step approve failed: ${e.message}`) },
                                );
                              }}
                              disabled={stepApprove.isPending}
                              className="flex-row items-center gap-1.5 rounded-lg px-3 py-1"
                              style={{
                                backgroundColor: "rgba(168,85,247,0.12)",
                                borderWidth: 1,
                                borderColor: "rgba(168,85,247,0.35)",
                                opacity: stepApprove.isPending ? 0.5 : 1,
                              }}
                            >
                              <ShieldCheck size={11} color="#a855f7" />
                              <Text style={{ fontSize: 11, fontWeight: "600", color: "#a855f7" }}>
                                Approve Step
                              </Text>
                            </Pressable>
                            <Text style={{ fontSize: 10, color: t.textDim }}>
                              Requires human approval
                            </Text>
                          </View>
                        )}

                        {/* Result summary */}
                        {step.result_summary && (
                          <View
                            className="rounded-md px-2 py-1"
                            style={{
                              marginLeft: 22,
                              backgroundColor: step.status === "failed"
                                ? "rgba(239,68,68,0.06)"
                                : "rgba(34,197,94,0.06)",
                            }}
                          >
                            <Text
                              style={{
                                fontSize: 11,
                                color: step.status === "failed" ? "#ef4444" : "#22c55e",
                                lineHeight: 15,
                              }}
                            >
                              {step.result_summary}
                            </Text>
                          </View>
                        )}
                      </View>
                    );
                  })}
                </View>
              )}
            </View>

            {/* Notes */}
            <View style={{ gap: 6 }}>
              <Text style={{ fontSize: 12, fontWeight: "700", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Notes
              </Text>
              {editing ? (
                <textarea
                  value={editNotes}
                  onChange={(e) => setEditNotes(e.target.value)}
                  placeholder="Context, rationale, estimates..."
                  rows={3}
                  style={{
                    fontSize: 13,
                    color: t.text,
                    backgroundColor: t.surfaceOverlay,
                    border: `1px solid ${t.surfaceBorder}`,
                    borderRadius: 6,
                    padding: "8px 10px",
                    outline: "none",
                    fontFamily: "inherit",
                    resize: "vertical",
                  }}
                />
              ) : plan.notes ? (
                <View
                  className="rounded-lg px-3 py-2"
                  style={{ backgroundColor: t.surfaceOverlay }}
                >
                  <Text style={{ fontSize: 13, color: t.textDim, lineHeight: 19 }}>
                    {plan.notes}
                  </Text>
                </View>
              ) : (
                <Text style={{ fontSize: 12, color: t.textDim, fontStyle: "italic" }}>
                  No notes
                </Text>
              )}
            </View>
          </>
        ) : null}
      </RefreshableScrollView>
    </View>
  );
}
