import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { ShieldAlert, Copy, Check } from "lucide-react";
import { useOverview } from "../hooks/useOverview";
import {
  usePlans,
  usePlanCreate,
  usePlanApprove,
  usePlanReject,
  usePlanResume,
  usePlanDelete,
  useStepApprove,
  useStepSkip,
} from "../hooks/useMC";
import { useScope } from "../lib/ScopeContext";
import { useConfirm } from "../lib/useConfirm";
import { channelColor } from "../lib/colors";
import { timeAgo, formatDuration } from "../lib/dates";
import { STATUS_FILTERS } from "../lib/planConstants";
import { StepIcon, ProgressBar, StatusBadge } from "../components/PlanComponents";
import ChannelFilterBar from "../components/ChannelFilterBar";
import StepListEditor, { makeStepKey } from "../components/StepListEditor";
import type { StepDraft } from "../components/StepListEditor";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import EmptyState from "../components/EmptyState";
import InfoPanel from "../components/InfoPanel";
import ScopeToggle from "../components/ScopeToggle";
import type { Plan, PlanStep } from "../lib/types";

export default function Plans() {
  const { scope } = useScope();
  const [statusFilter, setStatusFilter] = useState("all");
  const [channelFilter, setChannelFilter] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const { data: plans, isLoading, error, refetch } = usePlans(
    scope,
    statusFilter !== "all" ? statusFilter : undefined,
  );
  const { data: overview } = useOverview(scope);

  const channels = useMemo(() => {
    if (!overview?.channels) return [];
    return overview.channels.filter((ch) => ch.workspace_enabled);
  }, [overview]);

  const filtered = useMemo(() => {
    if (!plans) return [];
    if (!channelFilter) return plans;
    return plans.filter((p) => p.channel_id === channelFilter);
  }, [plans, channelFilter]);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-content">Plans</h1>
          <p className="text-sm text-content-dim mt-1">Structured execution plans</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="px-3 py-1.5 text-xs rounded-md border border-accent bg-accent text-white hover:bg-accent-hover transition-colors"
          >
            + New Plan
          </button>
          <ScopeToggle />
        </div>
      </div>

      <InfoPanel
        id="plans"
        description="Plans track multi-step execution with approval gates and human oversight."
        tips={[
          "Plans are channel-scoped — each plan belongs to one channel.",
          "Approval gates pause execution until you approve or skip.",
          "For cross-bot automation, use Workflows instead.",
        ]}
        links={[{ label: "Workflows (Admin)", to: "/admin/workflows", external: true }]}
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-6">
        <div className="flex gap-1">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-2.5 py-1 text-xs rounded-md border capitalize transition-colors ${
                statusFilter === s
                  ? "border-accent bg-accent text-white"
                  : "border-surface-3 text-content-muted hover:text-content"
              }`}
            >
              {s.replace(/_/g, " ")}
            </button>
          ))}
        </div>

        {channels.length > 1 && (
          <>
            <div className="w-px h-5 bg-surface-3" />
            <ChannelFilterBar channels={channels} value={channelFilter} onChange={setChannelFilter} />
          </>
        )}
      </div>

      {/* Create form */}
      {showCreate && channels.length > 0 && (
        <PlanCreateForm channels={channels} onClose={() => setShowCreate(false)} />
      )}

      {/* Content */}
      {isLoading ? (
        <LoadingSpinner />
      ) : error ? (
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="▷"
          title="No plans found"
          description="Plans are created by bots or manually. They track multi-step execution with optional approval gates."
          tips={[
            "Ask a bot to 'draft a plan for...' to get started.",
            "Or click + New Plan above to create one manually.",
          ]}
        />
      ) : (
        <div className="space-y-4">
          {filtered.map((plan) => (
            <PlanCard key={plan.id} plan={plan} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Plan card
// ---------------------------------------------------------------------------

function PlanCard({ plan }: { plan: Plan }) {
  const autoExpand = ["draft", "executing", "awaiting_approval"].includes(plan.status);
  const [expanded, setExpanded] = useState(autoExpand);
  const approve = usePlanApprove();
  const reject = usePlanReject();
  const resume = usePlanResume();
  const del = usePlanDelete();
  const stepApprove = useStepApprove();
  const stepSkip = useStepSkip();
  const rejectConfirm = useConfirm();
  const deleteConfirm = useConfirm();
  const [copied, setCopied] = useState(false);

  const copyId = () => {
    navigator.clipboard.writeText(plan.id);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Find next step
  const nextStepIdx = plan.steps.findIndex(
    (s) => s.status === "pending" || s.status === "in_progress" || s.status === "awaiting_approval",
  );

  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-4 py-3 hover:bg-surface-3 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-content truncate">{plan.title}</span>
              <StatusBadge status={plan.status} />
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span
                className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: channelColor(plan.channel_id) }}
              />
              <span className="text-xs text-content-dim">{plan.channel_name}</span>
              {plan.created_at && (
                <span className="text-xs text-content-dim">{new Date(plan.created_at).toLocaleDateString()}</span>
              )}
            </div>
          </div>
          <ProgressBar steps={plan.steps} />
          <span className="text-xs text-content-dim">{expanded ? "▲" : "▼"}</span>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-surface-3 pt-3">
          {/* Plan ID */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-content-dim font-mono">{plan.id}</span>
            <button onClick={copyId} className="text-content-dim hover:text-content-muted transition-colors">
              {copied ? <Check size={11} /> : <Copy size={11} />}
            </button>
          </div>

          {/* Actions */}
          <div className="flex flex-wrap gap-2">
            {plan.status === "draft" && (
              <>
                <ActionButton
                  label="Approve"
                  color="green"
                  loading={approve.isPending}
                  onClick={() => approve.mutate({ channelId: plan.channel_id, planId: plan.id })}
                />
                {!rejectConfirm.confirming ? (
                  <ActionButton label="Reject" color="red" onClick={rejectConfirm.requestConfirm} />
                ) : (
                  <ActionButton
                    label="Confirm Reject"
                    color="red"
                    loading={reject.isPending}
                    onClick={() => { reject.mutate({ channelId: plan.channel_id, planId: plan.id }); rejectConfirm.reset(); }}
                  />
                )}
              </>
            )}
            {(plan.status === "executing" || plan.status === "awaiting_approval") && (
              <ActionButton
                label="Resume"
                color="blue"
                loading={resume.isPending}
                onClick={() => resume.mutate({ channelId: plan.channel_id, planId: plan.id })}
              />
            )}
            {(plan.status === "draft" || plan.status === "complete" || plan.status === "abandoned") && (
              <>
                {!deleteConfirm.confirming ? (
                  <ActionButton label="Delete" color="red" onClick={deleteConfirm.requestConfirm} />
                ) : (
                  <ActionButton
                    label="Confirm Delete"
                    color="red"
                    loading={del.isPending}
                    onClick={() => { del.mutate({ channelId: plan.channel_id, planId: plan.id }); deleteConfirm.reset(); }}
                  />
                )}
              </>
            )}
            <Link
              to={`/plans/${plan.channel_id}/${plan.id}`}
              className="px-2.5 py-1 text-xs rounded-md border border-surface-3 text-content-muted hover:text-content transition-colors"
            >
              Full detail &rarr;
            </Link>
          </div>

          {plan.notes && <p className="text-xs text-content-muted italic">{plan.notes}</p>}

          {/* Steps */}
          {plan.steps.length > 0 && (
            <div className="space-y-1.5">
              {plan.steps.map((step, idx) => (
                <StepRow
                  key={step.position}
                  step={step}
                  plan={plan}
                  isNext={idx === nextStepIdx}
                  onApprove={() => stepApprove.mutate({ channelId: plan.channel_id, planId: plan.id, position: step.position })}
                  onSkip={() => stepSkip.mutate({ channelId: plan.channel_id, planId: plan.id, position: step.position })}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step row
// ---------------------------------------------------------------------------

function StepRow({
  step,
  plan,
  isNext,
  onApprove,
  onSkip,
}: {
  step: PlanStep;
  plan: Plan;
  isNext: boolean;
  onApprove: () => void;
  onSkip: () => void;
}) {
  return (
    <div
      className="flex items-start gap-2 py-1.5 px-2 rounded-md transition-colors"
      style={{
        backgroundColor: isNext ? "rgba(99,102,241,0.06)" : "transparent",
      }}
    >
      <span className="mt-0.5 flex-shrink-0"><StepIcon status={step.status} /></span>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-content">{step.content}</p>
        <div className="flex items-center gap-2 mt-0.5">
          {step.requires_approval && step.status !== "complete" && step.status !== "skipped" && (
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
              href="/admin/tasks"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[10px] text-content-dim font-mono hover:text-accent transition-colors"
            >
              task:{step.task_id.slice(0, 8)}
            </a>
          )}
        </div>
        {step.result_summary && (
          <div
            className="text-[10px] mt-1 px-2 py-1 rounded"
            style={{
              backgroundColor: step.status === "failed" ? "rgba(239,68,68,0.06)" : "rgba(34,197,94,0.06)",
              color: step.status === "failed" ? "#fca5a5" : "#86efac",
            }}
          >
            {step.result_summary}
          </div>
        )}
      </div>
      <div className="flex gap-1 flex-shrink-0">
        {step.status === "awaiting_approval" && plan.status === "awaiting_approval" && (
          <>
            <button onClick={onApprove} className="px-2 py-0.5 text-[10px] rounded bg-green-500/20 text-green-300 hover:bg-green-500/30 transition-colors">
              Approve
            </button>
            <button onClick={onSkip} className="px-2 py-0.5 text-[10px] rounded bg-surface-4/40 text-content-muted hover:bg-surface-4/60 transition-colors">
              Skip
            </button>
          </>
        )}
        {step.status === "pending" && (plan.status === "executing" || plan.status === "awaiting_approval") && (
          <button onClick={onSkip} className="px-2 py-0.5 text-[10px] rounded bg-surface-4/40 text-content-muted hover:bg-surface-4/60 transition-colors flex-shrink-0">
            Skip
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Action button
// ---------------------------------------------------------------------------

function ActionButton({
  label,
  color,
  loading,
  onClick,
}: {
  label: string;
  color: "green" | "red" | "blue" | "yellow";
  loading?: boolean;
  onClick: () => void;
}) {
  const colors = {
    green: "bg-green-500/20 text-green-300 hover:bg-green-500/30",
    red: "bg-red-500/20 text-red-300 hover:bg-red-500/30",
    blue: "bg-blue-500/20 text-blue-300 hover:bg-blue-500/30",
    yellow: "bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30",
  };
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`px-2.5 py-1 text-xs rounded-md transition-colors ${colors[color]} disabled:opacity-50`}
    >
      {loading ? "..." : label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Create form with StepListEditor
// ---------------------------------------------------------------------------

function PlanCreateForm({
  channels,
  onClose,
}: {
  channels: Array<{ id: string; name: string | null }>;
  onClose: () => void;
}) {
  const [channelId, setChannelId] = useState(channels[0]?.id || "");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [steps, setSteps] = useState<StepDraft[]>([
    { key: makeStepKey(), content: "", requires_approval: false },
  ]);
  const create = usePlanCreate();

  const handleSubmit = async () => {
    if (!title.trim() || !channelId) return;
    const validSteps = steps.filter((s) => s.content.trim());
    if (validSteps.length === 0) return;
    await create.mutateAsync({
      channelId,
      title,
      notes: notes || undefined,
      steps: validSteps.map((s) => ({
        content: s.content,
        requires_approval: s.requires_approval,
      })),
    });
    onClose();
  };

  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 p-4 mb-6 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-content">New Plan</h3>
        <button onClick={onClose} className="text-xs text-content-dim hover:text-content-muted">Cancel</button>
      </div>

      <select
        value={channelId}
        onChange={(e) => setChannelId(e.target.value)}
        className="w-full bg-surface-1 border border-surface-3 rounded-md px-3 py-2 text-sm text-content"
      >
        {channels.map((ch) => (
          <option key={ch.id} value={ch.id}>{ch.name || ch.id.slice(0, 8)}</option>
        ))}
      </select>

      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Plan title"
        className="w-full bg-surface-1 border border-surface-3 rounded-md px-3 py-2 text-sm text-content placeholder-gray-600"
      />

      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Notes (optional)"
        rows={2}
        className="w-full bg-surface-1 border border-surface-3 rounded-md px-3 py-2 text-sm text-content placeholder-gray-600 resize-none"
      />

      <div>
        <label className="text-xs text-content-muted mb-1 block">Steps</label>
        <StepListEditor steps={steps} onChange={setSteps} />
      </div>

      <button
        onClick={handleSubmit}
        disabled={create.isPending || !title.trim() || steps.every((s) => !s.content.trim())}
        className="px-4 py-2 text-xs rounded-md bg-accent text-white hover:bg-accent-hover transition-colors disabled:opacity-50"
      >
        {create.isPending ? "Creating..." : "Create Plan"}
      </button>
    </div>
  );
}
