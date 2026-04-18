import { useEffect } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { PipelineRunPreRun } from "./PipelineRunPreRun";
import { PipelineRunLive } from "./PipelineRunLive";

export type PipelineRunModalMode = "prerun" | "live";

export interface PipelineRunModalProps {
  channelId: string;
  mode: PipelineRunModalMode;
  /** For prerun mode: the pipeline definition id. */
  pipelineId?: string;
  /** For live mode: the child task's id. */
  taskId?: string;
}

/**
 * The run-view modal shell. Mounted on two route variants:
 *   - /channels/:channelId/pipelines/:pipelineId → pre-run (description + params)
 *   - /channels/:channelId/runs/:taskId         → live or complete transcript
 *
 * Closing routes back to the channel URL.
 */
export function PipelineRunModal({ channelId, mode, pipelineId, taskId }: PipelineRunModalProps) {
  const navigate = useNavigate();

  const handleClose = () => {
    // Prefer history back if we came from the channel, otherwise push.
    // `window.history.length` is a good-enough heuristic — if the user
    // deep-linked into the modal we don't want `back()` to exit the app.
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate(`/channels/${channelId}`, { replace: true });
    }
  };

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={handleClose}
        className="fixed inset-0 bg-black/55 z-[10040]"
        aria-hidden="true"
      />
      {/* Modal card — centered on desktop, full-screen on mobile */}
      <div
        role="dialog"
        aria-modal="true"
        className="fixed z-[10041] overflow-hidden
                   inset-0 md:inset-auto md:top-1/2 md:left-1/2
                   md:-translate-x-1/2 md:-translate-y-1/2
                   md:w-[92vw] md:max-w-[920px] md:h-[85vh]
                   bg-surface-raised md:border md:border-surface-border
                   md:rounded-xl md:shadow-[0_16px_48px_rgba(0,0,0,0.35)]
                   flex flex-col"
      >
        {mode === "prerun" && pipelineId ? (
          <PipelineRunPreRun
            pipelineId={pipelineId}
            channelId={channelId}
            onClose={handleClose}
            onLaunched={(childTaskId) =>
              navigate(`/channels/${channelId}/runs/${childTaskId}`, { replace: true })
            }
          />
        ) : mode === "live" && taskId ? (
          <PipelineRunLive
            taskId={taskId}
            channelId={channelId}
            onClose={handleClose}
          />
        ) : null}
      </div>
    </>,
    document.body,
  );
}
