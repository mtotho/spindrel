import type { ReactNode } from "react";
import { StickyNote, X as CloseIcon } from "lucide-react";
import { ChatSession } from "@/src/components/chat/ChatSession";
import { buildScratchChatSource, type ChannelSessionPanel } from "@/src/lib/channelSessionSurfaces";

interface ChannelSessionSplitPanelProps {
  panel: ChannelSessionPanel;
  channelId: string;
  botId?: string | null;
  emptyState?: ReactNode;
  chatMode?: "default" | "terminal";
  onClose: (sessionId: string) => void;
}

export function ChannelSessionSplitPanel({
  panel,
  channelId,
  botId,
  emptyState,
  chatMode = "default",
  onClose,
}: ChannelSessionSplitPanelProps) {
  const source = buildScratchChatSource({
    channelId,
    botId,
    sessionId: panel.sessionId,
  });

  return (
    <div
      className="ml-1.5 flex min-h-0 flex-col overflow-hidden rounded-md border border-surface-border bg-surface"
      style={{
        flex: "0 0 min(420px, 34vw)",
        minWidth: 340,
        maxWidth: 520,
      }}
    >
      <div className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-surface-border px-3 text-text">
        <div className="flex min-w-0 items-center gap-2">
          <StickyNote size={14} className="text-text-dim" />
          <span className="truncate text-[12px] font-medium">Session split</span>
        </div>
        <button
          type="button"
          onClick={() => onClose(panel.sessionId)}
          className="flex h-7 w-7 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
          aria-label="Close session split"
        >
          <CloseIcon size={14} />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        <ChatSession
          source={source}
          shape="fullpage"
          open
          onClose={() => onClose(panel.sessionId)}
          title="Session"
          emptyState={emptyState}
          chatMode={chatMode}
        />
      </div>
    </div>
  );
}
