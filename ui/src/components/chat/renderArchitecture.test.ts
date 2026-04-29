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

  assert.equal(existsSync(resolve(CHAT_DIR, "TerminalToolTranscript.tsx")), true);
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

test("native plan replay hydrates out-of-line envelopes before rendering plan cards", () => {
  const richToolResult = readChatFile("RichToolResult.tsx");
  const planRenderer = readChatFile("renderers/PlanResultRenderer.tsx");
  const planPayload = readChatFile("renderers/planPayload.ts");
  const planQuestions = readChatFile("renderers/nativeApps/PlanQuestionsWidget.tsx");
  const terminalToolTranscript = readChatFile("TerminalToolTranscript.tsx");
  const sessionPlanCard = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/SessionPlanCard.tsx"),
    "utf8",
  );

  assert.match(richToolResult, /const PLAN_CONTENT_TYPE = "application\/vnd\.spindrel\.plan\+json"/);
  assert.match(richToolResult, /unwrapFetchedToolResultBody\(envelope, fetched\)/);
  assert.match(richToolResult, /shouldAutoFetchPlan/);
  assert.match(richToolResult, /chatMode=\{mode === "terminal" \? "terminal" : "default"\}/);
  assert.match(planRenderer, /parsePlanPayload\(body \?\? envelope\.body\)/);
  assert.match(planRenderer, /chatMode=\{chatMode\}/);
  assert.match(planPayload, /parsed\._envelope/);
  assert.match(planPayload, /parsed\.plan/);
  assert.match(terminalToolTranscript, /rendersInlineRichTerminalResult/);
  assert.match(terminalToolTranscript, /application\/vnd\.spindrel\.plan\+json/);
  assert.match(terminalToolTranscript, /rendererVariant="terminal-chat"/);
  assert.match(sessionPlanCard, /data-plan-card-mode=\{chatMode\}/);
  assert.match(sessionPlanCard, /TERMINAL_FONT_STACK/);
  assert.doesNotMatch(sessionPlanCard, /useThemeTokens/);

  assert.match(planQuestions, /\/sessions\/\$\{sessionId\}\/plan\/question-answers/);
  assert.match(planQuestions, /\/sessions\/\$\{sessionId\}\/messages/);
  assert.match(planQuestions, /source:\s*"plan_questions"/);
  assert.match(planQuestions, /run_agent:\s*true/);
});

test("chat rich-result wrappers explicitly separate renderer variant from chrome ownership", () => {
  const orderedTranscript = readChatFile("OrderedTranscript.tsx");
  const toolBadges = readChatFile("ToolBadges.tsx");
  const toolTranscriptRows = readChatFile("ToolTranscriptRows.tsx");
  const terminalToolTranscript = readChatFile("TerminalToolTranscript.tsx");
  const richToolResult = readChatFile("RichToolResult.tsx");
  const widgetCard = readChatFile("WidgetCard.tsx");

  assert.match(richToolResult, /RichRendererChromeMode/);
  assert.match(richToolResult, /chromeMode\?:\s*RichRendererChromeMode/);
  assert.match(richToolResult, /chromeMode = "standalone"/);

  assert.match(orderedTranscript, /rendererVariant="terminal-chat"/);
  assert.match(orderedTranscript, /chromeMode="embedded"/);
  assert.match(orderedTranscript, /rendererVariant="default-chat"/);

  assert.match(toolTranscriptRows, /rendererVariant="default-chat"/);
  assert.match(terminalToolTranscript, /rendererVariant="terminal-chat"/);
  assert.match(toolTranscriptRows, /chromeMode="embedded"/);
  assert.match(terminalToolTranscript, /chromeMode="embedded"/);

  assert.match(orderedTranscript, /chatMode=\{chatMode\}/);
  assert.match(widgetCard, /chatMode\?:\s*"default"\s*\|\s*"terminal"/);
  assert.match(widgetCard, /hostSurface=\{isTerminalMode \? "plain" : "surface"\}/);
});

