import { useMemo, useState } from "react";
import { Loader2, X, Workflow } from "lucide-react";
import { useTask, useRunTaskNow } from "@/src/api/hooks/useTasks";
import {
  PipelineParamForm,
  isFormValid,
  type PipelineParamDef,
} from "@/src/components/shared/PipelineParamForm";

export interface PipelineRunPreRunProps {
  pipelineId: string;
  channelId: string;
  onLaunched: (childTaskId: string) => void;
  onClose: () => void;
}

/**
 * Pre-run pane of the pipeline run-view modal. Shows description + param
 * form + Start button. On launch, navigates to the run URL for the
 * newly-created child task.
 */
export function PipelineRunPreRun({
  pipelineId,
  channelId,
  onLaunched,
  onClose,
}: PipelineRunPreRunProps) {
  const { data: pipeline, isLoading } = useTask(pipelineId);
  const [values, setValues] = useState<Record<string, any>>({});
  const [launchError, setLaunchError] = useState<string | null>(null);
  const runNow = useRunTaskNow();

  const schema: PipelineParamDef[] = useMemo(() => {
    const raw = (pipeline as any)?.execution_config?.params_schema;
    return Array.isArray(raw) ? raw : [];
  }, [pipeline]);

  const description: string | null = useMemo(() => {
    const d = (pipeline as any)?.execution_config?.description;
    return typeof d === "string" && d.trim() ? d.trim() : null;
  }, [pipeline]);

  const canLaunch = useMemo(() => isFormValid(schema, values), [schema, values]);
  const running = runNow.isPending;
  const title = pipeline?.title || pipelineId;

  const handleStart = () => {
    setLaunchError(null);
    runNow.mutate(
      {
        taskId: pipelineId,
        params: Object.keys(values).length > 0 ? values : undefined,
        channel_id: channelId,
      },
      {
        onSuccess: (task) => onLaunched(task.id),
        onError: (err) => {
          setLaunchError(
            err instanceof Error
              ? err.message
              : "Failed to launch pipeline",
          );
        },
      },
    );
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-surface-border shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <Workflow size={16} className="text-accent shrink-0" />
          <span className="text-sm font-semibold text-text truncate">{title}</span>
          <span className="text-[10px] uppercase tracking-wider text-text-dim px-1.5 py-0.5 rounded bg-surface-overlay/60 border border-surface-border/60 shrink-0">
            Pre-run
          </span>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="p-1 text-text-dim hover:text-text"
          disabled={running}
        >
          <X size={18} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {isLoading && !pipeline ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={16} className="animate-spin text-text-dim" />
          </div>
        ) : (
          <>
            {description ? (
              <p className="text-xs text-text-dim leading-relaxed mb-5 whitespace-pre-wrap">
                {description}
              </p>
            ) : (
              <p className="text-xs text-text-dim/70 italic mb-5">
                This pipeline has no description. Click Start to launch.
              </p>
            )}
            <PipelineParamForm
              schema={schema}
              values={values}
              onChange={setValues}
              disabled={running}
            />
          </>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 px-5 py-3 border-t border-surface-border shrink-0">
        <div className="text-[11px] text-red-400 min-w-0 truncate">
          {launchError}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onClose}
            disabled={running}
            className="px-3 py-1.5 text-xs rounded-md border border-surface-border
                       text-text-dim hover:text-text disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleStart}
            disabled={!canLaunch || running || isLoading}
            className="px-3 py-1.5 text-xs rounded-md bg-accent text-white font-semibold
                       hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed
                       inline-flex items-center gap-1.5"
          >
            {running ? <Loader2 size={12} className="animate-spin" /> : null}
            {running ? "Starting..." : "Start"}
          </button>
        </div>
      </div>
    </div>
  );
}
