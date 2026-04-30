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
  assert.match(hook, /interface AgentIntegrationReadiness/);
  assert.match(hook, /interface AgentStatusSnapshot/);
  assert.match(hook, /interface AgentActivityLogSummary/);
  assert.match(hook, /interface ExecutionReceiptWrite/);
  assert.match(hook, /interface AgentRepairPreflight/);
  assert.match(hook, /interface AgentRepairRequest/);
  assert.match(hook, /interface AgentSkillRecommendation/);
  assert.match(hook, /interface AgentSkillCreationCandidate/);
  assert.match(hook, /createExecutionReceipt/);
  assert.match(hook, /preflightAgentRepair/);
  assert.match(hook, /requestAgentRepair/);
  assert.match(hook, /applyAgentReadinessRepair/);
  assert.match(hook, /updateBotConfig/);
  assert.match(hook, /fetchAgentCapabilities/);
  assert.match(hook, /\/api\/v1\/execution-receipts/);
  assert.match(hook, /\/api\/v1\/agent-capabilities\/actions\/preflight/);
  assert.match(hook, /\/api\/v1\/agent-capabilities\/actions\/request/);
  assert.match(hook, /proposed_actions\?: AgentCapabilityAction\[\]/);
  assert.match(hook, /recent_receipts\?: ExecutionReceipt\[\]/);
  assert.match(hook, /pending_repair_requests\?: ExecutionReceipt\[\]/);
  assert.match(hook, /recommended_now\?: AgentSkillRecommendation\[\]/);
  assert.match(hook, /creation_candidates\?: AgentSkillCreationCandidate\[\]/);
  assert.match(hook, /integrations\?: AgentIntegrationReadiness/);
  assert.match(hook, /agent_status\?: AgentStatusSnapshot/);
  assert.match(hook, /activity_log\?: AgentActivityLogSummary/);
  assert.match(panel, /StatusBadge label=\{label\}/);
  assert.match(panel, /SettingsStatGrid/);
  assert.match(panel, /API scopes/);
  assert.match(panel, /manifest\.tools\.working_set_count/);
  assert.match(panel, /manifest\.skills\.working_set_count/);
  assert.match(panel, /SurfaceSummary/);
  assert.match(panel, /WidgetAuthoringSummary/);
  assert.match(panel, /IntegrationReadinessSummary/);
  assert.match(panel, /AgentStatusSummary/);
  assert.match(panel, /ActivityLogSummary/);
  assert.match(panel, /SkillOpportunitySummary/);
  assert.match(panel, /agent-readiness-skill-opportunities/);
  assert.match(panel, /Recommended skills now/);
  assert.match(panel, /Missing skill coverage/);
  assert.match(panel, /recommendation\.first_action/);
  assert.match(panel, /candidate\.suggested_skill_id/);
  assert.match(panel, /widgets\.readiness/);
  assert.match(panel, /agent-readiness-integrations/);
  assert.match(panel, /Integration readiness/);
  assert.match(panel, /agent-readiness-agent-status/);
  assert.match(panel, /Agent status/);
  assert.match(panel, /agent-readiness-activity-log/);
  assert.match(panel, /Recent agent activity/);
  assert.match(panel, /HTML full check/);
  assert.match(panel, /agent-readiness-widget-authoring/);
  assert.match(panel, /data\.doctor\.findings/);
  assert.match(panel, /data\.doctor\.proposed_actions/);
  assert.match(panel, /Suggested repairs/);
  assert.match(panel, /ProposedActionRow/);
  assert.match(panel, /applyAgentReadinessRepair/);
  assert.match(hook, /finding_resolved/);
  assert.match(hook, /remaining_findings/);
  assert.match(hook, /preflight/);
  assert.match(hook, /Verified resolved/);
  assert.match(hook, /Applied, still needs review/);
  assert.match(panel, /agent_readiness/);
  assert.match(hook, /execution-receipts/);
  assert.match(panel, /LastRepairSummary/);
  assert.match(panel, /agent-readiness-last-repair/);
  assert.match(panel, /Last repair/);
  assert.match(panel, /PendingRepairRequests/);
  assert.match(panel, /agent-readiness-pending-requests/);
  assert.match(panel, /Pending repair request/);
  assert.match(panel, /manifest\.doctor\.pending_repair_requests/);
  assert.match(panel, /candidate\.id === actionId/);
  assert.match(panel, /<QuietPill label="stale"/);
  assert.match(panel, /onPress=\{\(\) => onApply\(action\)\}/);
  assert.match(panel, /Ready to act with current API grants, tools, skills, and runtime context/);
});

test("readiness proposed actions use existing bot update and invalidate capability queries", () => {
  const panel = readUiFile("src/components/shared/AgentReadinessPanel.tsx");
  const hook = readUiFile("src/api/hooks/useAgentCapabilities.ts");

  assert.match(panel, /applyAgentReadinessRepair\(\{/);
  assert.match(hook, /preflightAgentRepair\(\{/);
  assert.match(hook, /updateBotConfig\(botId, action\.apply\.patch as Partial<BotConfig>\)/);
  assert.match(hook, /preflight\.status === "blocked" \|\| preflight\.status === "stale"/);
  assert.match(hook, /preflight\.status === "noop"/);
  assert.match(panel, /action\.apply\.type === "bot_patch"/);
  assert.match(panel, /navigate\(href\)/);
  assert.match(panel, /WORKSPACE_ATTENTION_BRIEF_KEY/);
  assert.match(panel, /WORKSPACE_ATTENTION_KEY/);
  assert.match(panel, /queryKey: \["agent-capabilities"\]/);
  assert.match(panel, /queryKey: \["admin-bots"\]/);
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