test("terminal tool transcript uses CLI-style sequential rows instead of compact tape", () => {
  const toolBadges = readChatFile("ToolBadges.tsx");
  const toolTranscriptRows = readChatFile("ToolTranscriptRows.tsx");
  const terminalToolTranscript = readChatFile("TerminalToolTranscript.tsx");
  const harnessApprovalPreview = readChatFile("HarnessApprovalPreview.tsx");
  const codePreviewRenderer = readChatFile("CodePreviewRenderer.tsx");
  const toolTraceStrip = readChatFile("ToolTraceStrip.tsx");

  assert.match(toolBadges, /const isTerminalMode = chatMode === "terminal"/);
  assert.match(toolTranscriptRows, /<TerminalToolTranscript/);
  assert.match(terminalToolTranscript, /data-testid="terminal-tool-transcript"/);
  assert.match(terminalToolTranscript, /data-testid="tool-transcript-row"/);
  assert.match(terminalToolTranscript, /data-testid="terminal-tool-label"/);
  assert.match(terminalToolTranscript, /data-testid="terminal-tool-meta"/);
  assert.match(terminalToolTranscript, /data-testid="terminal-tool-output"/);
  assert.match(codePreviewRenderer, /data-testid=\{testId\}/);
  assert.match(terminalToolTranscript, /data-testid="terminal-diff-output"/);
  assert.match(terminalToolTranscript, /DiffRenderer/);
  assert.match(terminalToolTranscript, /hasUsefulArgs/);
  assert.doesNotMatch(terminalToolTranscript, /entry\.approval \? "\?" : ">"/);
  assert.match(harnessApprovalPreview, /DiffRenderer/);
  assert.match(harnessApprovalPreview, /CodePreviewRenderer/);
  assert.doesNotMatch(toolBadges, /function TerminalToolTranscript/);
  assert.doesNotMatch(toolBadges, /function HarnessToolPreview/);
  assert.doesNotMatch(toolBadges, /parseTerminalDiffRows/);
  assert.match(terminalToolTranscript, /looksLikeCodePreview/);
  assert.match(terminalToolTranscript, /gridTemplateColumns:\s*"14px minmax\(0, 1fr\)"/);
  assert.match(codePreviewRenderer, /gridTemplateColumns:\s*"4ch minmax\(0, 1fr\)"/);
  assert.match(readChatFile("renderers/DiffRenderer.tsx"), /rgba\(34, 197, 94, 0\.18\)/);
  assert.match(toolBadges, /const stripMode = !isTerminalMode && !hasApproval/);
  assert.match(toolTranscriptRows, /if \(!hasApproval && !groupExpanded && entries\.length >= TRACE_STRIP_THRESHOLD\)/);
  assert.match(toolTraceStrip, /data-testid="tool-trace-strip"/);
});

test("style slash command updates live channel cache instead of refresh-only invalidation", () => {
  const useChannelChat = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/useChannelChat.ts"),
    "utf8",
  );
  const chatSessionSources = readChatSessionSourceModes();
  const styleSideEffects = readChatFile("slashStyleSideEffects.ts");

  assert.match(styleSideEffects, /queryClient\.setQueryData<any>\(\["channels", channelId\]/);
  assert.match(styleSideEffects, /delete config\.chat_mode/);
  assert.match(useChannelChat, /applyChatStyleSideEffect\(queryClient, channelId, result\)/);
  assert.match(chatSessionSources, /applyChatStyleSideEffect\(qc, parentChannelId, result\)/);
  assert.doesNotMatch(chatSessionSources, /\["channel", parentChannelId\]/);
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

test("harness channel settings keep the channel prompt editor visible", () => {
  const settingsSections = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/ChannelSettingsSections.tsx"),
    "utf8",
  );
  const harnessBranchStart = settingsSections.indexOf("if (harnessRuntime) {");
  const harnessRoutingSection = settingsSections.indexOf("<MessageRoutingSection", harnessBranchStart);

  assert.notEqual(harnessBranchStart, -1);
  assert.notEqual(harnessRoutingSection, -1);
  assert.match(
    settingsSections.slice(harnessBranchStart, harnessRoutingSection),
    /<ChannelPromptSection\s+form=\{form\}/,
  );
});

test("mobile channel header does not make the whole title open context chrome", () => {
  const channelHeader = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/ChannelHeader.tsx"),
    "utf8",
  );

  assert.match(channelHeader, /import \{ useIsMobile \} from "@\/src\/hooks\/useIsMobile";/);
  assert.match(channelHeader, /isMobile: routeIsMobile/);
  assert.match(channelHeader, /const detectedMobile = useIsMobile\(\);/);
  assert.match(channelHeader, /const isMobile = routeIsMobile \|\| detectedMobile;/);
  assert.match(channelHeader, /const titleOpensContext = !isMobile && !isSystemChannel && !!bot && !bot\.harness_runtime && !!onContextBudgetClick;/);
  assert.match(channelHeader, /data-testid="channel-header-title-region"/);
  assert.match(channelHeader, /onClick=\{titleOpensContext \? onContextBudgetClick : undefined\}/);
  assert.match(channelHeader, /isMobile \? \(/);
  assert.match(channelHeader, /className="header-bot-label"/);
  assert.doesNotMatch(channelHeader, /compact && !contextNeedsAttention\) return null;/);
  assert.match(channelHeader, /data-testid=\{compact \? "harness-context-chip-mobile" : "harness-context-chip"\}/);
  assert.match(channelHeader, /data-testid="channel-header-mobile-overflow-menu"/);
  assert.match(channelHeader, /max-h-\[calc\(100dvh-72px\)\] overflow-auto rounded-md/);
});

