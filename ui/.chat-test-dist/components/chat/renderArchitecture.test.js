import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
const CHAT_DIR = resolve(process.cwd(), "src/components/chat");
function readChatFile(name) {
    return readFileSync(resolve(CHAT_DIR, name), "utf8");
}
test("assistant turn rows use one canonical renderer path across streaming and persisted views", () => {
    const messageBubble = readChatFile("MessageBubble.tsx");
    const streamingIndicator = readChatFile("StreamingIndicator.tsx");
    assert.match(messageBubble, /buildAssistantTurnBodyItems/);
    assert.doesNotMatch(messageBubble, /buildPersistedRenderItems/);
    assert.doesNotMatch(messageBubble, /<ToolBadges/);
    assert.match(messageBubble, /<OrderedTranscript/);
    assert.match(messageBubble, /chatMode=\{chatMode\}/);
    assert.match(streamingIndicator, /buildAssistantTurnBodyItems/);
    assert.doesNotMatch(streamingIndicator, /buildOrderedTurnBodyItemsFromLive/);
    assert.match(streamingIndicator, /<OrderedTranscript/);
    assert.match(streamingIndicator, /chatMode=\{chatMode\}/);
    assert.equal(existsSync(resolve(CHAT_DIR, "TerminalToolTranscript.tsx")), false);
});
test("default-mode composer width is centralized through ChatComposerShell", () => {
    const channelPage = readFileSync(resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"), "utf8");
    const chatSession = readChatFile("ChatSession.tsx");
    assert.match(channelPage, /ChatComposerShell/);
    assert.match(chatSession, /ChatComposerShell/);
});
