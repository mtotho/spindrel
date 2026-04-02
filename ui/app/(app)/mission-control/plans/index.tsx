import { useState, useMemo } from "react";
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
  useMCPlanCreate,
  useMCPlanDelete,
  type MCPlan,
} from "@/src/api/hooks/useMissionControl";
import { MCEmptyState } from "@/src/components/mission-control/MCEmptyState";
import { ChannelFilterBar } from "@/src/components/mission-control/ChannelFilterBar";
import { channelColor } from "@/src/components/mission-control/botColors";
import { PlanCreateForm } from "@/src/components/mission-control/PlanCreateForm";
import {
  StatusBadge,
  PlanStatusIcon,
  ProgressBar,
} from "@/src/components/mission-control/PlanComponents";
import { STATUS_FILTERS, STATUS_LABELS } from "@/src/components/mission-control/planConstants";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  ChevronRight,
  Play,
  X,
  Plus,
  Copy,
  Trash2,
  ShieldAlert,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Time helpers
// ---------------------------------------------------------------------------
function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60000) return "just now";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

// ---------------------------------------------------------------------------
// Plan card (list item)
// ---------------------------------------------------------------------------
function PlanCard({ plan }: { plan: MCPlan }) {
  const t = useThemeTokens();
  const router = useRouter();
  const cc = channelColor(plan.channel_id);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const approve = useMCPlanApprove();
  const reject = useMCPlanReject();
  const deletePlan = useMCPlanDelete();

  const navigate = () => {
    router.push(`/mission-control/plans/${plan.channel_id}/${plan.id}` as any);
  };

  const needsAction = plan.status === "draft" || plan.status === "awaiting_approval";
  const hasApprovalGates = plan.steps.some((s) => s.requires_approval && s.status !== "done" && s.status !== "skipped");

  return (
    <div
      style={{
        borderRadius: 8,
        border: `1px solid ${t.surfaceBorder}`,
        background: t.codeBg,
        overflow: "hidden",
        transition: "border-color 0.15s",
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = t.textDim; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = t.surfaceBorder; }}
    >
      {/* Main row — clickable to detail */}
      <Pressable
        onPress={navigate}
        style={{
          flexDirection: "row",
          alignItems: "center",
          padding: 14,
          gap: 12,
        }}
      >
        {/* Status icon */}
        <div style={{
          width: 28,
          height: 28,
          borderRadius: 14,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}>
          <PlanStatusIcon status={plan.status} size={18} />
        </div>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{
              fontSize: 14, fontWeight: 600, color: t.text,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              flex: 1,
            }}>
              {plan.title}
            </span>
            <StatusBadge status={plan.status} />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textDim }}>
              <div style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: cc }} />
              {plan.channel_name}
            </span>
            <Pressable onPress={() => writeToClipboard(plan.id)} style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
              <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
                {plan.id.slice(0, 8)}
              </span>
              <Copy size={8} color={t.textDim} />
            </Pressable>
            {plan.created_at && (
              <span style={{ fontSize: 10, color: t.textDim }}>
                {fmtTime(plan.created_at)}
              </span>
            )}
            {hasApprovalGates && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 2, fontSize: 10, color: "#a855f7" }}>
                <ShieldAlert size={9} />
                Gates
              </span>
            )}
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ width: 80, flexShrink: 0 }}>
          <ProgressBar steps={plan.steps} compact />
        </div>

        <ChevronRight size={14} color={t.textDim} />
      </Pressable>

      {/* Quick actions for actionable plans */}
      {needsAction && (
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 14px",
          borderTop: `1px solid ${t.surfaceBorder}`,
        }}>
          {plan.status === "draft" && (
            <>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setError(null);
                  approve.mutate(
                    { channelId: plan.channel_id, planId: plan.id },
                    { onError: (err: Error) => setError(err.message) },
                  );
                }}
                disabled={approve.isPending}
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "4px 10px", fontSize: 11, fontWeight: 600,
                  border: "none", borderRadius: 5,
                  background: t.success, color: "#fff", cursor: "pointer",
                  opacity: approve.isPending ? 0.6 : 1,
                }}
              >
                <Play size={11} />
                Approve
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setError(null);
                  reject.mutate(
                    { channelId: plan.channel_id, planId: plan.id },
                    { onError: (err: Error) => setError(err.message) },
                  );
                }}
                disabled={reject.isPending}
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "4px 10px", fontSize: 11, fontWeight: 600,
                  border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                  background: "transparent", color: t.textDim, cursor: "pointer",
                }}
              >
                <X size={11} />
                Reject
              </button>
            </>
          )}
          {plan.status === "awaiting_approval" && (
            <span style={{ fontSize: 11, color: "#a855f7", fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}>
              <ShieldAlert size={12} />
              Step requires approval — click to review
            </span>
          )}
          <div style={{ flex: 1 }} />
          {plan.status === "draft" && (
            <>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (!confirmDelete) { setConfirmDelete(true); return; }
                  setConfirmDelete(false);
                  setError(null);
                  deletePlan.mutate(
                    { channelId: plan.channel_id, planId: plan.id },
                    { onError: (err: Error) => setError(err.message) },
                  );
                }}
                style={{
                  display: "flex", alignItems: "center", gap: 3,
                  padding: "4px 8px", fontSize: 10, fontWeight: 600,
                  border: `1px solid ${confirmDelete ? t.dangerBorder : t.surfaceBorder}`,
                  borderRadius: 5,
                  background: confirmDelete ? t.dangerSubtle : "transparent",
                  color: confirmDelete ? t.danger : t.textDim,
                  cursor: "pointer",
                }}
              >
                <Trash2 size={10} />
                {confirmDelete ? "Confirm" : "Delete"}
              </button>
              {confirmDelete && (
                <button
                  onClick={(e) => { e.stopPropagation(); setConfirmDelete(false); }}
                  style={{
                    padding: "4px 6px", fontSize: 10,
                    border: "none", background: "transparent",
                    color: t.textDim, cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              )}
            </>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{
          padding: "6px 14px", fontSize: 11, color: t.danger,
          background: t.dangerSubtle, borderTop: `1px solid ${t.dangerBorder}`,
        }}>
          {error}
        </div>
      )}
    </div>
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

  const channels = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of plans) map.set(p.channel_id, p.channel_name);
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [plans]);

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

  // Group by status for visual separation
  const actionable = filtered.filter((p) => p.status === "draft" || p.status === "awaiting_approval");
  const active = filtered.filter((p) => p.status === "executing" || p.status === "approved");
  const terminal = filtered.filter((p) => p.status === "complete" || p.status === "abandoned");

  const handleCreate = (formData: {
    channelId: string;
    title: string;
    notes: string;
    steps: Array<{ content: string; requires_approval: boolean }>;
  }) => {
    createPlan.mutate(formData, {
      onSuccess: (result: { ok: boolean; plan_id: string; status: string }) => {
        setShowCreate(false);
        if (result?.plan_id) {
          router.push(`/mission-control/plans/${formData.channelId}/${result.plan_id}` as any);
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
          <button
            onClick={() => setShowCreate(!showCreate)}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "6px 12px", fontSize: 12, fontWeight: 600,
              border: `1px solid ${showCreate ? t.surfaceBorder : "rgba(34,197,94,0.3)"}`,
              borderRadius: 6,
              background: showCreate ? "transparent" : "rgba(34,197,94,0.12)",
              color: showCreate ? t.textDim : "#22c55e",
              cursor: "pointer",
            }}
          >
            <Plus size={13} />
            Create
          </button>
        }
      />

      {/* Filter bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
        paddingLeft: 20, paddingRight: 16, paddingTop: 8, paddingBottom: 8,
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        {STATUS_FILTERS.map((s) => {
          const active = filter === s;
          return (
            <button
              key={s}
              onClick={() => setFilter(s)}
              style={{
                padding: "4px 10px",
                fontSize: 11,
                fontWeight: active ? 600 : 400,
                border: `1px solid ${active ? t.accentBorder : t.surfaceBorder}`,
                borderRadius: 12,
                background: active ? t.accentSubtle : "transparent",
                color: active ? t.accent : t.textMuted,
                cursor: "pointer",
                textTransform: "capitalize",
              }}
            >
              {STATUS_LABELS[s] || s}
            </button>
          );
        })}
        <div style={{ width: 1, height: 16, background: t.surfaceBorder }} />
        <ChannelFilterBar
          channels={channels}
          value={filterChannel}
          onChange={setFilterChannel}
        />
      </div>

      {/* Content */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{
          paddingHorizontal: 20,
          paddingTop: 16,
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
              No plans found{filter !== "all" ? ` with status "${STATUS_LABELS[filter] || filter}"` : ""}.
              Plans are created when bots draft structured proposals, or click Create above.
            </Text>
          </MCEmptyState>
        ) : (
          <>
            {/* Needs attention */}
            {actionable.length > 0 && (
              <SectionHeader label="Needs Attention" count={actionable.length} t={t} />
            )}
            {actionable.map((plan) => <PlanCard key={plan.id} plan={plan} />)}

            {/* Active */}
            {active.length > 0 && (
              <SectionHeader label="Active" count={active.length} t={t} />
            )}
            {active.map((plan) => <PlanCard key={plan.id} plan={plan} />)}

            {/* Completed */}
            {terminal.length > 0 && (
              <SectionHeader label="Completed" count={terminal.length} t={t} />
            )}
            {terminal.map((plan) => <PlanCard key={plan.id} plan={plan} />)}
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Section header (like workflow list grouping)
// ---------------------------------------------------------------------------
function SectionHeader({ label, count, t }: { label: string; count: number; t: ReturnType<typeof useThemeTokens> }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      paddingTop: 8, paddingBottom: 4,
    }}>
      <span style={{
        fontSize: 11, fontWeight: 600, color: t.textMuted,
        textTransform: "uppercase", letterSpacing: 1,
      }}>
        {label}
      </span>
      <span style={{ fontSize: 10, color: t.textDim, fontWeight: 500 }}>
        {count}
      </span>
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}