test("harness context pressure avoids soft alert chrome", () => {
  const channelPage = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"),
    "utf8",
  );

  assert.match(channelPage, /const harnessAutoCompactionLane = autoCompactPressure === "hard"/);
  assert.match(channelPage, /Native context is low/);
  assert.doesNotMatch(channelPage, /Native context is getting full/);
  assert.doesNotMatch(channelPage, /border-warning\/25 bg-warning\/8/);
});

test("session resume cards do not show normal bot model labels for harness sessions", () => {
  const resumeCardHook = readChatFile("useSessionResumeCard.tsx");
  const approvalsHook = readFileSync(
    resolve(process.cwd(), "src/api/hooks/useApprovals.ts"),
    "utf8",
  );
  const channelPage = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"),
    "utf8",
  );
  const chatSessionSources = readChatSessionSourceModes();

  assert.match(resumeCardHook, /useSessionHarnessStatus\(sessionId, isHarnessBot\)/);
  assert.match(resumeCardHook, /const isHarnessBot = !!bot\?\.harness_runtime;/);
  assert.match(resumeCardHook, /const seededBotModel = isHarnessBot \? null : seed\?\.botModel;/);
  assert.match(resumeCardHook, /const resolvedBotModel = isHarnessBot\s*\?\s*\(harnessStatus\?\.model \?\? null\)\s*:\s*\(bot\?\.model \?\? null\);/);
  assert.match(resumeCardHook, /botModel: seededBotModel \?\? resolvedBotModel/);
  assert.match(approvalsHook, /enabled = true/);
  assert.match(approvalsHook, /enabled: enabled && !!sessionId/);
  assert.match(channelPage, /botModel:\s*bot\?\.harness_runtime \? null : bot\?\.model/);
  assert.match(chatSessionSources, /botModel:\s*bot\?\.harness_runtime \? null : bot\?\.model/);
  assert.match(chatSessionSources, /botModel:\s*sessionBot\?\.harness_runtime \? null : sessionBot\?\.model/);
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
  assert.match(messageInput, /shouldShowComposerPlanControl/);
  assert.doesNotMatch(messageInput, /!isHarness && canTogglePlanMode/);
  assert.doesNotMatch(messageInput, /useDraftsStore/);
  assert.doesNotMatch(messageInput, /type DraftFile/);
  assert.doesNotMatch(messageInput, /function fileToBase64/);
  assert.doesNotMatch(messageInput, /uploadChannelWorkspaceFile/);
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
  assert.match(draftFiles, /uploadChannelWorkspaceFile/);
  assert.doesNotMatch(draftFiles, /setDraftFiles/);
  assert.match(composerSubmit, /resolveSlashCommand/);
  assert.match(composerSubmit, /detectMissingSlashArgs/);
  assert.doesNotMatch(composerSubmit, /toast/);

  assert.match(modelControl, /LlmModelDropdownContent/);
  assert.match(modelControl, /function HarnessModelPickerContent/);
  assert.match(modelControl, /spindrel:open-model-picker/);
  assert.match(planControl, /getComposerPlanControlState/);
  assert.match(planControl, /data-testid="composer-plan-mode-control"/);
  assert.match(planControl, /createPortal/);
  assert.match(planControl, /ListTodo/);
  assert.match(planControl, /ChevronDown/);
  assert.match(approvalModeControl, /getHarnessApprovalModeControlState/);
});

