import { useState, useCallback, useMemo } from "react";
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
  useMCSavePlanAsTemplate,
  type MCPlanStep,
} from "@/src/api/hooks/useMissionControl";
import { channelColor } from "@/src/components/mission-control/botColors";
import {
  StatusBadge,
  StepIcon,
  StepStatusBadge,
  ProgressBar,
  MetaItem,
} from "@/src/components/mission-control/PlanComponents";
import { getStepStatusStyle } from "@/src/components/mission-control/planConstants";
import {
  StepListEditor,
  makeStepKey,
  type StepDraft,
} from "@/src/components/mission-control/StepListEditor";
import { writeToClipboard } from "@/src/utils/clipboard";
import { downloadBlob } from "@/src/utils/download";
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
  BookmarkPlus,
  Download,
  Layers,
  Check,
  AlertTriangle,
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

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60000) return "just now";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Export menu
// ---------------------------------------------------------------------------
function ExportMenu({ channelId, planId, planTitle }: { channelId: string; planId: string; planTitle: string }) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const doExport = async (format: "markdown" | "json") => {
    setExporting(true);
    try {
      const { apiFetchText } = await import("@/src/api/client");
      const content = await apiFetchText(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}/export?format=${format}`,
      );
      const ext = format === "markdown" ? "md" : "json";
      const slug = planTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
      downloadBlob(content, `plan-${slug}.${ext}`, format === "markdown" ? "text/markdown" : "application/json");
    } catch {
      // silently fail
    } finally {
      setExporting(false);
      setOpen(false);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={exporting}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          padding: "4px 10px", fontSize: 11, fontWeight: 600,
          border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
          background: "transparent", color: t.textDim, cursor: "pointer",
          opacity: exporting ? 0.5 : 1,
        }}
      >
        <Download size={12} />
        Export
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: 28,
            right: 0,
            zIndex: 100,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
            minWidth: 120,
            overflow: "hidden",
          }}
        >
          <button
            onClick={() => doExport("markdown")}
            style={{
              display: "block", width: "100%", textAlign: "left",
              padding: "8px 12px", fontSize: 12, color: t.text,
              background: "transparent", border: "none", cursor: "pointer",
            }}
          >
            Markdown
          </button>
          <button
            onClick={() => doExport("json")}
            style={{
              display: "block", width: "100%", textAlign: "left",
              padding: "8px 12px", fontSize: 12, color: t.text,
              background: "transparent", border: "none", cursor: "pointer",
            }}
          >
            JSON
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step feed section (one step = one section, like WorkflowRunFeed)
// ---------------------------------------------------------------------------
function StepSection({
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
  const saveAsTemplate = useMCSavePlanAsTemplate();

  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmReject, setConfirmReject] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editSteps, setEditSteps] = useState<StepDraft[]>([]);
  const [templateSaved, setTemplateSaved] = useState(false);

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
          paddingHorizontal: 20,
          paddingTop: 16,
          gap: 16,
          paddingBottom: 48,
          maxWidth: 960,
        }}
      >
        {isLoading ? (
          <View className="items-center py-12">
            <ActivityIndicator size="large" />
          </View>
        ) : error ? (
          <div style={{
            padding: 12, borderRadius: 8,
            background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
          }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: t.danger }}>
              Failed to load plan
            </span>
            <div style={{ fontSize: 12, color: t.danger, marginTop: 4 }}>
              {(error as any)?.message || "Plan not found"}
            </div>
          </div>
        ) : plan ? (
          <>
            {/* ── Action toolbar ── */}
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
              paddingBottom: 12,
              flexWrap: "wrap",
            }}>
              <StatusBadge status={plan.status} />
              <div style={{ flex: 1 }} />

              {/* Primary actions */}
              {plan.status === "draft" && !editing && (
                <>
                  <button
                    onClick={() =>
                      approve.mutate(
                        { channelId: plan.channel_id, planId: plan.id },
                        { onError: (e: Error) => setActionError(`Approve failed: ${e.message}`) }
                      )
                    }
                    disabled={approve.isPending}
                    style={{
                      display: "flex", alignItems: "center", gap: 4,
                      padding: "5px 12px", fontSize: 12, fontWeight: 600,
                      border: "none", borderRadius: 6,
                      background: t.success, color: "#fff", cursor: "pointer",
                      opacity: approve.isPending ? 0.6 : 1,
                    }}
                  >
                    <Play size={12} />
                    Approve
                  </button>
                  <button
                    onClick={() => {
                      if (!confirmReject) { setConfirmReject(true); return; }
                      setConfirmReject(false);
                      reject.mutate(
                        { channelId: plan.channel_id, planId: plan.id },
                        { onError: (e: Error) => setActionError(`Reject failed: ${e.message}`) }
                      );
                    }}
                    disabled={reject.isPending}
                    style={{
                      display: "flex", alignItems: "center", gap: 4,
                      padding: "4px 10px", fontSize: 11, fontWeight: 600,
                      border: `1px solid ${confirmReject ? t.dangerBorder : t.surfaceBorder}`,
                      borderRadius: 5,
                      background: confirmReject ? t.dangerSubtle : "transparent",
                      color: confirmReject ? t.danger : t.textDim,
                      cursor: "pointer",
                    }}
                  >
                    <X size={12} />
                    {confirmReject ? "Confirm Reject" : "Reject"}
                  </button>
                  {confirmReject && (
                    <button
                      onClick={() => setConfirmReject(false)}
                      style={{
                        padding: "4px 8px", fontSize: 11,
                        border: "none", background: "transparent",
                        color: t.textDim, cursor: "pointer",
                      }}
                    >
                      Cancel
                    </button>
                  )}
                </>
              )}
              {plan.status === "executing" && (
                <button
                  onClick={() =>
                    resume.mutate(
                      { channelId: plan.channel_id, planId: plan.id },
                      { onError: (e: Error) => setActionError(`Resume failed: ${e.message}`) }
                    )
                  }
                  disabled={resume.isPending}
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "4px 10px", fontSize: 11, fontWeight: 600,
                    border: `1px solid ${t.accentBorder}`,
                    borderRadius: 5,
                    background: t.accentSubtle, color: t.accent, cursor: "pointer",
                    opacity: resume.isPending ? 0.6 : 1,
                  }}
                >
                  <StepForward size={12} />
                  Resume
                </button>
              )}

              {/* Secondary actions */}
              {plan.status === "draft" && !editing && (
                <button
                  onClick={startEdit}
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "4px 10px", fontSize: 11, fontWeight: 600,
                    border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                    background: "transparent", color: t.textDim, cursor: "pointer",
                  }}
                >
                  <Pencil size={12} />
                  Edit
                </button>
              )}
              {editing && (
                <>
                  <button
                    onClick={saveEdit}
                    disabled={updatePlan.isPending}
                    style={{
                      display: "flex", alignItems: "center", gap: 4,
                      padding: "5px 12px", fontSize: 12, fontWeight: 600,
                      border: "none", borderRadius: 6,
                      background: t.success, color: "#fff", cursor: "pointer",
                      opacity: updatePlan.isPending ? 0.6 : 1,
                    }}
                  >
                    Save
                  </button>
                  <button
                    onClick={() => setEditing(false)}
                    style={{
                      padding: "4px 10px", fontSize: 11, fontWeight: 600,
                      border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                      background: "transparent", color: t.textDim, cursor: "pointer",
                    }}
                  >
                    Cancel
                  </button>
                </>
              )}

              {/* Save template */}
              {!editing && (plan.status === "draft" || plan.status === "complete") && (
                <button
                  onClick={() => {
                    setActionError(null);
                    saveAsTemplate.mutate(
                      {
                        channelId: plan.channel_id,
                        planId: plan.id,
                        name: plan.title,
                        description: plan.notes || "",
                      },
                      {
                        onSuccess: () => { setTemplateSaved(true); setTimeout(() => setTemplateSaved(false), 2000); },
                        onError: (e: Error) => setActionError(`Save template failed: ${e.message}`),
                      },
                    );
                  }}
                  disabled={saveAsTemplate.isPending || templateSaved}
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "4px 10px", fontSize: 11, fontWeight: 600,
                    border: `1px solid ${templateSaved ? t.successBorder : t.surfaceBorder}`,
                    borderRadius: 5,
                    background: templateSaved ? t.successSubtle : "transparent",
                    color: templateSaved ? t.success : t.textDim,
                    cursor: "pointer",
                    opacity: saveAsTemplate.isPending ? 0.6 : 1,
                  }}
                >
                  {templateSaved ? <Check size={12} /> : <BookmarkPlus size={12} />}
                  {templateSaved ? "Saved!" : "Save Template"}
                </button>
              )}

              {/* Export */}
              {!editing && (
                <ExportMenu channelId={plan.channel_id} planId={plan.id} planTitle={plan.title} />
              )}

              {/* Delete */}
              {(plan.status === "draft" || plan.status === "complete" || plan.status === "abandoned") && !editing && (
                <>
                  <button
                    onClick={() => {
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
                    style={{
                      display: "flex", alignItems: "center", gap: 4,
                      padding: "4px 10px", fontSize: 11, fontWeight: 600,
                      border: `1px solid ${confirmDelete ? t.dangerBorder : t.surfaceBorder}`,
                      borderRadius: 5,
                      background: confirmDelete ? t.dangerSubtle : "transparent",
                      color: confirmDelete ? t.danger : t.textDim,
                      cursor: "pointer",
                    }}
                  >
                    <Trash2 size={12} />
                    {confirmDelete ? "Confirm Delete" : "Delete"}
                  </button>
                  {confirmDelete && (
                    <button
                      onClick={() => setConfirmDelete(false)}
                      style={{
                        padding: "4px 8px", fontSize: 11,
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

            {/* ── Error banner ── */}
            {actionError && (
              <div style={{
                padding: 10, borderRadius: 8,
                background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
                color: t.danger, fontSize: 12,
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}>
                <span>{actionError}</span>
                <button
                  onClick={() => setActionError(null)}
                  style={{ background: "none", border: "none", color: t.danger, cursor: "pointer", padding: 2 }}
                >
                  <X size={14} />
                </button>
              </div>
            )}

            {/* ── Metadata grid ── */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
              gap: 8,
              padding: 12,
              borderRadius: 8,
              background: t.codeBg,
              border: `1px solid ${t.surfaceBorder}`,
            }}>
              <MetaItem label="Plan ID" value={plan.id.slice(0, 12)} mono />
              <div>
                <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Channel
                </div>
                <div style={{
                  display: "flex", alignItems: "center", gap: 4,
                  fontSize: 12, color: t.text, marginTop: 1,
                }}>
                  <div style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: cc, flexShrink: 0 }} />
                  {plan.channel_name}
                </div>
              </div>
              <MetaItem label="Created" value={fmtTime(plan.created_at)} />
              {plan.updated_at && <MetaItem label="Updated" value={fmtTime(plan.updated_at)} />}
              {plan.meta.approved && <MetaItem label="Approved" value={plan.meta.approved} />}
              <div>
                <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Progress
                </div>
                <div style={{ marginTop: 3 }}>
                  <ProgressBar steps={plan.steps} />
                </div>
              </div>
            </div>

            {/* ── Notes ── */}
            {editing ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Title
                </div>
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  style={{
                    fontSize: 14, fontWeight: 600, color: t.text,
                    backgroundColor: t.inputBg, border: `1px solid ${t.inputBorder}`,
                    borderRadius: 8, padding: "8px 12px", outline: "none", fontFamily: "inherit",
                  }}
                />
                <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: 4 }}>
                  Notes
                </div>
                <textarea
                  value={editNotes}
                  onChange={(e) => setEditNotes(e.target.value)}
                  placeholder="Context, rationale, estimates..."
                  rows={3}
                  style={{
                    fontSize: 13, color: t.text,
                    backgroundColor: t.inputBg, border: `1px solid ${t.inputBorder}`,
                    borderRadius: 8, padding: "8px 12px", outline: "none",
                    fontFamily: "inherit", resize: "vertical",
                  }}
                />
              </div>
            ) : plan.notes ? (
              <div style={{
                padding: 12, borderRadius: 8,
                background: t.codeBg, border: `1px solid ${t.surfaceBorder}`,
              }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
                  Notes
                </div>
                <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5 }}>
                  {plan.notes}
                </div>
              </div>
            ) : null}

            {/* ── Steps ── */}
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
                Steps
              </div>
              {editing ? (
                <StepListEditor steps={editSteps} onChange={setEditSteps} />
              ) : (
                <div style={{
                  borderRadius: 8,
                  border: `1px solid ${t.surfaceBorder}`,
                  overflow: "hidden",
                  background: t.codeBg,
                }}>
                  {plan.steps.map((step, i) => (
                    <StepSection
                      key={step.position}
                      step={step}
                      plan={plan}
                      onApproveStep={() => {
                        setActionError(null);
                        stepApprove.mutate(
                          { channelId: plan.channel_id, planId: plan.id, position: step.position },
                          { onError: (e: Error) => setActionError(`Step approve failed: ${e.message}`) },
                        );
                      }}
                      onSkipStep={() => {
                        setActionError(null);
                        skipStep.mutate(
                          { channelId: plan.channel_id, planId: plan.id, position: step.position },
                          { onError: (e: Error) => setActionError(`Skip failed: ${e.message}`) },
                        );
                      }}
                      isApprovePending={stepApprove.isPending}
                      isSkipPending={skipStep.isPending}
                      isLast={i === plan.steps.length - 1}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* ── Execution Timeline ── */}
            {!editing && <ExecutionTimeline steps={plan.steps} t={t} />}
          </>
        ) : null}
      </RefreshableScrollView>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Execution timeline — chronological feed of step events
// ---------------------------------------------------------------------------
interface TimelineEvent {
  time: Date;
  label: string;
  stepPosition: number;
  type: "started" | "completed" | "failed" | "skipped";
}

function ExecutionTimeline({
  steps,
  t,
}: {
  steps: MCPlanStep[];
  t: ReturnType<typeof import("@/src/theme/tokens").useThemeTokens>;
}) {
  const events = useMemo(() => {
    const evts: TimelineEvent[] = [];
    for (const step of steps) {
      if (step.started_at) {
        evts.push({
          time: new Date(step.started_at),
          label: `Step ${step.position} started`,
          stepPosition: step.position,
          type: "started",
        });
      }
      if (step.completed_at) {
        const type = step.status === "failed" ? "failed" : step.status === "skipped" ? "skipped" : "completed";
        evts.push({
          time: new Date(step.completed_at),
          label: `Step ${step.position} ${type}`,
          stepPosition: step.position,
          type,
        });
      }
    }
    evts.sort((a, b) => a.time.getTime() - b.time.getTime());
    return evts;
  }, [steps]);

  if (events.length === 0) return null;

  const typeColor = (type: TimelineEvent["type"]) => {
    switch (type) {
      case "started": return t.accent;
      case "completed": return t.success;
      case "failed": return t.danger;
      case "skipped": return t.textDim;
    }
  };

  const typeDot = (type: TimelineEvent["type"]) => {
    switch (type) {
      case "started": return t.accent;
      case "completed": return t.success;
      case "failed": return t.danger;
      case "skipped": return t.textDim;
    }
  };

  const fmtTimelineTime = (d: Date) => {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  // Compute elapsed since first event
  const firstTime = events[0].time.getTime();

  return (
    <div>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: t.textMuted,
          textTransform: "uppercase",
          letterSpacing: 0.5,
          marginBottom: 8,
        }}
      >
        Timeline
      </div>
      <div
        style={{
          borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`,
          background: t.codeBg,
          padding: "8px 0",
        }}
      >
        {events.map((ev, i) => {
          const elapsed = ev.time.getTime() - firstTime;
          const elapsedStr = elapsed === 0 ? "" : `+${fmtElapsed(elapsed)}`;
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "5px 14px",
                position: "relative",
              }}
            >
              {/* Timeline line */}
              {i < events.length - 1 && (
                <div
                  style={{
                    position: "absolute",
                    left: 21,
                    top: 20,
                    bottom: -5,
                    width: 1,
                    background: t.surfaceBorder,
                  }}
                />
              )}
              {/* Dot */}
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: typeDot(ev.type),
                  flexShrink: 0,
                  zIndex: 1,
                }}
              />
              {/* Time */}
              <span
                style={{
                  fontSize: 10,
                  color: t.textDim,
                  fontFamily: "monospace",
                  width: 68,
                  flexShrink: 0,
                }}
              >
                {fmtTimelineTime(ev.time)}
              </span>
              {/* Event label */}
              <span style={{ fontSize: 12, color: typeColor(ev.type), fontWeight: 500, flex: 1 }}>
                {ev.label}
              </span>
              {/* Elapsed */}
              {elapsedStr && (
                <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
                  {elapsedStr}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function fmtElapsed(ms: number): string {
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
