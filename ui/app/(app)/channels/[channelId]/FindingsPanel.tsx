import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Cog, Check, XCircle, Loader2, AlertTriangle, Trash2 } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import type { TasksResponse, TaskItem } from "@/src/components/shared/TaskConstants";
import type { StepState, StepDef } from "@/src/api/hooks/useTasks";
import { cn } from "@/src/lib/cn";

// ---------------------------------------------------------------------------
// A single finding = a pipeline run paused at step i with awaiting_user_input.
// The widget_envelope stored in step_states[i] has shape {template, args,
// title} where template.kind drives how we render. Current kinds: "approval_review".
// ---------------------------------------------------------------------------

export interface Finding {
  task: TaskItem;
  stepIndex: number;
  stepDef: StepDef | null;
  stepState: StepState;
}

interface ProposalItem {
  id: string;
  label?: string;
  rationale?: string;
  diff_preview?: string;
  scope?: string;
  target_path?: string;
  target_method?: string;
  [k: string]: any;
}

function collectFindings(rows: TaskItem[]): Finding[] {
  const out: Finding[] = [];
  for (const task of rows) {
    const states = (task as any).step_states as StepState[] | null | undefined;
    const steps = (task as any).steps as StepDef[] | null | undefined;
    if (!Array.isArray(states)) continue;
    for (let i = 0; i < states.length; i++) {
      const st = states[i];
      if (st?.status === "awaiting_user_input") {
        out.push({ task, stepIndex: i, stepDef: steps?.[i] ?? null, stepState: st });
      }
    }
  }
  out.sort((a, b) => {
    const ta = a.task.run_at || a.task.created_at || "";
    const tb = b.task.run_at || b.task.created_at || "";
    return tb.localeCompare(ta);
  });
  return out;
}