test("Tiptap slash picker re-runs when the server command catalog hydrates", () => {
  const tiptapInput = readChatFile("TiptapChatInput.tsx");

  assert.match(tiptapInput, /const slashCatalog = useSlashCommandList\(currentBotId\);/);
  assert.match(tiptapInput, /detectSlashCommand\(markdown\);/);
  assert.match(tiptapInput, /\}, \[editor, detectSlashCommand\]\);/);
});

test("session composers use the parent channel for tool discovery menus", () => {
  const messageInput = readChatFile("MessageInput.tsx");
  const fixedSession = readChatFile("ChatSessionFixed.tsx");
  const ephemeralSession = readChatFile("ChatSessionEphemeral.tsx");

  assert.match(messageInput, /toolContextChannelId\?:\s*string/);
  assert.match(messageInput, /const toolChannelId = toolContextChannelId \?\? channelId;/);
  assert.match(messageInput, /<ComposerAddMenu\s+channelId=\{toolChannelId\}/);
  assert.match(fixedSession, /channelId=\{sessionId\}\s+toolContextChannelId=\{parentChannelId\}/);
  assert.match(ephemeralSession, /toolContextChannelId=\{scratchBoundChannelId \?\? parentChannelId\}/);
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

test("mobile chat transcript uses full-width content instead of avatar gutter", () => {
  const messageBubble = readChatFile("MessageBubble.tsx");
  const streamingIndicator = readChatFile("StreamingIndicator.tsx");
  const chatMessageArea = readChatFile("ChatMessageArea.tsx");

  assert.match(messageBubble, /const detectedMobile = useIsMobile\(\);/);
  assert.match(messageBubble, /const effectiveMobile = isMobile \|\| detectedMobile;/);
  assert.match(messageBubble, /const narrow = effectiveMobile \|\| compactLayout;/);
  assert.match(streamingIndicator, /const isMobile = useIsMobile\(\);/);
  assert.match(streamingIndicator, /!\s*isTerminalMode && !isMobile/);
  assert.match(chatMessageArea, /const contentHorizontalPadding = contentHorizontalPaddingOverride \?\? \(isMobile \? 4 : 16\);/);
  assert.doesNotMatch(chatMessageArea, /className="w-full mx-auto px-4"/);
});

test("harness route headers use URL session id while pane chrome hydrates", () => {
  const channelRoute = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"),
    "utf8",
  );

  assert.match(channelRoute, /const headerHarnessSessionId = channelHeaderChromeMode !== "canvas"/);
  assert.match(channelRoute, /headerPaneSessionId \?\? routeSessionId \?\? null/);
  assert.match(channelRoute, /bot\?\.harness_runtime \? headerHarnessSessionId : null/);
  assert.match(channelRoute, /sessionId=\{headerHarnessSessionId\}/);
});

test("channel route delegates session pane orchestration to its local controller", () => {
  const channelRoute = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"),
    "utf8",
  );
  const paneController = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/useChannelSessionPaneController.ts"),
    "utf8",
  );

  assert.match(channelRoute, /useChannelRouteSessionSurface/);
  assert.match(channelRoute, /useChannelSessionOverlayController/);
  assert.match(channelRoute, /useChannelSessionPaneController/);
  assert.doesNotMatch(channelRoute, /const focusPane = useCallback/);
  assert.doesNotMatch(channelRoute, /const minimizePane = useCallback/);
  assert.doesNotMatch(channelRoute, /onMinimizePane/);
  assert.doesNotMatch(channelRoute, /const replacePaneWithPendingSplit = useCallback/);
  assert.doesNotMatch(channelRoute, /const activateChannelSessionSurface = useCallback/);
  assert.doesNotMatch(channelRoute, /usePromoteScratchSession/);
  assert.match(paneController, /const focusPane = useCallback/);
  assert.match(paneController, /const unsplitPane = useCallback/);
  assert.match(paneController, /const replacePaneWithPendingSplit = useCallback/);
  assert.match(paneController, /const activateChannelSessionSurface = useCallback/);
  assert.match(paneController, /usePromoteScratchSession/);
});

