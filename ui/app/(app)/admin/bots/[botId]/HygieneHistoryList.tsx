import { useState } from "react";
import { ChevronDown, ChevronRight, Clock, FileText, Zap } from "lucide-react";
import { ToolCallsList } from "@/src/components/shared/ToolCallsList";
import { cn } from "@/src/lib/cn";
import {
  SettingsGroupLabel,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { TraceActionButton } from "@/src/components/shared/TraceActionButton";
import type { MemoryHygieneRun } from "@/src/api/hooks/useMemoryHygiene";
import type { LearningHygieneRun } from "@/src/api/hooks/useLearningOverview";

type RunWithExtras = (MemoryHygieneRun | LearningHygieneRun) & {
  bot_name?: string;
  files_affected?: string[];
};

function statusVariant(status: string): "success" | "danger" | "skipped" | "neutral" {
  if (status === "complete") return "success";
  if (status === "failed") return "danger";
  if (status === "skipped") return "skipped";
  return "neutral";
}

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function jobTypeLabel(run: RunWithExtras): string | null {
  if (!("job_type" in run) || !run.job_type) return null;
  return run.job_type === "skill_review" ? "skills" : "maint";
}

function jobTypeClass(run: RunWithExtras): string {
  if (!("job_type" in run) || run.job_type !== "skill_review") {
    return "bg-warning/[0.06] text-warning-muted";
  }
  return "bg-purple/[0.06] text-purple";
}

export function HygieneHistoryList({ runs, showBotName }: { runs: RunWithExtras[]; showBotName?: boolean }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <>
      <SettingsGroupLabel label="Recent Runs" />
      <div className="flex flex-col gap-1">
        {runs.map((run) => {
          const isExpanded = expandedId === run.id;
          const hasContent = Boolean(run.result || run.error || run.correlation_id);
          const isFailed = run.status === "failed";
          const isSkipped = run.status === "skipped";
          const jobLabel = jobTypeLabel(run);

          return (
            <div key={run.id}>
              <button
                type="button"
                onClick={() => hasContent && setExpandedId(isExpanded ? null : run.id)}
                className={cn(
                  "flex w-full flex-col gap-1 border border-surface-border/45 px-3 py-2 text-left transition-colors",
                  isExpanded ? "rounded-t-md" : "rounded-md",
                  isExpanded ? "bg-surface-overlay/60" : "bg-surface-raised/40 hover:bg-surface-overlay/45",
                  isFailed && !isExpanded && "bg-danger/[0.04]",
                  isSkipped && !isExpanded && "bg-purple/[0.035]",
                  hasContent ? "cursor-pointer" : "cursor-default",
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    {hasContent && (
                      isExpanded
                        ? <ChevronDown size={12} className="shrink-0 text-text-dim" />
                        : <ChevronRight size={12} className="shrink-0 text-text-dim" />
                    )}
                    {showBotName && run.bot_name && (
                      <span className="truncate text-[11px] font-semibold text-text">
                        {run.bot_name}
                      </span>
                    )}
                    {jobLabel && (
                      <span
                        className={cn(
                          "shrink-0 rounded px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.04em]",
                          jobTypeClass(run),
                        )}
                      >
                        {jobLabel}
                      </span>
                    )}
                    <span className="truncate text-xs text-text-muted">
                      {new Date(run.created_at).toLocaleString()}
                    </span>
                    {run.completed_at && !isSkipped && (
                      <span className="shrink-0 text-[10px] text-text-dim">
                        ({Math.round((new Date(run.completed_at).getTime() - new Date(run.created_at).getTime()) / 1000)}s)
                      </span>
                    )}
                  </div>
                  <StatusBadge label={run.status} variant={statusVariant(run.status)} />
                </div>

                {!isExpanded && (
                  <CollapsedRunPreview
                    run={run}
                    isFailed={isFailed}
                    isSkipped={isSkipped}
                    indent={hasContent}
                  />
                )}
              </button>

              {isExpanded && (
                <div className="rounded-b-md border-x border-b border-surface-border/45 bg-surface/80 px-3 py-2.5">
                  {run.error && (
                    <div className="mb-2 whitespace-pre-wrap break-words rounded-md bg-danger/10 px-2 py-1.5 text-xs text-danger">
                      {run.error}
                    </div>
                  )}
                  {run.files_affected && run.files_affected.length > 0 && (
                    <div className="mb-2 flex items-start gap-1.5 rounded-md bg-purple/[0.04] px-2 py-1.5">
                      <FileText size={11} className="mt-0.5 shrink-0 text-purple" />
                      <FilePills files={run.files_affected} />
                    </div>
                  )}
                  {run.result && (
                    <div className="max-h-[200px] overflow-y-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-text">
                      {run.result}
                    </div>
                  )}
                  {(run.iterations > 0 || run.total_tokens > 0 || run.duration_ms != null) && (
                    <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-text-dim">
                      {run.duration_ms != null && (
                        <span className="inline-flex items-center gap-1">
                          <Clock size={10} /> {fmtDuration(run.duration_ms)}
                        </span>
                      )}
                      {run.total_tokens > 0 && (
                        <span className="inline-flex items-center gap-1">
                          <Zap size={10} /> {fmtTokens(run.total_tokens)} tokens
                        </span>
                      )}
                      {run.iterations > 0 && <span>{run.iterations} iter</span>}
                    </div>
                  )}
                  {run.tool_calls.length > 0 && (
                    <ToolCallsList toolCalls={run.tool_calls as any} />
                  )}
                  {run.correlation_id && (
                    <div className="mt-2">
                      <TraceActionButton
                        correlationId={run.correlation_id}
                        title={run.bot_name ? `${run.bot_name} dreaming run` : "Dreaming run"}
                        subtitle={run.status}
                      />
                    </div>
                  )}
                  {!run.result && !run.error && (
                    <div className="text-[11px] italic text-text-dim">No output recorded</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

function CollapsedRunPreview({
  run,
  isFailed,
  isSkipped,
  indent,
}: {
  run: RunWithExtras;
  isFailed: boolean;
  isSkipped: boolean;
  indent: boolean;
}) {
  return (
    <>
      {run.files_affected && run.files_affected.length > 0 && (
        <div className={cn("flex flex-wrap gap-1", indent && "ml-5")}>
          <FilePills files={run.files_affected.slice(0, 5)} />
          {run.files_affected.length > 5 && (
            <span className="text-[9px] text-text-dim">+{run.files_affected.length - 5}</span>
          )}
        </div>
      )}
      {isFailed && run.error && (
        <div className={cn("truncate text-[10px] text-danger", indent && "ml-5")}>
          {run.error}
        </div>
      )}
      {isSkipped && run.result && (
        <div className={cn("truncate text-[10px] text-purple", indent && "ml-5")}>
          {run.result}
        </div>
      )}
    </>
  );
}

function FilePills({ files }: { files: string[] }) {
  return (
    <div className="flex min-w-0 flex-wrap gap-1">
      {files.map((file) => (
        <span
          key={file}
          className="rounded bg-purple/[0.06] px-1.5 py-0.5 text-[9px] font-medium text-purple"
        >
          {file.replace(/^memory\//, "")}
        </span>
      ))}
    </div>
  );
}
