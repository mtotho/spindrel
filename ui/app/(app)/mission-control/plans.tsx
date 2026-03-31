import { useState, useMemo, useCallback } from "react";
import { View, Text, Pressable } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCPlans,
  useMCPrefs,
  useMCPlanApprove,
  useMCPlanReject,
  useMCPlanResume,
  type MCPlan,
} from "@/src/api/hooks/useMissionControl";
import { MCEmptyState } from "@/src/components/mission-control/MCEmptyState";
import { channelColor } from "@/src/components/mission-control/botColors";
import {
  ClipboardCheck,
  Circle,
  CheckCircle2,
  Loader2,
  MinusCircle,
  ChevronDown,
  ChevronRight,
  Play,
  X,
  RotateCw,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Status colors
// ---------------------------------------------------------------------------
const STATUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  draft: { bg: "rgba(245,158,11,0.1)", border: "rgba(245,158,11,0.4)", text: "#f59e0b" },
  approved: { bg: "rgba(59,130,246,0.1)", border: "rgba(59,130,246,0.4)", text: "#3b82f6" },
  executing: { bg: "rgba(34,197,94,0.1)", border: "rgba(34,197,94,0.4)", text: "#22c55e" },
  complete: { bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.2)", text: "#6b7280" },
  abandoned: { bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.2)", text: "#ef4444" },
};

const STATUS_FILTERS = ["all", "draft", "executing", "approved", "complete", "abandoned"] as const;

