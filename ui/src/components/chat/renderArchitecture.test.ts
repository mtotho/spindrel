import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const CHAT_DIR = resolve(process.cwd(), "src/components/chat");
const CHAT_SESSION_SOURCE_FILES = [
  "ChatSessionChannel.tsx",
  "ChatSessionFixed.tsx",
  "ChatSessionEphemeral.tsx",
  "ChatSessionThread.tsx",
];

function readChatFile(name: string): string {
  return readFileSync(resolve(CHAT_DIR, name), "utf8");
}

function readChatSessionSourceModes(): string {
  return CHAT_SESSION_SOURCE_FILES.map(readChatFile).join("\n");
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
  const chatSessionModes = readChatSessionSourceModes();

  assert.match(channelPage, /ChatComposerShell/);
  assert.match(chatSessionModes, /ChatComposerShell/);
});

test("chat modes centralize composer placement and rich result mode conventions", () => {
  const chatModes = readChatFile("chatModes.ts");
  const chatSessionModes = readChatSessionSourceModes();
  const richToolResult = readChatFile("RichToolResult.tsx");

  assert.match(chatModes, /composerPlacement:\s*"viewport-overlay"/);
  assert.match(chatModes, /composerPlacement:\s*"transcript-flow"/);
  assert.match(chatSessionModes, /isTranscriptFlowComposer/);
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

test("ChatSession stays a source router over dedicated source-mode modules", () => {
  const chatSession = readChatFile("ChatSession.tsx");

  assert.match(chatSession, /ChannelChatSession/);
  assert.match(chatSession, /FixedSessionChatSession/);
  assert.match(chatSession, /EphemeralChatSession/);
  assert.match(chatSession, /ThreadChatSession/);
  assert.match(chatSession, /props\.source\.kind === "channel"/);
  assert.match(chatSession, /props\.source\.kind === "thread"/);
  assert.match(chatSession, /props\.source\.kind === "session"/);
  assert.match(chatSession, /EphemeralChatSession/);
  assert.match(chatSession, /export type \{ ChatSessionProps, ChatSource, EphemeralContextPayload \}/);

  assert.doesNotMatch(chatSession, /useSubmitChat/);
  assert.doesNotMatch(chatSession, /useSlashCommandExecutor/);
  assert.doesNotMatch(chatSession, /MessageInput/);
  assert.doesNotMatch(chatSession, /ChatComposerShell/);
  assert.doesNotMatch(chatSession, /function ChannelChatSession/);
  assert.doesNotMatch(chatSession, /function FixedSessionChatSession/);
  assert.doesNotMatch(chatSession, /function EphemeralChatSession/);
  assert.doesNotMatch(chatSession, /function ThreadChatSession/);

  assert.match(readChatFile("ChatSessionChannel.tsx"), /export function ChannelChatSession/);
  assert.match(readChatFile("ChatSessionFixed.tsx"), /export function FixedSessionChatSession/);
  assert.match(readChatFile("ChatSessionEphemeral.tsx"), /export function EphemeralChatSession/);
  assert.match(readChatFile("ChatSessionThread.tsx"), /export function ThreadChatSession/);
});

test("EditPinDrawer keeps its hooks above the open-state early return", () => {
  const editPinDrawer = readFileSync(
    resolve(process.cwd(), "app/(app)/widgets/EditPinDrawer.tsx"),
    "utf8",
  );
  const schemaHooks = editPinDrawer.indexOf("const configSchemaProperties = useMemo(");
  const earlyReturn = editPinDrawer.indexOf("if (!isOpen) return null;");

  assert.notEqual(schemaHooks, -1);
  assert.notEqual(earlyReturn, -1);
  assert.ok(schemaHooks < earlyReturn);
});

test("channel settings form hydrates header strip shell from saved settings", () => {
  const channelSettings = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/settings.tsx"),
    "utf8",
  );

  assert.match(channelSettings, /header_backdrop_mode:\s*settings\.header_backdrop_mode\s*\?\?\s*"glass"/);
});

test("machine-control rich-result views are extracted into dedicated renderer files", () => {
  const richToolResult = readChatFile("RichToolResult.tsx");
  const machineStatusRenderer = readFileSync(
    resolve(CHAT_DIR, "renderers/machineControl/MachineTargetStatusRenderer.tsx"),
    "utf8",
  );
  const machineAccessRenderer = readFileSync(
    resolve(CHAT_DIR, "renderers/machineControl/MachineAccessRequiredRenderer.tsx"),
    "utf8",
  );
  const commandRenderer = readFileSync(
    resolve(CHAT_DIR, "renderers/machineControl/CommandResultRenderer.tsx"),
    "utf8",
  );

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
  const channelPage = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"),
    "utf8",
  );
  const chatSessionModes = readChatSessionSourceModes();
  const sessionChatView = readChatFile("SessionChatView.tsx");
  const messageBubble = readChatFile("MessageBubble.tsx");
  const messageActions = readChatFile("MessageActions.tsx");

  assert.match(channelPage, /getTurnMessages/);
  assert.match(chatSessionModes, /getTurnMessages/);
  assert.match(sessionChatView, /getTurnMessages/);
  assert.match(messageBubble, /fullTurnMessages\?:\s*Message\[\]/);
  assert.match(messageBubble, /fullTurnMessages=\{fullTurnMessages\}/);
  assert.match(messageActions, /Copy JSON/);
});

