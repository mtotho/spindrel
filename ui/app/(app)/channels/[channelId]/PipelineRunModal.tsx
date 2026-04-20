import { useNavigate } from "react-router-dom";
import { ChatSessionModal } from "@/src/components/chat/ChatSessionModal";
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
 * Thin wrapper around ChatSessionModal — the portal shell lives there so
 * ChatSession and pipeline modals share identical chrome.
 */
export function PipelineRunModal({ channelId, mode, pipelineId, taskId }: PipelineRunModalProps) {
  const navigate = useNavigate();

  const handleClose = () => {
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate(`/channels/${channelId}`, { replace: true });
    }
  };

  return (
    <ChatSessionModal open title="Pipeline run" onClose={handleClose}>
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
    </ChatSessionModal>
  );
}