// ---------------------------------------------------------------------------
// Step icon
// ---------------------------------------------------------------------------
function StepIcon({ status }: { status: string }) {
  switch (status) {
    case "done":
      return <CheckCircle2 size={14} color="#22c55e" />;
    case "in_progress":
      return <Loader2 size={14} color="#3b82f6" />;
    case "skipped":
      return <MinusCircle size={14} color="#9ca3af" />;
    default:
      return <Circle size={14} color="#d1d5db" />;
  }
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------
function ProgressBar({ steps }: { steps: MCPlan["steps"] }) {
  const t = useThemeTokens();
  const total = steps.length;
  if (total === 0) return null;
  const done = steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  const pct = Math.round((done / total) * 100);

  return (
    <View style={{ gap: 4 }}>
      <View
        style={{
          height: 4,
          borderRadius: 2,
          backgroundColor: t.surfaceBorder,
          overflow: "hidden",
        }}
      >
        <View
          style={{
            height: 4,
            borderRadius: 2,
            backgroundColor: pct === 100 ? "#22c55e" : "#3b82f6",
            width: `${pct}%`,
          }}
        />
      </View>
      <Text style={{ fontSize: 10, color: t.textDim }}>
        {done}/{total} steps ({pct}%)
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------
function StatusBadge({ status }: { status: string }) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.draft;
  return (
    <View
      style={{
        paddingHorizontal: 8,
        paddingVertical: 2,
        borderRadius: 10,
        backgroundColor: colors.bg,
        borderWidth: 1,
        borderColor: colors.border,
      }}
    >
      <Text style={{ fontSize: 10, fontWeight: "700", color: colors.text, textTransform: "uppercase" }}>
        {status}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Plan card
// ---------------------------------------------------------------------------
function PlanCard({ plan }: { plan: MCPlan }) {
  const t = useThemeTokens();
  const cc = channelColor(plan.channel_id);
  const [expanded, setExpanded] = useState(plan.status === "draft" || plan.status === "executing");
  const [confirmReject, setConfirmReject] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const approve = useMCPlanApprove();
  const reject = useMCPlanReject();
  const resume = useMCPlanResume();

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

  return (
    <View
      className="rounded-xl border border-surface-border"
      style={{ overflow: "hidden" }}
    >
      {/* Header */}
      <Pressable
        onPress={() => setExpanded(!expanded)}
        className="px-4 py-3 hover:bg-surface-overlay"
        style={{ gap: 6 }}
      >
        <View className="flex-row items-center gap-2">
          {expanded ? (
            <ChevronDown size={14} color={t.textDim} />
          ) : (
            <ChevronRight size={14} color={t.textDim} />
          )}
          <Text
            className="text-text font-semibold flex-1"
            numberOfLines={1}
            style={{ fontSize: 14 }}
          >
            {plan.title}
          </Text>
          <StatusBadge status={plan.status} />
        </View>
        <View className="flex-row items-center gap-3" style={{ paddingLeft: 22 }}>
          <View className="flex-row items-center gap-1.5">
            <View
              style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: cc }}
            />
            <Text style={{ fontSize: 11, color: t.textDim }}>{plan.channel_name}</Text>
          </View>
          {plan.meta.created && (
            <Text style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
              {plan.meta.created}
            </Text>
          )}
          <View style={{ flex: 1 }} />
          <ProgressBar steps={plan.steps} />
        </View>
      </Pressable>

      {/* Expanded content */}
      {expanded && (
        <View
          className="border-t border-surface-border px-4 py-3"
          style={{ gap: 10 }}
        >
          {/* Steps */}
          {plan.steps.length > 0 && (
            <View style={{ gap: 4 }}>
              {plan.steps.map((step) => (
                <View
                  key={step.position}
                  className="flex-row items-start gap-2"
                  style={{ paddingVertical: 2 }}
                >
                  <View style={{ marginTop: 1 }}>
                    <StepIcon status={step.status} />
                  </View>
                  <Text
                    style={{
                      fontSize: 13,
                      color: step.status === "done" || step.status === "skipped" ? t.textDim : t.text,
                      flex: 1,
                      lineHeight: 18,
                      textDecorationLine: step.status === "skipped" ? "line-through" : "none",
                    }}
                  >
                    {step.position}. {step.content}
                  </Text>
                </View>
              ))}
            </View>
          )}

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
            {plan.status === "executing" && (
              <Pressable
                onPress={handleResume}
                disabled={resume.isPending}
                className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                style={{
                  backgroundColor: "rgba(59,130,246,0.12)",
                  borderWidth: 1,
                  borderColor: "rgba(59,130,246,0.35)",
                  opacity: resume.isPending ? 0.5 : 1,
                }}
              >
                <RotateCw size={12} color="#3b82f6" />
                <Text style={{ fontSize: 12, fontWeight: "600", color: "#3b82f6" }}>
                  Resume
                </Text>
              </Pressable>
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
  const { data: prefs } = useMCPrefs();
  const scope =
    ((prefs?.layout_prefs as any)?.scope as "fleet" | "personal") || "fleet";
  const statusParam = filter === "all" ? undefined : filter;
  const { data, isLoading } = useMCPlans(scope, statusParam);
  const { refreshing, onRefresh } = usePageRefresh([["mc-plans"]]);
  const t = useThemeTokens();

  const plans = data?.plans || [];

  // Unique channels for filter chips
  const channels = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of plans) map.set(p.channel_id, p.channel_name);
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [plans]);

  const filtered = useMemo(
    () =>
      filterChannel
        ? plans.filter((p) => p.channel_id === filterChannel)
        : plans,
    [plans, filterChannel]
  );

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Plans"
        subtitle="Structured execution plans"
        right={
          <View className="flex-row items-center gap-2">
            <ClipboardCheck size={14} color={t.textDim} />
            <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "600" }}>
              {filtered.length} plan{filtered.length !== 1 ? "s" : ""}
            </Text>
          </View>
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
              {s}
            </Text>
          </Pressable>
        ))}

        {/* Channel filter */}
        {channels.length > 1 && (
          <>
            <View
              style={{
                width: 1,
                height: 16,
                backgroundColor: t.surfaceBorder,
                marginHorizontal: 4,
              }}
            />
            <Pressable
              onPress={() => setFilterChannel(null)}
              className={`rounded-full px-3 py-1 border ${
                !filterChannel ? "border-accent bg-accent/10" : "border-surface-border"
              }`}
            >
              <Text
                className={`text-xs ${
                  !filterChannel ? "text-accent font-medium" : "text-text-muted"
                }`}
              >
                All
              </Text>
            </Pressable>
            {channels.map((ch) => {
              const active = filterChannel === ch.id;
              const cc = channelColor(ch.id);
              return (
                <Pressable
                  key={ch.id}
                  onPress={() => setFilterChannel(active ? null : ch.id)}
                  className={`rounded-full px-3 py-1 border flex-row items-center gap-1.5 ${
                    active ? "border-accent bg-accent/10" : "border-surface-border"
                  }`}
                >
                  <View
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 3,
                      backgroundColor: cc,
                    }}
                  />
                  <Text
                    className={`text-xs ${
                      active ? "text-accent font-medium" : "text-text-muted"
                    }`}
                  >
                    {ch.name}
                  </Text>
                </Pressable>
              );
            })}
          </>
        )}
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
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading plans...</Text>
        ) : filtered.length === 0 ? (
          <MCEmptyState feature="plans">
            <Text className="text-text-muted text-sm">
              No plans found{filter !== "all" ? ` with status "${filter}"` : ""}.
              Plans are created when bots draft structured proposals using the
              planning tools.
            </Text>
          </MCEmptyState>
        ) : (
          filtered.map((plan) => <PlanCard key={plan.id} plan={plan} />)
        )}
      </RefreshableScrollView>
    </View>
  );
}
