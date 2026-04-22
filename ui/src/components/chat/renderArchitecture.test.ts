import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const CHAT_DIR = resolve(process.cwd(), "src/components/chat");

function readChatFile(name: string): string {
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
  const channelPage = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"),
    "utf8",
  );
  const chatSession = readChatFile("ChatSession.tsx");

  assert.match(channelPage, /ChatComposerShell/);
  assert.match(chatSession, /ChatComposerShell/);
});

test("chat rich-result wrappers explicitly separate renderer variant from chrome ownership", () => {
  const orderedTranscript = readChatFile("OrderedTranscript.tsx");
  const toolBadges = readChatFile("ToolBadges.tsx");
  const richToolResult = readChatFile("RichToolResult.tsx");
  const widgetCard = readChatFile("WidgetCard.tsx");

  assert.match(richToolResult, /RichRendererChromeMode/);
  assert.match(richToolResult, /chromeMode\?:\s*RichRendererChromeMode/);
  assert.match(richToolResult, /chromeMode = "standalone"/);

  assert.match(orderedTranscript, /rendererVariant="terminal-chat"/);
  assert.match(orderedTranscript, /chromeMode="embedded"/);
  assert.match(orderedTranscript, /rendererVariant="default-chat"/);

  assert.match(toolBadges, /rendererVariant=\{isTerminalMode \? "terminal-chat" : "default-chat"\}/);
  assert.match(toolBadges, /chromeMode="embedded"/);

  assert.match(orderedTranscript, /chatMode=\{chatMode\}/);
  assert.match(widgetCard, /chatMode\?:\s*"default"\s*\|\s*"terminal"/);
  assert.match(widgetCard, /hostSurface=\{isTerminalMode \? "plain" : "surface"\}/);
});

test("chat copy actions share one assistant-response bundle primitive for text and json", () => {
  const channelPage = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"),
    "utf8",
  );
  const chatSession = readChatFile("ChatSession.tsx");
  const sessionChatView = readChatFile("SessionChatView.tsx");
  const messageBubble = readChatFile("MessageBubble.tsx");
  const messageActions = readChatFile("MessageActions.tsx");

  assert.match(channelPage, /getTurnMessages/);
  assert.match(chatSession, /getTurnMessages/);
  assert.match(sessionChatView, /getTurnMessages/);
  assert.match(messageBubble, /fullTurnMessages\?:\s*Message\[\]/);
  assert.match(messageBubble, /fullTurnMessages=\{fullTurnMessages\}/);
  assert.match(messageActions, /Copy JSON/);
});
