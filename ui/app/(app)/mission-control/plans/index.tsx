import { useState, useMemo, useCallback } from "react";
import { View, Text, Pressable } from "react-native";
import { useRouter } from "expo-router";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCPlans,
  useMCPrefs,
  useMCOverview,
  useMCPlanApprove,
  useMCPlanReject,
  useMCPlanResume,
  useMCPlanStepApprove,
  useMCPlanCreate,
  useMCPlanDelete,
  useMCPlanStepSkip,
  type MCPlan,
} from "@/src/api/hooks/useMissionControl";
import { MCEmptyState } from "@/src/components/mission-control/MCEmptyState";
import { ChannelFilterBar } from "@/src/components/mission-control/ChannelFilterBar";
import { channelColor } from "@/src/components/mission-control/botColors";
import { PlanCreateForm } from "@/src/components/mission-control/PlanCreateForm";
import { StatusBadge, StepIcon, ProgressBar } from "@/src/components/mission-control/PlanComponents";
import { STATUS_FILTERS, STATUS_LABELS } from "@/src/components/mission-control/planConstants";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  ClipboardCheck,
  ChevronDown,
  ChevronRight,
  Play,
  X,
  StepForward,
  ShieldCheck,
  ShieldAlert,
  Plus,
  Copy,
  Trash2,
  SkipForward,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Duration helper
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

