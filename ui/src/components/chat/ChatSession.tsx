import type { ChatSessionProps } from "./ChatSessionTypes";
import { ChannelChatSession } from "./ChatSessionChannel";
import { FixedSessionChatSession } from "./ChatSessionFixed";
import { EphemeralChatSession } from "./ChatSessionEphemeral";
import { ThreadChatSession } from "./ChatSessionThread";

export type { ChatSessionProps, ChatSource, EphemeralContextPayload } from "./ChatSessionTypes";

/**
 * Chat controller — routes each chat source to its dedicated implementation.
 * The public props stay stable; source-specific behavior lives behind the
 * mode modules so channel/session/thread/ephemeral logic can evolve locally.
 */
export function ChatSession(props: ChatSessionProps) {
  if (props.source.kind === "channel") {
    return <ChannelChatSession {...props} source={props.source} />;
  }
  if (props.source.kind === "thread") {
    return <ThreadChatSession {...props} source={props.source} />;
  }
  if (props.source.kind === "session") {
    return <FixedSessionChatSession {...props} source={props.source} />;
  }
  return <EphemeralChatSession {...props} source={props.source} />;
}
