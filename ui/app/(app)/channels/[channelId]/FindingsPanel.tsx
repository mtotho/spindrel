import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, Cog } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useThemeTokens } from "@/src/theme/tokens";
import { ComponentRenderer } from "@/src/components/chat/renderers/ComponentRenderer";
import type { TasksResponse, TaskItem } from "@/src/components/shared/TaskConstants";
import type { StepState, StepDef } from "@/src/api/hooks/useTasks";

// ---------------------------------------------------------------------------
// A single finding = a pipeline run paused at step i with awaiting_user_input.
// The widget envelope stored in step_states[i].widget_envelope is what the
// approval UI actually renders; we forward it verbatim to ComponentRenderer.
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
        out.push({
          task,
          stepIndex: i,
          stepDef: steps?.[i] ?? null,
          stepState: st,
        });
      }
    }
  }
  // Newest task first — use run_at or created_at fallback.
  out.sort((a, b) => {
    const ta = a.task.run_at || a.task.created_at || "";
    const tb = b.task.run_at || b.task.created_at || "";
    return tb.localeCompare(ta);
  });
  return out;
}

// ---------------------------------------------------------------------------
// Shared query hook — reused by FindingsPanel (to render) and by the header
// (to show a badge count). Using the same queryKey means react-query
// deduplicates the fetch across both consumers.
// ---------------------------------------------------------------------------

export function useFindings(channelId: string | undefined) {
  const { data } = useQuery({
    queryKey: ["findings", channelId],
    queryFn: () =>
      apiFetch<TasksResponse>(
        // include_children=true: awaiting_user_input step_states live on child
        // tasks (the pipeline runs), which are hidden by default.
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
// Per-finding card — renders widget envelope via ComponentRenderer.
// ---------------------------------------------------------------------------

function FindingCard({ finding }: { finding: Finding }) {
  const t = useThemeTokens();
  const envelope = finding.stepState.widget_envelope;
  const title =
    finding.stepDef?.title || finding.stepDef?.label || finding.task.title || "Pending review";
  const when = finding.stepState.started_at || finding.task.run_at || finding.task.created_at;

  return (
    <article className="rounded-md bg-surface border border-surface-border p-3 flex flex-col gap-2">
      <header className="flex flex-row items-center justify-between gap-2">
        <h4 className="text-sm font-medium text-text truncate flex-1">{title}</h4>
        {when && (
          <span className="text-[10px] text-text-dim shrink-0">
            {new Date(when).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </header>
      {envelope ? (
        <div className="text-sm">
          <ComponentRenderer body={envelope as any} t={t} />
        </div>
      ) : (
        <div className="text-xs text-text-dim italic">
          (Awaiting input — no widget rendered)
        </div>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

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

      {findings.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 p-6 text-text-dim">
          <Cog size={24} className="opacity-40" />
          <span className="text-sm">No pending reviews</span>
          <span className="text-xs text-center opacity-75">
            When a pipeline pauses for approval, it'll appear here.
          </span>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
          {findings.map((f) => (
            <FindingCard key={`${f.task.id}:${f.stepIndex}`} finding={f} />
          ))}
        </div>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Mobile bottom-sheet variant — same data, fullscreen overlay
// ---------------------------------------------------------------------------

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
        {findings.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-2 p-6 text-text-dim">
            <Cog size={24} className="opacity-40" />
            <span className="text-sm">No pending reviews</span>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
            {findings.map((f) => (
              <FindingCard key={`${f.task.id}:${f.stepIndex}`} finding={f} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