// ---------------------------------------------------------------------------
// Plan card
// ---------------------------------------------------------------------------
function PlanCard({ plan }: { plan: MCPlan }) {
  const t = useThemeTokens();
  const router = useRouter();
  const cc = channelColor(plan.channel_id);
  const [expanded, setExpanded] = useState(
    plan.status === "draft" || plan.status === "executing" || plan.status === "awaiting_approval"
  );
  const [confirmReject, setConfirmReject] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const approve = useMCPlanApprove();
  const reject = useMCPlanReject();
  const resume = useMCPlanResume();
  const stepApprove = useMCPlanStepApprove();
  const deletePlan = useMCPlanDelete();
  const skipStep = useMCPlanStepSkip();

  const handleApprove = useCallback(() => {
    setError(null);
    approve.mutate(
      { channelId: plan.channel_id, planId: plan.id },
      { onError: (e: Error) => setError(`Approve failed: ${e.message}`) },
    );
  }, [approve, plan.channel_id, plan.id]);

  const handleReject = useCallback(() => {
    if (!confirmReject) {
      setConfirmReject(true);
      return;
    }
    setError(null);
    setConfirmReject(false);
    reject.mutate(
      { channelId: plan.channel_id, planId: plan.id },
      { onError: (e: Error) => setError(`Reject failed: ${e.message}`) },
    );
  }, [confirmReject, reject, plan.channel_id, plan.id]);

  const handleResume = useCallback(() => {
    setError(null);
    resume.mutate(
      { channelId: plan.channel_id, planId: plan.id },
      { onError: (e: Error) => setError(`Resume failed: ${e.message}`) },
    );
  }, [resume, plan.channel_id, plan.id]);

  const handleDelete = useCallback(() => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setError(null);
    setConfirmDelete(false);
    deletePlan.mutate(
      { channelId: plan.channel_id, planId: plan.id },
      { onError: (e: Error) => setError(`Delete failed: ${e.message}`) },
    );
  }, [confirmDelete, deletePlan, plan.channel_id, plan.id]);

  const navigateToDetail = () => {
    router.push(`/mission-control/plans/${plan.channel_id}/${plan.id}` as any);
  };

  return (
    <View
      className="rounded-xl border border-surface-border"
      style={{ overflow: "hidden" }}
    >
      {/* Header */}
      <View className="flex-row items-start">
        {/* Expand toggle */}
        <Pressable
          onPress={() => setExpanded(!expanded)}
          style={{ padding: 12, paddingRight: 4 }}
        >
          {expanded ? (
            <ChevronDown size={14} color={t.textDim} />
          ) : (
            <ChevronRight size={14} color={t.textDim} />
          )}
        </Pressable>
        {/* Clickable title → detail page */}
        <Pressable
          onPress={navigateToDetail}
          className="flex-1 hover:bg-surface-overlay py-3 pr-4"
          style={{ gap: 6 }}
        >
          <View className="flex-row items-center gap-2">
            <Text
              className="text-text font-semibold flex-1"
              numberOfLines={1}
              style={{ fontSize: 14 }}
            >
              {plan.title}
            </Text>
            <StatusBadge status={plan.status} />
          </View>
          <View className="flex-row items-center gap-3">
            <View className="flex-row items-center gap-1.5">
              <View
                style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: cc }}
              />
              <Text style={{ fontSize: 11, color: t.textDim }}>{plan.channel_name}</Text>
            </View>
            {/* Plan ID with copy */}
            <Pressable
              onPress={(e) => {
                e.stopPropagation?.();
                writeToClipboard(plan.id);
              }}
              className="flex-row items-center gap-1"
            >
              <Text style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
                {plan.id}
              </Text>
              <Copy size={9} color={t.textDim} />
            </Pressable>
            <View style={{ flex: 1 }} />
            <ProgressBar steps={plan.steps} />
          </View>
        </Pressable>
      </View>

      {/* Expanded content */}
      {expanded && (
        <View
          className="border-t border-surface-border px-4 py-3"
          style={{ gap: 10 }}
        >
          {/* Steps */}
          {plan.steps.length > 0 && (() => {
            const nextIdx = plan.steps.findIndex(
              (s) => s.status === "pending" || s.status === "in_progress"
            );
            const isAwaitingApproval = plan.status === "awaiting_approval";
            return (
              <View style={{ gap: 4 }}>
                {plan.steps.map((step, i) => {
                  const isNext = (plan.status === "executing" || isAwaitingApproval) && i === nextIdx;
                  const isTerminal = step.status === "done" || step.status === "skipped" || step.status === "failed";
                  const isGated = step.requires_approval && !isTerminal;
                  const needsStepApproval = isAwaitingApproval && isNext && isGated;
                  const canSkip = step.status === "pending" && (plan.status === "executing" || plan.status === "awaiting_approval");
                  return (
                    <View key={step.position} style={{ gap: 2 }}>
                      <View
                        className="flex-row items-start gap-2"
                        style={{
                          paddingVertical: 2,
                          paddingHorizontal: isNext ? 4 : 0,
                          backgroundColor: needsStepApproval
                            ? "rgba(168,85,247,0.06)"
                            : isNext
                              ? "rgba(59,130,246,0.06)"
                              : "transparent",
                          borderRadius: isNext ? 6 : 0,
                        }}
                      >
                        <View style={{ marginTop: 1 }}>
                          <StepIcon status={step.status} />
                        </View>
                        <View style={{ flex: 1, gap: 2 }}>
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
                          {/* Step timestamps */}
                          {step.started_at && step.completed_at && (
                            <Text style={{ fontSize: 10, color: t.textDim }}>
                              {formatDuration(step.started_at, step.completed_at)}
                            </Text>
                          )}
                          {step.started_at && !step.completed_at && step.status === "in_progress" && (
                            <Text style={{ fontSize: 10, color: "#3b82f6" }}>
                              started {timeAgo(step.started_at)}
                            </Text>
                          )}
                        </View>
                        <View className="flex-row items-center gap-1">
                          {isGated && (
                            <ShieldAlert size={13} color="#a855f7" />
                          )}
                          {canSkip && (
                            <Pressable
                              onPress={() => {
                                setError(null);
                                skipStep.mutate(
                                  { channelId: plan.channel_id, planId: plan.id, position: step.position },
                                  { onError: (e: Error) => setError(`Skip failed: ${e.message}`) },
                                );
                              }}
                              disabled={skipStep.isPending}
                              style={{ padding: 2, opacity: skipStep.isPending ? 0.4 : 0.6 }}
                              accessibilityLabel="Skip step"
                            >
                              <SkipForward size={12} color={t.textDim} />
                            </Pressable>
                          )}
                        </View>
                      </View>
                      {/* Step approve button for gated steps awaiting approval */}
                      {needsStepApproval && (
                        <View className="flex-row items-center gap-2" style={{ paddingLeft: 22 }}>
                          <Pressable
                            onPress={() => {
                              setError(null);
                              stepApprove.mutate(
                                { channelId: plan.channel_id, planId: plan.id, position: step.position },
                                { onError: (e: Error) => setError(`Step approve failed: ${e.message}`) },
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
                            Requires human approval to continue
                          </Text>
                        </View>
                      )}
                      {/* Result summary for ALL completed steps */}
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
                            numberOfLines={3}
                          >
                            {step.result_summary}
                          </Text>
                        </View>
                      )}
                    </View>
                  );
                })}
              </View>
            );
          })()}

          {/* Notes */}
          {plan.notes ? (
            <View
              className="rounded-lg px-3 py-2"
              style={{ backgroundColor: t.surfaceOverlay }}
            >
              <Text style={{ fontSize: 12, color: t.textDim, lineHeight: 17 }}>
                {plan.notes}
              </Text>
            </View>
          ) : null}

          {/* Error feedback */}
          {error && (
            <View
              className="rounded-lg px-3 py-2"
              style={{ backgroundColor: "rgba(239,68,68,0.1)" }}
            >
              <Text style={{ fontSize: 12, color: "#ef4444" }}>{error}</Text>
            </View>
          )}

          {/* Actions */}
          <View className="flex-row items-center gap-2 pt-1">
            {(plan.status === "draft" || plan.status === "approved") && (
              <>
                {plan.status === "draft" && (
                  <Pressable
                    onPress={handleApprove}
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
                    <Text style={{ fontSize: 12, fontWeight: "600", color: "#22c55e" }}>
                      Approve
                    </Text>
                  </Pressable>
                )}
                <Pressable
                  onPress={handleReject}
                  disabled={reject.isPending}
                  className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                  style={{
                    backgroundColor: confirmReject
                      ? "rgba(239,68,68,0.25)"
                      : "rgba(239,68,68,0.1)",
                    borderWidth: 1,
                    borderColor: confirmReject
                      ? "rgba(239,68,68,0.6)"
                      : "rgba(239,68,68,0.3)",
                    opacity: reject.isPending ? 0.5 : 1,
                  }}
                >
                  <X size={12} color="#ef4444" />
                  <Text style={{ fontSize: 12, fontWeight: "600", color: "#ef4444" }}>
                    {confirmReject ? "Confirm Reject" : "Reject"}
                  </Text>
                </Pressable>
                {confirmReject && (
                  <Pressable
                    onPress={() => setConfirmReject(false)}
                    className="rounded-lg px-2 py-1.5"
                  >
                    <Text style={{ fontSize: 11, color: t.textDim }}>Cancel</Text>
                  </Pressable>
                )}
              </>
            )}
            {(plan.status === "executing" || plan.status === "awaiting_approval") && (() => {
              const nextStep = plan.steps.find(
                (s) => s.status === "pending" || s.status === "in_progress"
              );
              if (plan.status === "executing") {
                return (
                  <Pressable
                    onPress={handleResume}
                    disabled={resume.isPending || !nextStep}
                    className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                    style={{
                      backgroundColor: "rgba(59,130,246,0.12)",
                      borderWidth: 1,
                      borderColor: "rgba(59,130,246,0.35)",
                      opacity: resume.isPending || !nextStep ? 0.5 : 1,
                    }}
                  >
                    <StepForward size={12} color="#3b82f6" />
                    <Text style={{ fontSize: 12, fontWeight: "600", color: "#3b82f6" }}>
                      {nextStep ? `Resume (#${nextStep.position})` : "All steps done"}
                    </Text>
                  </Pressable>
                );
              }
              return null;
            })()}
            {/* Delete button for terminal/draft states */}
            {(plan.status === "draft" || plan.status === "complete" || plan.status === "abandoned") && (
              <>
                <Pressable
                  onPress={handleDelete}
                  disabled={deletePlan.isPending}
                  className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                  style={{
                    backgroundColor: confirmDelete
                      ? "rgba(239,68,68,0.2)"
                      : "transparent",
                    borderWidth: 1,
                    borderColor: confirmDelete
                      ? "rgba(239,68,68,0.4)"
                      : t.surfaceBorder,
                    opacity: deletePlan.isPending ? 0.5 : 1,
                  }}
                >
                  <Trash2 size={12} color={confirmDelete ? "#ef4444" : t.textDim} />
                  <Text style={{ fontSize: 12, fontWeight: "600", color: confirmDelete ? "#ef4444" : t.textDim }}>
                    {confirmDelete ? "Confirm Delete" : "Delete"}
                  </Text>
                </Pressable>
                {confirmDelete && (
                  <Pressable
                    onPress={() => setConfirmDelete(false)}
                    className="rounded-lg px-2 py-1.5"
                  >
                    <Text style={{ fontSize: 11, color: t.textDim }}>Cancel</Text>
                  </Pressable>
                )}
              </>
            )}
          </View>
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCPlans() {
  const [filter, setFilter] = useState<string>("all");
  const [filterChannel, setFilterChannel] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const { data: prefs } = useMCPrefs();
  const scope =
    ((prefs?.layout_prefs as any)?.scope as "fleet" | "personal") || "fleet";
  const statusParam = filter === "all" ? undefined : filter;
  const { data, isLoading } = useMCPlans(scope, statusParam);
  const { data: overview } = useMCOverview(scope);
  const { refreshing, onRefresh } = usePageRefresh([["mc-plans"]]);
  const createPlan = useMCPlanCreate();
  const router = useRouter();
  const t = useThemeTokens();

  const plans = data?.plans || [];

  // Unique channels for filter chips
  const channels = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of plans) map.set(p.channel_id, p.channel_name);
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [plans]);

  // Overview channels for create form
  const overviewChannels = useMemo(
    () => overview?.channels.map((ch) => ({ id: ch.id, name: ch.name })) || [],
    [overview?.channels]
  );

  const filtered = useMemo(
    () =>
      filterChannel
        ? plans.filter((p) => p.channel_id === filterChannel)
        : plans,
    [plans, filterChannel]
  );

  const handleCreate = (data: {
    channelId: string;
    title: string;
    notes: string;
    steps: Array<{ content: string; requires_approval: boolean }>;
  }) => {
    createPlan.mutate(data, {
      onSuccess: (result) => {
        setShowCreate(false);
        if (result?.plan_id) {
          router.push(`/mission-control/plans/${data.channelId}/${result.plan_id}` as any);
        }
      },
    });
  };

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Plans"
        subtitle="Structured execution plans"
        right={
          <Pressable
            onPress={() => setShowCreate(!showCreate)}
            className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
            style={{
              backgroundColor: showCreate ? t.surfaceOverlay : "rgba(34,197,94,0.12)",
              borderWidth: 1,
              borderColor: showCreate ? t.surfaceBorder : "rgba(34,197,94,0.3)",
            }}
          >
            <Plus size={13} color={showCreate ? t.textDim : "#22c55e"} />
            <Text style={{ fontSize: 12, fontWeight: "600", color: showCreate ? t.textDim : "#22c55e" }}>
              Create
            </Text>
          </Pressable>
        }
      />

      {/* Filter bar */}
      <View className="flex-row items-center gap-2 border-b border-surface-border flex-wrap" style={{ paddingLeft: 24, paddingRight: 16, paddingVertical: 8 }}>
        {/* Status filter */}
        {STATUS_FILTERS.map((s) => (
          <Pressable
            key={s}
            onPress={() => setFilter(s)}
            className={`rounded-full px-3 py-1 border ${
              filter === s ? "border-accent bg-accent/10" : "border-surface-border"
            }`}
          >
            <Text
              className={`text-xs ${
                filter === s ? "text-accent font-medium" : "text-text-muted"
              }`}
              style={{ textTransform: "capitalize" }}
            >
              {STATUS_LABELS[s] || s}
            </Text>
          </Pressable>
        ))}

        {/* Channel filter */}
        <ChannelFilterBar
          channels={channels}
          value={filterChannel}
          onChange={setFilterChannel}
        />
      </View>

      {/* Content */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{
          paddingLeft: 24,
          paddingRight: 16,
          paddingTop: 20,
          gap: 12,
          paddingBottom: 48,
          maxWidth: 960,
        }}
      >
        {/* Create form */}
        {showCreate && overviewChannels.length > 0 && (
          <PlanCreateForm
            channels={overviewChannels}
            onSubmit={handleCreate}
            onCancel={() => setShowCreate(false)}
            isPending={createPlan.isPending}
          />
        )}

        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading plans...</Text>
        ) : filtered.length === 0 ? (
          <MCEmptyState feature="plans">
            <Text className="text-text-muted text-sm">
              No plans found{filter !== "all" ? ` with status "${filter}"` : ""}.
              Plans are created when bots draft structured proposals using the
              planning tools, or click Create above.
            </Text>
          </MCEmptyState>
        ) : (
          filtered.map((plan) => <PlanCard key={plan.id} plan={plan} />)
        )}
      </RefreshableScrollView>
    </View>
  );
}