test("MessageInput delegates draft files and submit decision policy", () => {
  const messageInput = readChatFile("MessageInput.tsx");
  const draftFiles = readChatFile("useComposerDraftFiles.ts");
  const composerSubmit = readChatFile("composerSubmit.ts");
  const modelControl = readChatFile("ComposerModelControl.tsx");
  const planControl = readChatFile("ComposerPlanControl.tsx");
  const approvalModeControl = readChatFile("ComposerApprovalModeControl.tsx");

  assert.match(messageInput, /useComposerDraftFiles/);
  assert.match(messageInput, /resolveComposerSubmitIntent/);
  assert.match(messageInput, /ComposerModelControl/);
  assert.match(messageInput, /ComposerPlanControl/);
  assert.match(messageInput, /ComposerApprovalModeControl/);
  assert.doesNotMatch(messageInput, /useDraftsStore/);
  assert.doesNotMatch(messageInput, /type DraftFile/);
  assert.doesNotMatch(messageInput, /function fileToBase64/);
  assert.doesNotMatch(messageInput, /function draftFilesToPending/);
  assert.doesNotMatch(messageInput, /resolveSlashCommand/);
  assert.doesNotMatch(messageInput, /detectMissingSlashArgs/);
  assert.doesNotMatch(messageInput, /function HarnessModelPickerContent/);
  assert.doesNotMatch(messageInput, /LlmModelDropdownContent/);
  assert.doesNotMatch(messageInput, /getComposerPlanControlState/);
  assert.doesNotMatch(messageInput, /getHarnessApprovalModeControlState/);
  assert.doesNotMatch(messageInput, /createPortal/);
  assert.doesNotMatch(messageInput, /ListTodo/);
  assert.doesNotMatch(messageInput, /ChevronDown/);

  assert.match(draftFiles, /useDraftsStore/);
  assert.match(draftFiles, /function fileToBase64/);
  assert.match(draftFiles, /function draftFilesToPending/);
  assert.match(composerSubmit, /resolveSlashCommand/);
  assert.match(composerSubmit, /detectMissingSlashArgs/);
  assert.doesNotMatch(composerSubmit, /toast/);

  assert.match(modelControl, /LlmModelDropdownContent/);
  assert.match(modelControl, /function HarnessModelPickerContent/);
  assert.match(modelControl, /spindrel:open-model-picker/);
  assert.match(planControl, /getComposerPlanControlState/);
  assert.match(planControl, /createPortal/);
  assert.match(planControl, /ListTodo/);
  assert.match(planControl, /ChevronDown/);
  assert.match(approvalModeControl, /getHarnessApprovalModeControlState/);
});

test("chat sends thread a stable client-local id through optimistic rows and requests", () => {
  const channelHook = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/useChannelChat.ts"),
    "utf8",
  );
  const channelEvents = readFileSync(
    resolve(process.cwd(), "src/api/hooks/useChannelEvents.ts"),
    "utf8",
  );
  const chatMessageArea = readChatFile("ChatMessageArea.tsx");

  assert.match(channelHook, /client_local_id:\s*clientLocalId/);
  assert.match(channelHook, /local_status:\s*"sending"/);
  assert.match(channelHook, /local_status:\s*"queued"/);
  assert.match(channelEvents, /incomingClientLocalId/);
  assert.match(chatMessageArea, /meta\.client_local_id/);
});
