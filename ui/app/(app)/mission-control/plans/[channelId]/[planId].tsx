import { useState, useCallback } from "react";
import { View, Text, ActivityIndicator } from "react-native";
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
} from "@/src/api/hooks/useMissionControl";
import { channelColor } from "@/src/components/mission-control/botColors";
import {
  MetaItem,
  ProgressBar,
} from "@/src/components/mission-control/PlanComponents";
import {
  StepListEditor,
  makeStepKey,
  type StepDraft,
} from "@/src/components/mission-control/StepListEditor";
import { X } from "lucide-react";

import { fmtTime } from "./planHelpers";
import { StepSection } from "./StepSection";
import { PlanToolbar } from "./PlanToolbar";
import { ExecutionTimeline } from "./ExecutionTimeline";

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
            {/* ---- Action toolbar ---- */}
            <PlanToolbar
              plan={plan}
              t={t}
              editing={editing}
              confirmReject={confirmReject}
              confirmDelete={confirmDelete}
              templateSaved={templateSaved}
              onStartEdit={startEdit}
              onSaveEdit={saveEdit}
              onCancelEdit={() => setEditing(false)}
              onApprove={() =>
                approve.mutate(
                  { channelId: plan.channel_id, planId: plan.id },
                  { onError: (e: Error) => setActionError(`Approve failed: ${e.message}`) }
                )
              }
              onReject={() =>
                reject.mutate(
                  { channelId: plan.channel_id, planId: plan.id },
                  { onError: (e: Error) => setActionError(`Reject failed: ${e.message}`) }
                )
              }
              onResume={() =>
                resume.mutate(
                  { channelId: plan.channel_id, planId: plan.id },
                  { onError: (e: Error) => setActionError(`Resume failed: ${e.message}`) }
                )
              }
              onSaveTemplate={() => {
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
              onDelete={() =>
                deletePlan.mutate(
                  { channelId: plan.channel_id, planId: plan.id },
                  {
                    onSuccess: () => goBack(),
                    onError: (e: Error) => setActionError(`Delete failed: ${e.message}`),
                  }
                )
              }
              onSetConfirmReject={setConfirmReject}
              onSetConfirmDelete={setConfirmDelete}
              onGoBack={goBack}
              isApprovePending={approve.isPending}
              isRejectPending={reject.isPending}
              isResumePending={resume.isPending}
              isUpdatePending={updatePlan.isPending}
              isDeletePending={deletePlan.isPending}
              isSaveTemplatePending={saveAsTemplate.isPending}
            />

            {/* ---- Error banner ---- */}
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

            {/* ---- Metadata grid ---- */}
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

            {/* ---- Notes ---- */}
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

            {/* ---- Steps ---- */}
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

            {/* ---- Execution Timeline ---- */}
            {!editing && <ExecutionTimeline steps={plan.steps} t={t} />}
          </>
        ) : null}
      </RefreshableScrollView>
    </View>
  );
}
