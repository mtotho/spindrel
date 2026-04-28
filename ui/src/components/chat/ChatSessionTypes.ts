import type { ReactNode } from "react";
import type { Message } from "@/src/types/api";

export interface EphemeralContextPayload {
  page_name?: string;
  url?: string;
  tags?: string[];
  payload?: Record<string, unknown>;
  tool_hints?: string[];
}

/** Discriminator picks which backend path the chat component talks to. */
export type ChatSource =
  | { kind: "channel"; channelId: string }
  | {
      kind: "session";
      sessionId: string;
      parentChannelId: string;
      botId?: string;
      externalDelivery?: "channel" | "none";
    }
  | {
      kind: "ephemeral";
      sessionStorageKey: string;
      parentChannelId?: string;
      defaultBotId?: string;
      context?: EphemeralContextPayload;
      scratchBoundChannelId?: string;
      pinnedSessionId?: string;
    }
  | {
      kind: "thread";
      threadSessionId: string | null;
      parentChannelId: string;
      parentMessageId: string;
      botId: string;
      parentMessage?: Message | null;
      onSessionSpawned?: (sessionId: string) => void;
    };

export interface ChatSessionProps {
  source: ChatSource;
  chatMode?: "default" | "terminal";
  shape: "modal" | "dock" | "fullpage";
  open: boolean;
  onClose: () => void;
  title?: string;
  emptyState?: ReactNode;
  initiallyExpanded?: boolean;
  dockCollapsedTitle?: string;
  dockCollapsedSubtitle?: string | null;
  onRestoreToCanvas?: () => void;
  dismissMode?: "collapse" | "close";
  onOpenSessions?: () => void;
  onOpenSessionSplit?: () => void;
  onToggleFocusLayout?: () => void;
}

export function getDockStorageKey(source: ChatSource): string {
  if (source.kind === "channel") {
    return `channel:${source.channelId}`;
  }
  if (source.kind === "thread") {
    return `thread:${source.parentChannelId}:${source.parentMessageId}`;
  }
  if (source.kind === "session") {
    return `session:${source.parentChannelId}:${source.sessionId}`;
  }
  return [
    "ephemeral",
    source.sessionStorageKey,
    source.parentChannelId ?? "none",
    source.scratchBoundChannelId ?? "none",
    source.pinnedSessionId ?? "none",
  ].join(":");
}