test("channel route renders desktop session tabs through dedicated components and pure model", () => {
  const channelRoute = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/index.tsx"),
    "utf8",
  );
  const topTabsController = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/useChannelTopTabsController.ts"),
    "utf8",
  );
  const sessionTabs = readFileSync(
    resolve(process.cwd(), "app/(app)/channels/[channelId]/ChannelSessionTabs.tsx"),
    "utf8",
  );
  const sessionSurfaces = readFileSync(
    resolve(process.cwd(), "src/lib/channelSessionSurfaces.ts"),
    "utf8",
  );

  assert.match(channelRoute, /useChannelTopTabsController/);
  assert.match(channelRoute, /<ChannelSessionTabStrip/);
  assert.match(channelRoute, /tabs=\{topTabs\}/);
  assert.match(channelRoute, /<ChannelSessionInlinePicker/);
  assert.match(channelRoute, /pendingSessionTabKey/);
  assert.match(channelRoute, /openSessionTabSurfaceKeys/);
  assert.match(channelRoute, /handleFocusOpenSessionTabSurface/);
  assert.doesNotMatch(channelRoute, /const fileDirtyRef/);
  assert.doesNotMatch(channelRoute, /readChannelFileIntent/);
  assert.doesNotMatch(channelRoute, /CHANNEL_FILE_LINK_OPEN_EVENT/);
  assert.doesNotMatch(channelRoute, /moveTabKeyToFront/);
  assert.doesNotMatch(channelRoute, /selectFileTabNow/);
  assert.doesNotMatch(channelRoute, /fileTabKey/);
  assert.doesNotMatch(channelRoute, /const handleRenameSessionTab = useCallback/);
  assert.doesNotMatch(channelRoute, /snapshotChannelSessionTabLayout/);
  assert.match(topTabsController, /buildChannelSessionTabItems/);
  assert.match(topTabsController, /hiddenSessionTabKeys/);
  assert.match(topTabsController, /fileTabPaths/);
  assert.match(topTabsController, /selectFileTabNow/);
  assert.match(topTabsController, /fileTabKey/);
  assert.match(topTabsController, /sessionTabLayouts/);
  assert.match(topTabsController, /readChannelFileIntent/);
  assert.match(topTabsController, /CHANNEL_FILE_LINK_OPEN_EVENT/);
  assert.match(topTabsController, /if \(currentSerialized === nextSerialized\) return;/);
  assert.match(sessionTabs, /data-testid="channel-session-tab-strip"/);
  assert.match(sessionTabs, /data-testid="channel-session-tab-overflow-button"/);
  assert.match(sessionTabs, /data-testid="channel-session-tab-overflow-menu"/);
  assert.doesNotMatch(sessionTabs, /overflow-x-auto/);
  assert.match(sessionTabs, /data-testid="channel-session-split-tab"/);
  assert.match(sessionTabs, /data-testid="channel-session-tab-menu"/);
  assert.match(sessionTabs, /Focus open pane/);
  assert.match(sessionTabs, /Already open/);
  assert.match(sessionTabs, /Rename session/);
  assert.match(sessionTabs, /data-testid="channel-session-tab-rename-input"/);
  assert.match(sessionTabs, /Unsplit to/);
  assert.match(sessionTabs, /ChannelFileTabItem/);
  assert.match(sessionTabs, /ChannelTopTabItem/);
  assert.match(sessionTabs, /FileText/);
  assert.match(sessionTabs, /Already split/);
  assert.match(sessionTabs, /<DragOverlay/);
  assert.match(sessionTabs, /activationConstraint: \{ distance: 2 \}/);
  assert.match(sessionTabs, /data-testid="channel-session-inline-picker"/);
  assert.match(sessionSurfaces, /export function buildChannelSessionTabItems/);
  assert.match(sessionSurfaces, /export function snapshotChannelSessionTabLayout/);
});
