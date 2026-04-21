import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { SessionChatView } from "@/src/components/chat/SessionChatView";

/**
 * Read-only viewer for a historical scratch-pad session. Mounted at
 * ``/channels/:channelId/scratch/:sessionId``. Reuses ``SessionChatView``
 * (the same transcript renderer used inside pipeline run modals) so the
 * look matches the main chat — just without a composer.
 */
export default function ScratchViewer() {
  const { channelId, sessionId } = useParams<{
    channelId: string;
    sessionId: string;
  }>();

  if (!channelId || !sessionId) {
    return (
      <div className="p-8 text-sm text-text-dim">
        Missing channelId or sessionId in URL.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-surface">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-surface-border bg-surface-raised">
        <Link
          to={`/channels/${channelId}`}
          className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
          aria-label="Back to channel"
        >
          <ArrowLeft size={16} />
        </Link>
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-text">Scratch session</span>
          <span className="text-[11px] text-text-dim">
            Read-only archive · session {sessionId.slice(0, 8)}…
          </span>
        </div>
      </div>

      <div className="flex-1 min-h-0 relative">
        <SessionChatView
          sessionId={sessionId}
          parentChannelId={channelId}
        />
      </div>
    </div>
  );
}
