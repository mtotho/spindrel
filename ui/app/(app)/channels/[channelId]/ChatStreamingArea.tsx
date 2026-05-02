import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { useChatStore } from "@/src/stores/chat";
import { ChatMessageArea, type ChatMessageAreaProps } from "@/src/components/chat/ChatMessageArea";
import { ChatComposerShell } from "@/src/components/chat/ChatComposerShell";
import { MessageInput } from "@/src/components/chat/MessageInput";
import { ErrorBanner, ProjectChannelEmptyHint, SecretWarningBanner } from "./ChatBanners";
import { useChannel } from "@/src/api/hooks/useChannels";

type MessageInputComponentProps = ComponentProps<typeof MessageInput>;
type MessageAreaBaseProps = Omit<
  ChatMessageAreaProps,
  "chatState" | "sessionResumeSlot" | "bottomSlot" | "scrollPaddingTop" | "scrollPaddingBottom"
>;

export interface ChatStreamingAreaProps {
  channelId: string;
  chatMode: "default" | "terminal";
  isMobile: boolean;
  /** Built by the parent — already excludes streaming-bound fields. */
  messageInputProps: MessageInputComponentProps;
  /** Built by the parent — `chatState` is added inside this component. */
  messageAreaPropsBase: MessageAreaBaseProps;
  pendingHarnessQuestionLane: ReactNode;
  harnessAutoCompactionLane: ReactNode;
  primarySessionResumeSlot: ReactNode;
  onRetry: () => void;
}

/**
 * Owns the channel's chatState subscription so the parent (`ChatScreen`)
 * doesn't re-render on every text-delta. The parent stays at ~turn-boundary
 * cadence; this subtree absorbs the ~50×/sec churn and forwards a stable
 * `chatState` reference into the memoized children.
 */
export function ChatStreamingArea({
  channelId,
  chatMode,
  isMobile,
  messageInputProps,
  messageAreaPropsBase,
  pendingHarnessQuestionLane,
  harnessAutoCompactionLane,
  primarySessionResumeSlot,
  onRetry,
}: ChatStreamingAreaProps) {
  const chatState = useChatStore((s) => s.getChannel(channelId));
  const { data: channelData } = useChannel(channelId);
  const projectSummary = channelData?.project ?? null;
  // Show the discoverability hint only when the channel has no user messages
  // yet AND is attached to a Project. Auto-hides as soon as the user types.
  const hasAnyUserMessage = chatState.messages?.some((m) => m.role === "user") ?? false;
  const showProjectEmptyHint = !!projectSummary && !hasAnyUserMessage;

  const inputOverlayRef = useRef<HTMLDivElement>(null);
  const [inputOverlayHeight, setInputOverlayHeight] = useState(96);
  useEffect(() => {
    if (!inputOverlayRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height;
      if (h) setInputOverlayHeight(Math.ceil(h));
    });
    ro.observe(inputOverlayRef.current);
    return () => ro.disconnect();
  }, []);

  const handleDismissError = () => {
    useChatStore.getState().setError(channelId, "");
  };
  const handleDismissSecretWarning = () => {
    useChatStore.setState((s) => ({
      channels: {
        ...s.channels,
        [channelId]: { ...s.channels[channelId]!, secretWarning: null },
      },
    }));
  };

  const banners = (
    <>
      {chatState.error && (
        <ErrorBanner
          error={chatState.error}
          onDismiss={handleDismissError}
          onRetry={onRetry}
        />
      )}
      {chatState.secretWarning && (
        <SecretWarningBanner
          patterns={chatState.secretWarning.patterns}
          onDismiss={handleDismissSecretWarning}
        />
      )}
      {projectSummary && (
        <ProjectChannelEmptyHint
          projectName={projectSummary.name || "This Project"}
          visible={showProjectEmptyHint}
        />
      )}
    </>
  );

  const terminalBottomSlot = chatMode === "terminal" ? (
    <>
      {banners}
      {pendingHarnessQuestionLane}
      {harnessAutoCompactionLane}
      <ChatComposerShell chatMode={chatMode}>
        <MessageInput {...messageInputProps} />
      </ChatComposerShell>
    </>
  ) : null;

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", position: "relative" }}>
      <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
        <ChatMessageArea
          {...messageAreaPropsBase}
          chatState={chatState}
          sessionResumeSlot={primarySessionResumeSlot}
          bottomSlot={terminalBottomSlot}
          scrollPaddingTop={0}
          scrollPaddingBottom={chatMode === "terminal" ? 20 : inputOverlayHeight + (isMobile ? 32 : 48)}
        />
      </div>
      {chatMode !== "terminal" && (
        <div ref={inputOverlayRef} style={{ position: "absolute", bottom: 0, left: 0, right: 0, zIndex: 4 }}>
          {banners}
          {pendingHarnessQuestionLane}
          {harnessAutoCompactionLane}
          <ChatComposerShell chatMode={chatMode}>
            <MessageInput {...messageInputProps} />
          </ChatComposerShell>
        </div>
      )}
    </div>
  );
}
