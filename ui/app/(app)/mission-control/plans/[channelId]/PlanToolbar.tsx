import { type ThemeTokens } from "@/src/theme/tokens";
import type { MCPlan } from "@/src/api/hooks/useMissionControl";
import { ExportMenu } from "./ExportMenu";
import {
  Play,
  X,
  StepForward,
  Pencil,
  BookmarkPlus,
  Trash2,
  Check,
} from "lucide-react";
import { StatusBadge } from "@/src/components/mission-control/PlanComponents";

// ---------------------------------------------------------------------------
// Action toolbar for the plan detail page
// ---------------------------------------------------------------------------
export function PlanToolbar({
  plan,
  t,
  editing,
  confirmReject,
  confirmDelete,
  templateSaved,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  onApprove,
  onReject,
  onResume,
  onSaveTemplate,
  onDelete,
  onSetConfirmReject,
  onSetConfirmDelete,
  onGoBack,
  isApprovePending,
  isRejectPending,
  isResumePending,
  isUpdatePending,
  isDeletePending,
  isSaveTemplatePending,
}: {
  plan: MCPlan;
  t: ThemeTokens;
  editing: boolean;
  confirmReject: boolean;
  confirmDelete: boolean;
  templateSaved: boolean;
  onStartEdit: () => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  onApprove: () => void;
  onReject: () => void;
  onResume: () => void;
  onSaveTemplate: () => void;
  onDelete: () => void;
  onSetConfirmReject: (v: boolean) => void;
  onSetConfirmDelete: (v: boolean) => void;
  onGoBack: () => void;
  isApprovePending: boolean;
  isRejectPending: boolean;
  isResumePending: boolean;
  isUpdatePending: boolean;
  isDeletePending: boolean;
  isSaveTemplatePending: boolean;
}) {
  return (
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
            onClick={onApprove}
            disabled={isApprovePending}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "5px 12px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: t.success, color: "#fff", cursor: "pointer",
              opacity: isApprovePending ? 0.6 : 1,
            }}
          >
            <Play size={12} />
            Approve
          </button>
          <button
            onClick={() => {
              if (!confirmReject) { onSetConfirmReject(true); return; }
              onSetConfirmReject(false);
              onReject();
            }}
            disabled={isRejectPending}
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
              onClick={() => onSetConfirmReject(false)}
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
          onClick={onResume}
          disabled={isResumePending}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "4px 10px", fontSize: 11, fontWeight: 600,
            border: `1px solid ${t.accentBorder}`,
            borderRadius: 5,
            background: t.accentSubtle, color: t.accent, cursor: "pointer",
            opacity: isResumePending ? 0.6 : 1,
          }}
        >
          <StepForward size={12} />
          Resume
        </button>
      )}

      {/* Secondary actions */}
      {plan.status === "draft" && !editing && (
        <button
          onClick={onStartEdit}
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
            onClick={onSaveEdit}
            disabled={isUpdatePending}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "5px 12px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: t.success, color: "#fff", cursor: "pointer",
              opacity: isUpdatePending ? 0.6 : 1,
            }}
          >
            Save
          </button>
          <button
            onClick={onCancelEdit}
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
          onClick={onSaveTemplate}
          disabled={isSaveTemplatePending || templateSaved}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "4px 10px", fontSize: 11, fontWeight: 600,
            border: `1px solid ${templateSaved ? t.successBorder : t.surfaceBorder}`,
            borderRadius: 5,
            background: templateSaved ? t.successSubtle : "transparent",
            color: templateSaved ? t.success : t.textDim,
            cursor: "pointer",
            opacity: isSaveTemplatePending ? 0.6 : 1,
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
              if (!confirmDelete) { onSetConfirmDelete(true); return; }
              onSetConfirmDelete(false);
              onDelete();
            }}
            disabled={isDeletePending}
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
              onClick={() => onSetConfirmDelete(false)}
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
  );
}
