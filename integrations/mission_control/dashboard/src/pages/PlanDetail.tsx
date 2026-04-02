import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ShieldAlert, Copy, Check } from "lucide-react";
import {
  usePlan,
  usePlanApprove,
  usePlanReject,
  usePlanResume,
  usePlanDelete,
  usePlanUpdate,
  useStepApprove,
  useStepSkip,
} from "../hooks/useMC";
import { useConfirm } from "../lib/useConfirm";
import { channelColor } from "../lib/colors";
import { timeAgo, formatDuration } from "../lib/dates";
import { StepIcon, ProgressBar, StatusBadge } from "../components/PlanComponents";
import StepListEditor, { makeStepKey } from "../components/StepListEditor";
import type { StepDraft } from "../components/StepListEditor";
import MarkdownViewer from "../components/MarkdownViewer";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import type { Plan, PlanStep } from "../lib/types";

export default function PlanDetail() {
  const { channelId, planId } = useParams<{ channelId: string; planId: string }>();
  const { data: plan, isLoading, error, refetch } = usePlan(channelId, planId);
  const [editing, setEditing] = useState(false);

  if (isLoading) return <div className="p-6"><LoadingSpinner /></div>;
  if (error) return <div className="p-6"><ErrorBanner message={error.message} onRetry={() => refetch()} /></div>;
  if (!plan) return null;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <Link to="/plans" className="text-xs text-content-dim hover:text-content-muted transition-colors">
        &larr; All Plans
      </Link>

      {/* Header */}
      <div className="mt-2 mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-content">{plan.title}</h1>
          <StatusBadge status={plan.status} />
        </div>
        <div className="flex items-center gap-3 mt-1">
          <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: channelColor(plan.channel_id) }} />
          <span className="text-sm text-content-dim">{plan.channel_name}</span>
          {plan.created_at && (
            <span className="text-xs text-content-dim">Created {new Date(plan.created_at).toLocaleString()}</span>
          )}
          {plan.updated_at && (
            <span className="text-xs text-content-dim">Updated {new Date(plan.updated_at).toLocaleString()}</span>
          )}
        </div>
        <PlanIdCopy planId={plan.id} />
      </div>

      {/* Actions */}
      <PlanActions plan={plan} onEdit={() => setEditing(!editing)} />

      {/* Edit form */}
      {editing && plan.status === "draft" && (
        <PlanEditForm plan={plan} onDone={() => setEditing(false)} />
      )}

      {/* Notes */}
      {plan.notes && (
        <div className="mb-6 bg-surface-2 rounded-xl border border-surface-3 p-4">
          <h3 className="text-xs font-medium text-content-muted uppercase tracking-wider mb-2">Notes</h3>
          <MarkdownViewer content={plan.notes} />
        </div>
      )}

      {/* Progress */}
      <div className="mb-4">
        <ProgressBar steps={plan.steps} />
      </div>

      {/* Steps timeline */}
      <div className="mb-6">
        <h3 className="text-sm font-semibold text-content mb-3">
          Steps ({plan.steps.filter((s) => s.status === "complete" || s.status === "skipped").length}/{plan.steps.length})
        </h3>
        <div className="space-y-2">
          {plan.steps.map((step, idx) => {
            const isNext = plan.steps.findIndex(
              (s) => s.status === "pending" || s.status === "in_progress" || s.status === "awaiting_approval",
            ) === idx;
            return <StepCard key={step.position} step={step} plan={plan} isNext={isNext} />;
          })}
        </div>
      </div>

      {/* Meta */}
      {Object.keys(plan.meta).length > 0 && (
        <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
          <h3 className="text-xs font-medium text-content-muted uppercase tracking-wider mb-2">Metadata</h3>
          <div className="space-y-1">
            {Object.entries(plan.meta).map(([k, v]) => (
              <div key={k} className="flex gap-2 text-xs">
                <span className="text-content-dim w-24 flex-shrink-0">{k}</span>
                <span className="text-content-muted">{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Plan ID copy
// ---------------------------------------------------------------------------

function PlanIdCopy({ planId }: { planId: string }) {
  const [copied, setCopied] = useState(false);
  const copyId = () => {
    navigator.clipboard.writeText(planId);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="flex items-center gap-1.5 mt-1">
      <span className="text-[10px] text-content-dim font-mono">{planId}</span>
      <button onClick={copyId} className="text-content-dim hover:text-content-muted transition-colors">
        {copied ? <Check size={11} /> : <Copy size={11} />}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Plan actions
// ---------------------------------------------------------------------------

function PlanActions({ plan, onEdit }: { plan: Plan; onEdit: () => void }) {
  const approve = usePlanApprove();
  const reject = usePlanReject();
  const resume = usePlanResume();
  const del = usePlanDelete();
  const rejectConfirm = useConfirm();
  const deleteConfirm = useConfirm();

  return (
    <div className="flex flex-wrap gap-2 mb-6">
      {plan.status === "draft" && (
        <>
          <Btn label="Approve" color="green" loading={approve.isPending}
            onClick={() => approve.mutate({ channelId: plan.channel_id, planId: plan.id })} />
          {!rejectConfirm.confirming ? (
            <Btn label="Reject" color="red" onClick={rejectConfirm.requestConfirm} />
          ) : (
            <Btn label="Confirm Reject" color="red" loading={reject.isPending}
              onClick={() => { reject.mutate({ channelId: plan.channel_id, planId: plan.id }); rejectConfirm.reset(); }} />
          )}
          <Btn label="Edit" color="blue" onClick={onEdit} />
        </>
      )}
      {(plan.status === "executing" || plan.status === "awaiting_approval") && (
        <Btn label="Resume" color="blue" loading={resume.isPending}
          onClick={() => resume.mutate({ channelId: plan.channel_id, planId: plan.id })} />
      )}
      {(plan.status === "draft" || plan.status === "complete" || plan.status === "abandoned") && (
        <>
          {!deleteConfirm.confirming ? (
            <Btn label="Delete" color="red" onClick={deleteConfirm.requestConfirm} />
          ) : (
            <Btn label="Confirm Delete" color="red" loading={del.isPending}
              onClick={() => { del.mutate({ channelId: plan.channel_id, planId: plan.id }); deleteConfirm.reset(); }} />
          )}
        </>
      )}
    </div>
  );
}

function Btn({
  label,
  color,
  loading,
  onClick,
}: {
  label: string;
  color: "green" | "red" | "blue";
  loading?: boolean;
  onClick: () => void;
}) {
  const colors = {
    green: "bg-green-500/20 text-green-300 hover:bg-green-500/30",
    red: "bg-red-500/20 text-red-300 hover:bg-red-500/30",
    blue: "bg-blue-500/20 text-blue-300 hover:bg-blue-500/30",
  };
  return (
    <button onClick={onClick} disabled={loading}
      className={`px-3 py-1.5 text-xs rounded-md transition-colors ${colors[color]} disabled:opacity-50`}>
      {loading ? "..." : label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Step card
// ---------------------------------------------------------------------------

function stepBorderColor(status: string): string {
  switch (status) {
    case "complete": return "border-green-500 bg-green-500/10";
    case "in_progress": return "border-yellow-500 bg-yellow-500/10";
    case "skipped": return "border-surface-4 bg-surface-1";
    case "failed": return "border-red-500 bg-red-500/10";
    case "awaiting_approval": return "border-purple-500 bg-purple-500/10";
    default: return "border-surface-3 bg-surface-1";
  }
}

function StepCard({ step, plan, isNext }: { step: PlanStep; plan: Plan; isNext: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const approveStep = useStepApprove();
  const skipStep = useStepSkip();

  return (
    <div
      className={`rounded-lg border p-3 ${stepBorderColor(step.status)}`}
      style={{ outline: isNext ? "1px solid rgba(99,102,241,0.3)" : "none" }}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex-shrink-0"><StepIcon status={step.status} /></span>
        <div className="flex-1 min-w-0">
          <button onClick={() => setExpanded(!expanded)} className="text-left w-full">
            <p className="text-sm text-content">{step.content}</p>
          </button>

          {/* Inline meta */}
          <div className="flex items-center gap-2 mt-0.5">
            {step.requires_approval && (
              <span className="flex items-center gap-0.5 text-[10px] text-purple-400">
                <ShieldAlert size={10} /> gated
              </span>
            )}
            {step.started_at && step.completed_at && (
              <span className="text-[10px] text-content-dim">{formatDuration(step.started_at, step.completed_at)}</span>
            )}
            {step.started_at && !step.completed_at && (
              <span className="text-[10px] text-content-dim">started {timeAgo(step.started_at)}</span>
            )}
            {step.task_id && (
              <a
                href={`/admin/tasks`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[10px] text-content-dim font-mono hover:text-accent transition-colors"
              >
                task:{step.task_id.slice(0, 8)}
              </a>
            )}
          </div>

          {expanded && (
            <div className="mt-2 space-y-1 text-xs">
              <p className="text-content-dim">Status: {step.status}</p>
              {step.started_at && <p className="text-content-dim">Started: {new Date(step.started_at).toLocaleString()}</p>}
              {step.completed_at && <p className="text-content-dim">Completed: {new Date(step.completed_at).toLocaleString()}</p>}
              {step.result_summary && (
                <div
                  className="mt-2 rounded p-2"
                  style={{
                    backgroundColor: step.status === "failed" ? "rgba(239,68,68,0.06)" : "rgba(34,197,94,0.06)",
                  }}
                >
                  <MarkdownViewer content={step.result_summary} />
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex gap-1 flex-shrink-0">
          {step.status === "awaiting_approval" && plan.status === "awaiting_approval" && (
            <>
              <button onClick={() => approveStep.mutate({ channelId: plan.channel_id, planId: plan.id, position: step.position })}
                className="px-2 py-0.5 text-[10px] rounded bg-green-500/20 text-green-300 hover:bg-green-500/30">Approve</button>
              <button onClick={() => skipStep.mutate({ channelId: plan.channel_id, planId: plan.id, position: step.position })}
                className="px-2 py-0.5 text-[10px] rounded bg-surface-4/40 text-content-muted hover:bg-surface-4/60">Skip</button>
            </>
          )}
          {step.status === "pending" && (plan.status === "executing" || plan.status === "awaiting_approval") && (
            <button onClick={() => skipStep.mutate({ channelId: plan.channel_id, planId: plan.id, position: step.position })}
              className="px-2 py-0.5 text-[10px] rounded bg-surface-4/40 text-content-muted hover:bg-surface-4/60">Skip</button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Edit form with StepListEditor
// ---------------------------------------------------------------------------

function PlanEditForm({ plan, onDone }: { plan: Plan; onDone: () => void }) {
  const [title, setTitle] = useState(plan.title);
  const [notes, setNotes] = useState(plan.notes);
  const [steps, setSteps] = useState<StepDraft[]>(
    plan.steps.map((s) => ({
      key: makeStepKey(),
      content: s.content,
      requires_approval: s.requires_approval,
    })),
  );
  const update = usePlanUpdate();

  const handleSave = async () => {
    const validSteps = steps.filter((s) => s.content.trim());
    if (validSteps.length === 0) return;
    await update.mutateAsync({
      channelId: plan.channel_id,
      planId: plan.id,
      title,
      notes,
      steps: validSteps.map((s) => ({
        content: s.content,
        requires_approval: s.requires_approval,
      })),
    });
    onDone();
  };

  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 p-4 mb-6 space-y-3">
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="w-full bg-surface-1 border border-surface-3 rounded-md px-3 py-2 text-sm text-content"
      />
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Notes"
        rows={2}
        className="w-full bg-surface-1 border border-surface-3 rounded-md px-3 py-2 text-sm text-content placeholder-gray-600 resize-none"
      />
      <div>
        <label className="text-xs text-content-muted mb-1 block">Steps</label>
        <StepListEditor steps={steps} onChange={setSteps} />
      </div>
      <div className="flex gap-2">
        <button onClick={handleSave} disabled={update.isPending}
          className="px-3 py-1.5 text-xs rounded-md bg-accent text-white hover:bg-accent-hover disabled:opacity-50">
          {update.isPending ? "Saving..." : "Save"}
        </button>
        <button onClick={onDone} className="px-3 py-1.5 text-xs rounded-md border border-surface-3 text-content-muted hover:text-content">
          Cancel
        </button>
      </div>
    </div>
  );
}
