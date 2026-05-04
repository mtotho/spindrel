import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function readProjectFile(path: string): string {
  return readFileSync(resolve(process.cwd(), path), "utf8");
}

test("channel chat submits follow-ups immediately and renders server queue state", () => {
  const useChannelChat = readProjectFile("app/(app)/channels/[channelId]/useChannelChat.ts");
  const channelPage = readProjectFile("app/(app)/channels/[channelId]/index.tsx");
  const messageInput = readProjectFile("src/components/chat/MessageInput.tsx");
  const messageArea = readProjectFile("src/components/chat/ChatMessageArea.tsx");
  const useChat = readProjectFile("src/api/hooks/useChat.ts");

  assert.doesNotMatch(useChannelChat, /queuedRequestRef/);
  assert.doesNotMatch(useChannelChat, /setIsQueued|setQueuedMessageText|isActiveRef/);
  assert.match(useChannelChat, /submitPrepared\(prepared\);/);
  assert.match(useChannelChat, /local_status:\s*"queued"/);
  assert.match(useChannelChat, /queuedLocalMessages\(messages\)/);
  assert.match(useChannelChat, /Math\.max\(result\.queued_message_count \?\? 0, localQueuedCount\)/);
  assert.match(useChannelChat, /meta\.client_local_id === prepared\.clientLocalId/);

  const channelEvents = readProjectFile("src/api/hooks/useChannelEvents.ts");
  assert.match(channelEvents, /const queuedMeta = optimisticMatches/);
  assert.match(channelEvents, /local_status:\s*"queued"/);

  assert.doesNotMatch(channelPage, /onCancelQueue:|onEditQueue:|onSendNow:/);
  assert.match(messageInput, /Responding - follow-up will be queued/);
  assert.match(messageInput, /\{onSendNow && \(/);

  assert.match(messageArea, /QueuedFollowupNotice/);
  assert.match(messageArea, /queuedFollowupRunCount/);
  assert.match(messageArea, /follow-ups queued together/);
  assert.match(messageArea, /after this turn/);

  const chatSessionShared = readProjectFile("src/components/chat/ChatSessionShared.ts");
  assert.match(chatSessionShared, /markSessionMessageQueued/);
  assert.match(chatSessionShared, /meta\.client_local_id === clientLocalId/);
  assert.match(readProjectFile("src/components/chat/ChatSessionFixed.tsx"), /markSessionMessageQueued\(sessionId, clientLocalId, result\)/);

  assert.match(useChat, /coalesced\?: boolean/);
  assert.match(useChat, /queued_message_count\?: number/);
});