export function useFindings(channelId: string | undefined) {
  const { data } = useQuery({
    queryKey: ["findings", channelId],
    queryFn: () =>
      apiFetch<TasksResponse>(
        `/api/v1/admin/tasks?limit=200&include_children=true&channel_id=${encodeURIComponent(channelId ?? "")}`,
      ),
    enabled: !!channelId,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const findings = useMemo(() => {
    if (!data) return [];
    return collectFindings([...(data.tasks ?? []), ...(data.schedules ?? [])]);
  }, [data]);

  return { findings, count: findings.length };
}

// ---------------------------------------------------------------------------
// Resolve / cancel mutations
// ---------------------------------------------------------------------------

function useResolveStep() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      taskId,
      stepIndex,
      response,
    }: {
      taskId: string;
      stepIndex: number;
      response: Record<string, any>;
    }) =>
      apiFetch(`/api/v1/admin/tasks/${taskId}/steps/${stepIndex}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["findings"] });
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
      qc.invalidateQueries({ queryKey: ["orchestrator-runs"] });
    },
  });
}

function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      apiFetch(`/api/v1/admin/tasks/${taskId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["findings"] });
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
      qc.invalidateQueries({ queryKey: ["orchestrator-runs"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Approval Review renderer — handles {template: {kind: "approval_review"}} +
// response_schema.type === "multi_item" or "binary".
// ---------------------------------------------------------------------------

function ProposalRow({
  item,
  decision,
  onDecide,
}: {
  item: ProposalItem;
  decision: "approve" | "reject" | undefined;
  onDecide: (d: "approve" | "reject") => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const label = item.label || item.id;
  const summary = item.rationale || item.diff_preview || "";

  return (
    <div
      className={cn(
        "rounded-md border p-2.5 flex flex-col gap-2 transition-colors",
        decision === "approve" && "border-emerald-500/50 bg-emerald-500/5",
        decision === "reject" && "border-red-500/50 bg-red-500/5",
        !decision && "border-surface-border bg-surface",
      )}
    >
      <div className="flex flex-row items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5 min-w-0 flex-1">
          <span className="text-xs font-semibold text-text truncate">{label}</span>
          {item.scope && item.target_path && (
            <span className="text-[10px] text-text-dim font-mono truncate">
              {item.target_method || "PATCH"} {item.target_path}
            </span>
          )}
          {summary && (
            <p className={cn(
              "text-[11px] text-text-dim leading-snug",
              expanded ? "" : "line-clamp-2",
            )}>
              {summary}
            </p>
          )}
          {summary && summary.length > 120 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-[10px] text-accent hover:underline self-start"
            >
              {expanded ? "Less" : "More"}
            </button>
          )}
        </div>
      </div>
      <div className="flex flex-row gap-1.5 shrink-0">
        <button
          onClick={() => onDecide("approve")}
          className={cn(
            "flex-1 inline-flex items-center justify-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-colors",
            decision === "approve"
              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/50"
              : "bg-surface-raised text-text-dim border border-surface-border hover:bg-emerald-500/10 hover:text-emerald-400",
          )}
        >
          <Check size={11} />
          Approve
        </button>
        <button
          onClick={() => onDecide("reject")}
          className={cn(
            "flex-1 inline-flex items-center justify-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-colors",
            decision === "reject"
              ? "bg-red-500/20 text-red-400 border border-red-500/50"
              : "bg-surface-raised text-text-dim border border-surface-border hover:bg-red-500/10 hover:text-red-400",
          )}
        >
          <XCircle size={11} />
          Reject
        </button>
      </div>
    </div>
  );
}

function ApprovalReviewRenderer({ finding }: { finding: Finding }) {
  const schema = (finding.stepState.response_schema as any) || {};
  const schemaType = schema.type;
  const items: ProposalItem[] = Array.isArray(schema.items) ? schema.items : [];
  const [decisions, setDecisions] = useState<Record<string, "approve" | "reject">>({});
  const [binaryDecision, setBinaryDecision] = useState<"approve" | "reject" | undefined>(undefined);
  const resolveMut = useResolveStep();

  const handleSubmit = () => {
    let response: Record<string, any>;
    if (schemaType === "binary") {
      if (!binaryDecision) return;
      response = { decision: binaryDecision };
    } else {
      response = { ...decisions };
      for (const it of items) {
        if (!response[it.id]) response[it.id] = "reject";
      }
    }
    resolveMut.mutate({
      taskId: finding.task.id,
      stepIndex: finding.stepIndex,
      response,
    });
  };

  if (schemaType === "multi_item" && items.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        <div className="text-[11px] text-text-dim italic flex items-center gap-1.5">
          <AlertTriangle size={11} className="text-amber-500" />
          No proposals — the agent step returned an empty list.
        </div>
        <button
          onClick={() =>
            resolveMut.mutate({
              taskId: finding.task.id,
              stepIndex: finding.stepIndex,
              response: {},
            })
          }
          disabled={resolveMut.isPending}
          className="px-2.5 py-1 text-[11px] rounded-md bg-surface-raised border border-surface-border
                     text-text-dim hover:text-text self-start disabled:opacity-50"
        >
          {resolveMut.isPending ? "Resolving..." : "Dismiss"}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {schemaType === "binary" ? (
        <div className="flex flex-row gap-1.5">
          <button
            onClick={() => setBinaryDecision("approve")}
            className={cn(
              "flex-1 inline-flex items-center justify-center gap-1 px-2 py-1.5 rounded text-xs font-medium",
              binaryDecision === "approve"
                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/50"
                : "bg-surface-raised text-text-dim border border-surface-border hover:text-text",
            )}
          >
            <Check size={12} /> Approve
          </button>
          <button
            onClick={() => setBinaryDecision("reject")}
            className={cn(
              "flex-1 inline-flex items-center justify-center gap-1 px-2 py-1.5 rounded text-xs font-medium",
              binaryDecision === "reject"
                ? "bg-red-500/20 text-red-400 border border-red-500/50"
                : "bg-surface-raised text-text-dim border border-surface-border hover:text-text",
            )}
          >
            <XCircle size={12} /> Reject
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {items.map((item) => (
            <ProposalRow
              key={item.id}
              item={item}
              decision={decisions[item.id]}
              onDecide={(d) => setDecisions((s) => ({ ...s, [item.id]: d }))}
            />
          ))}
        </div>
      )}

      {resolveMut.isError && (
        <div className="text-[11px] text-red-400">
          {(resolveMut.error as Error)?.message ?? "Resolve failed"}
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={
          resolveMut.isPending ||
          (schemaType === "binary" ? !binaryDecision : false)
        }
        className="mt-1 px-3 py-1.5 rounded-md bg-accent text-white text-xs font-semibold
                   hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed
                   inline-flex items-center justify-center gap-1.5"
      >
        {resolveMut.isPending && <Loader2 size={12} className="animate-spin" />}
        {schemaType === "multi_item"
          ? `Submit (${Object.values(decisions).filter((d) => d === "approve").length} approved, ${items.length - Object.values(decisions).filter((d) => d === "approve").length} rejected)`
          : "Submit"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-finding card with a Cancel option (deletes the whole pipeline run —
// the cleanup path for old stuck reviews the user can't or won't resolve).
// ---------------------------------------------------------------------------

function FindingCard({ finding }: { finding: Finding }) {
  const envelope = (finding.stepState.widget_envelope as any) || {};
  const template = envelope.template || {};
  const kind = template.kind;
  const deleteMut = useDeleteTask();

  const title =
    envelope.title ||
    finding.stepDef?.title ||
    finding.stepDef?.label ||
    template.title ||
    finding.task.title ||
    "Pending review";
  const when = finding.stepState.started_at || finding.task.run_at || finding.task.created_at;

  return (
    <article className="rounded-md bg-surface border border-surface-border p-3 flex flex-col gap-2">
      <header className="flex flex-row items-start justify-between gap-2">
        <div className="flex flex-col min-w-0 flex-1">
          <h4 className="text-sm font-medium text-text truncate">{title}</h4>
          <span className="text-[10px] text-text-dim">
            {finding.task.title ?? finding.task.id} · {when ? new Date(when).toLocaleString() : ""}
          </span>
        </div>
        <button
          onClick={() => {
            if (confirm("Cancel this pipeline run? The stuck review will be deleted.")) {
              deleteMut.mutate(finding.task.id);
            }
          }}
          disabled={deleteMut.isPending}
          className="p-1 text-text-dim/60 hover:text-red-400 shrink-0"
          title="Cancel this run and delete it"
        >
          <Trash2 size={12} />
        </button>
      </header>

      {kind === "approval_review" ? (
        <ApprovalReviewRenderer finding={finding} />
      ) : (
        <div className="text-[11px] text-text-dim italic">
          Unsupported widget kind: {kind || "(unspecified)"}
        </div>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Main panels — desktop right rail + mobile bottom sheet.
// ---------------------------------------------------------------------------

function FindingsBody({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 p-6 text-text-dim">
        <Cog size={24} className="opacity-40" />
        <span className="text-sm">No pending reviews</span>
        <span className="text-xs text-center opacity-75">
          When a pipeline pauses for approval, it'll appear here.
        </span>
      </div>
    );
  }
  return (
    <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
      {findings.map((f) => (
        <FindingCard key={`${f.task.id}:${f.stepIndex}`} finding={f} />
      ))}
    </div>
  );
}

export function FindingsPanel({
  channelId,
  onClose,
}: {
  channelId: string;
  onClose: () => void;
}) {
  const { findings } = useFindings(channelId);

  return (
    <aside className="hidden md:flex w-80 shrink-0 flex-col
                      bg-surface-raised border-l border-surface-border">
      <header className="h-12 px-4 flex flex-row items-center justify-between
                         border-b border-surface-border shrink-0">
        <div className="flex flex-row items-center gap-2">
          <span className="text-sm font-semibold text-text">Findings</span>
          {findings.length > 0 && (
            <span className="text-[10px] text-accent bg-accent/10 border border-accent/30
                             rounded-full px-1.5 py-0.5 font-medium">
              {findings.length}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 text-text-dim hover:text-text rounded"
          title="Hide findings"
        >
          <X size={14} />
        </button>
      </header>
      <FindingsBody findings={findings} />
    </aside>
  );
}

export function FindingsSheet({
  channelId,
  open,
  onClose,
}: {
  channelId: string;
  open: boolean;
  onClose: () => void;
}) {
  const { findings } = useFindings(channelId);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[10010] md:hidden">
      <div className="absolute inset-0 bg-black/45" onClick={onClose} />
      <div
        className="absolute inset-x-0 bottom-0 h-[85vh] bg-surface-raised
                   border-t border-surface-border rounded-t-xl flex flex-col"
      >
        <header className="h-12 px-4 flex flex-row items-center justify-between
                           border-b border-surface-border shrink-0">
          <div className="flex flex-row items-center gap-2">
            <span className="text-sm font-semibold text-text">Findings</span>
            {findings.length > 0 && (
              <span className="text-[10px] text-accent bg-accent/10 border border-accent/30
                               rounded-full px-1.5 py-0.5 font-medium">
                {findings.length}
              </span>
            )}
          </div>
          <button onClick={onClose} className="p-1 text-text-dim hover:text-text">
            <X size={16} />
          </button>
        </header>
        <FindingsBody findings={findings} />
      </div>
    </div>
  );
}
