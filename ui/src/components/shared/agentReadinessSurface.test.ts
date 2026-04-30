import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function readUiFile(path: string): string {
  return readFileSync(resolve(process.cwd(), path), "utf8");
}

test("agent readiness hook calls the shared capability manifest with scoped query params", () => {
  const hook = readUiFile("src/api/hooks/useAgentCapabilities.ts");

  assert.match(hook, /"agent-capabilities"/);
  assert.match(hook, /\/api\/v1\/agent-capabilities\?/);
  assert.match(hook, /params\.set\("bot_id", botId\)/);
  assert.match(hook, /params\.set\("channel_id", channelId\)/);
  assert.match(hook, /params\.set\("session_id", sessionId\)/);
  assert.match(hook, /params\.set\("include_schemas", includeSchemas \? "true" : "false"\)/);
  assert.match(hook, /params\.set\("include_endpoints", includeEndpoints \? "true" : "false"\)/);
  assert.match(hook, /params\.set\("max_tools", String\(maxTools\)\)/);
  assert.match(hook, /enabled: enabled && Boolean\(botId \|\| channelId \|\| sessionId\)/);
});

test("readiness panel renders doctor status, capability counts, surfaces, and findings", () => {
  const panel = readUiFile("src/components/shared/AgentReadinessPanel.tsx");
  const hook = readUiFile("src/api/hooks/useAgentCapabilities.ts");

  assert.match(panel, /useAgentCapabilities/);
  assert.match(hook, /interface AgentCapabilityAction/);
  assert.match(hook, /proposed_actions\?: AgentCapabilityAction\[\]/);
  assert.match(panel, /StatusBadge label=\{label\}/);
  assert.match(panel, /SettingsStatGrid/);
  assert.match(panel, /API scopes/);
  assert.match(panel, /manifest\.tools\.working_set_count/);
  assert.match(panel, /manifest\.skills\.working_set_count/);
  assert.match(panel, /SurfaceSummary/);
  assert.match(panel, /WidgetAuthoringSummary/);
  assert.match(panel, /widgets\.readiness/);
  assert.match(panel, /HTML full check/);
  assert.match(panel, /agent-readiness-widget-authoring/);
  assert.match(panel, /data\.doctor\.findings/);
  assert.match(panel, /data\.doctor\.proposed_actions/);
  assert.match(panel, /Suggested repairs/);
  assert.match(panel, /ProposedActionRow/);
  assert.match(panel, /Ready to act with current API grants, tools, skills, and runtime context/);
});

test("readiness proposed actions use existing bot update and invalidate capability queries", () => {
  const panel = readUiFile("src/components/shared/AgentReadinessPanel.tsx");
  const botsHook = readUiFile("src/api/hooks/useBots.ts");

  assert.match(panel, /useUpdateBot\(botId \|\| undefined\)/);
  assert.match(panel, /updateBot\.mutateAsync\(action\.apply\.patch as Partial<BotConfig>\)/);
  assert.match(panel, /action\.apply\.type === "bot_patch"/);
  assert.match(panel, /navigate\(href\)/);
  assert.match(botsHook, /queryKey: \["agent-capabilities"\]/);
  assert.match(botsHook, /queryKey: \["admin-bots"\]/);
});

test("composer exposes readiness next to attach, skills, and tools", () => {
  const composer = readUiFile("src/components/chat/ComposerAddMenu.tsx");

  assert.match(composer, /type View = "root" \| "skills" \| "tools" \| "readiness"/);
  assert.match(composer, /ReadinessMenuRow/);
  assert.match(composer, /onClick=\{\(\) => setView\("readiness"\)\}/);
  assert.match(composer, /<AgentReadinessPanel/);
  assert.match(composer, /view === "readiness"/);
});

test("tools panel promotes manifest-recommended tools without replacing catalog search", () => {
  const toolsPanel = readUiFile("src/components/chat/ToolsInContextPanel.tsx");

  assert.match(toolsPanel, /useAgentCapabilities/);
  assert.match(toolsPanel, /capabilities\.tools\.recommended_core/);
  assert.match(toolsPanel, /Recommended now/);
  assert.match(toolsPanel, /!search\.trim\(\) && recommended\.length > 0/);
  assert.match(toolsPanel, /CatalogRow/);
});

test("settings surfaces show agent readiness in bot and channel configuration", () => {
  const botEditor = readUiFile("app/(app)/admin/bots/[botId]/index.tsx");
  const channelTools = readUiFile("app/(app)/channels/[channelId]/ToolsOverrideTab.tsx");

  assert.match(botEditor, /AgentReadinessPanel/);
  assert.match(botEditor, /readinessBotId=\{isNew \? undefined : draft\.id\}/);
  assert.match(channelTools, /AgentReadinessPanel/);
  assert.match(channelTools, /botId=\{botId\} channelId=\{channelId\}/);
});
