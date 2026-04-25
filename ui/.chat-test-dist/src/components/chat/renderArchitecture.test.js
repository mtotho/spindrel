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
test("chat modes centralize composer placement and rich result mode conventions", () => {
    const chatModes = readChatFile("chatModes.ts");
    const chatSession = readChatFile("ChatSession.tsx");
    const richToolResult = readChatFile("RichToolResult.tsx");
    assert.match(chatModes, /composerPlacement:\s*"viewport-overlay"/);
    assert.match(chatModes, /composerPlacement:\s*"transcript-flow"/);
    assert.match(chatSession, /isTranscriptFlowComposer/);
    assert.match(richToolResult, /resultViews\.resolve\(viewKey, renderMode\)/);
    assert.match(richToolResult, /SafeFallbackResult/);
    assert.match(richToolResult, /core\.search_results/);
    assert.doesNotMatch(richToolResult, /web_search\.results/);
    assert.match(richToolResult, /resultViews\.register\("core\.plan", \{ default: renderPlanView, terminal: renderPlanView \}\)/);
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
test("EditPinDrawer keeps its hooks above the open-state early return", () => {
    const editPinDrawer = readFileSync(resolve(process.cwd(), "app/(app)/widgets/EditPinDrawer.tsx"), "utf8");
    const schemaHooks = editPinDrawer.indexOf("const configSchemaProperties = useMemo(");
    const earlyReturn = editPinDrawer.indexOf("if (!isOpen) return null;");
    assert.notEqual(schemaHooks, -1);
    assert.notEqual(earlyReturn, -1);
    assert.ok(schemaHooks < earlyReturn);
});
test("channel settings form hydrates header strip shell from saved settings", () => {
    const channelSettings = readFileSync(resolve(process.cwd(), "app/(app)/channels/[channelId]/settings.tsx"), "utf8");
    assert.match(channelSettings, /header_backdrop_mode:\s*settings\.header_backdrop_mode\s*\?\?\s*"glass"/);
});
test("machine-control rich-result views are extracted into dedicated renderer files", () => {
    const richToolResult = readChatFile("RichToolResult.tsx");
    const machineStatusRenderer = readFileSync(resolve(CHAT_DIR, "renderers/machineControl/MachineTargetStatusRenderer.tsx"), "utf8");
    const machineAccessRenderer = readFileSync(resolve(CHAT_DIR, "renderers/machineControl/MachineAccessRequiredRenderer.tsx"), "utf8");
    const commandRenderer = readFileSync(resolve(CHAT_DIR, "renderers/machineControl/CommandResultRenderer.tsx"), "utf8");
    assert.match(richToolResult, /renderers\/machineControl\/MachineTargetStatusRenderer/);
    assert.match(richToolResult, /renderers\/machineControl\/MachineAccessRequiredRenderer/);
    assert.match(richToolResult, /renderers\/machineControl\/CommandResultRenderer/);
    assert.doesNotMatch(richToolResult, /function MachineTargetStatusRenderer/);
    assert.doesNotMatch(richToolResult, /function MachineAccessRequiredRenderer/);
    assert.doesNotMatch(richToolResult, /function CommandResultRenderer/);
    assert.match(machineStatusRenderer, /useGrantSessionMachineTargetLease/);
    assert.match(machineAccessRenderer, /admin_machines_href/);
    assert.match(commandRenderer, /coerceCommandResultPayload/);
});
test("chat copy actions share one assistant-response bundle primitive for text and json", () => {
    const channelPage = readFileSync(resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"), "utf8");
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
test("chat sends thread a stable client-local id through optimistic rows and requests", () => {
    const channelHook = readFileSync(resolve(process.cwd(), "app/(app)/channels/[channelId]/useChannelChat.ts"), "utf8");
    const channelEvents = readFileSync(resolve(process.cwd(), "src/api/hooks/useChannelEvents.ts"), "utf8");
    const chatMessageArea = readChatFile("ChatMessageArea.tsx");
    assert.match(channelHook, /client_local_id:\s*clientLocalId/);
    assert.match(channelHook, /local_status:\s*"sending"/);
    assert.match(channelHook, /local_status:\s*"queued"/);
    assert.match(channelEvents, /incomingClientLocalId/);
    assert.match(chatMessageArea, /meta\.client_local_id/);
});
