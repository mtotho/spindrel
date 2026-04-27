import { useMemo, useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Cog, Trash2, MoreHorizontal, SkipForward, Loader2 } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import type { TasksResponse, TaskItem } from "@/src/components/shared/TaskConstants";
import type { StepState, StepDef } from "@/src/api/hooks/useTasks";
import { useResolveStep } from "@/src/api/hooks/useResolveStep";
import { InlineApprovalReview } from "@/src/components/chat/InlineApprovalReview";
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
// Delete mutation — secondary action, tucked behind a menu.
// ---------------------------------------------------------------------------

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
// Per-finding card: header + shared approval review + overflow menu.
// Skip is the primary cleanup action (resolves with empty response, keeps
// the run visible in admin history). Delete is demoted to a secondary menu.
// ---------------------------------------------------------------------------

function relTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!then) return "";
  const diff = Date.now() - then;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

function proposalCount(finding: Finding): number {
  const schema = (finding.stepState.response_schema as any) || {};
  if (Array.isArray(schema.items)) return schema.items.length;
  const tmpl = (finding.stepState.widget_envelope as any)?.template;
  const fromTmpl = tmpl?.proposals;
  if (Array.isArray(fromTmpl)) return fromTmpl.length;
  return 0;
}

function FindingCard({ finding }: { finding: Finding }) {
  const envelope = (finding.stepState.widget_envelope as any) || {};
  const template = envelope.template || {};
  const kind = template.kind;

  const deleteMut = useDeleteTask();
  const resolveMut = useResolveStep();

  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  const headerTitle =
    envelope.title ||
    finding.stepDef?.title ||
    finding.stepDef?.label ||
    template.title ||
    finding.task.title ||
    "Pending review";
  const when = finding.stepState.started_at || finding.task.run_at || finding.task.created_at;
  const count = proposalCount(finding);

  const handleSkip = () => {
    resolveMut.mutate({
      taskId: finding.task.id,
      stepIndex: finding.stepIndex,
      response: {},
    });
    setMenuOpen(false);
  };

  const handleDelete = () => {
    deleteMut.mutate(finding.task.id);
    setMenuOpen(false);
    setConfirmDelete(false);
  };

  return (
    <article className="rounded-md bg-surface-raised/40 hover:bg-surface-overlay/45 transition-colors p-3 flex flex-col gap-2">
      <header className="flex flex-row items-start justify-between gap-2">
        <div className="flex flex-col min-w-0 flex-1">
          <h4 className="text-sm font-medium text-text truncate">{headerTitle}</h4>
          <span className="text-[10px] text-text-dim flex flex-row flex-wrap items-center gap-1.5">
            <span className="truncate">{finding.task.title ?? "pipeline"}</span>
            {count > 0 && (
              <>
                <span className="opacity-50">·</span>
                <span>
                  {count} proposal{count === 1 ? "" : "s"}
                </span>
              </>
            )}
            {when && (
              <>
                <span className="opacity-50">·</span>
                <span>{relTime(when)}</span>
              </>
            )}
          </span>
        </div>
        <div ref={menuRef} className="relative shrink-0">
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="p-1 text-text-dim/70 hover:text-text rounded"
            title="More actions"
            aria-label="More actions"
          >
            <MoreHorizontal size={14} />
          </button>
          {menuOpen && (
            <div
              className="absolute right-0 top-6 z-10 w-40 rounded-md border border-surface-border
                         bg-surface-raised py-1"
            >
              <button
                onClick={handleSkip}
                disabled={resolveMut.isPending}
                className="w-full px-3 py-1.5 text-left text-[11px] text-text-dim
                           hover:bg-surface-overlay hover:text-text flex items-center gap-2
                           disabled:opacity-50"
              >
                {resolveMut.isPending ? (
                  <Loader2 size={11} className="animate-spin" />
                ) : (
                  <SkipForward size={11} />
                )}
                Skip review
              </button>
              <button
                onClick={() => setConfirmDelete(true)}
                disabled={deleteMut.isPending}
                className="w-full px-3 py-1.5 text-left text-[11px] text-danger
                           hover:bg-danger/10 flex items-center gap-2
                           disabled:opacity-50"
              >
                <Trash2 size={11} />
                Delete run
              </button>
            </div>
          )}
        </div>
      </header>

      {confirmDelete && (
        <div className="rounded-md bg-danger/10 p-2 flex flex-col gap-1.5">
          <span className="text-[11px] text-danger">
            Delete the pipeline run? This removes it from admin history too.
          </span>
          <div className="flex flex-row gap-1.5">
            <button
              onClick={handleDelete}
              disabled={deleteMut.isPending}
              className="flex-1 px-2 py-1 rounded bg-danger/20 text-danger text-[11px]
                         hover:bg-danger/30 disabled:opacity-50"
            >
              {deleteMut.isPending ? "Deleting..." : "Delete"}
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="flex-1 px-2 py-1 rounded text-[11px]
                         text-text-dim hover:bg-surface-overlay hover:text-text"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {kind === "approval_review" ? (
        <InlineApprovalReview
          taskId={finding.task.id}
          stepIndex={finding.stepIndex}
          widgetEnvelope={finding.stepState.widget_envelope}
          responseSchema={finding.stepState.response_schema}
        />
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

function FindingsBody({
  findings,
  subtitle,
}: {
  findings: Finding[];
  subtitle?: string;
}) {
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
      {subtitle && (
        <span className="text-[10px] text-text-dim uppercase tracking-wider">
          {subtitle}
        </span>
      )}
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
    <aside className="hidden md:flex w-[22rem] shrink-0 flex-col
                      bg-surface-raised">
      <header className="h-12 px-4 flex flex-row items-center justify-between shrink-0">
        <div className="flex flex-row items-center gap-2">
          <span className="text-sm font-semibold text-text">Findings</span>
          {findings.length > 0 && (
            <span className="text-[10px] text-accent bg-accent/10
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
      <FindingsBody findings={findings} subtitle="Pending reviews on this channel" />
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
        className={cn(
          "absolute inset-x-0 bottom-0 h-[85vh] bg-surface-raised",
          "rounded-t-lg flex flex-col",
        )}
      >
        <header className="h-12 px-4 flex flex-row items-center justify-between shrink-0">
          <div className="flex flex-row items-center gap-2">
            <span className="text-sm font-semibold text-text">Findings</span>
            {findings.length > 0 && (
              <span className="text-[10px] text-accent bg-accent/10
                               rounded-full px-1.5 py-0.5 font-medium">
                {findings.length}
              </span>
            )}
          </div>
          <button onClick={onClose} className="p-1 text-text-dim hover:text-text">
            <X size={16} />
          </button>
        </header>
        <FindingsBody findings={findings} subtitle="Pending reviews on this channel" />
      </div>
    </div>
  );
}
