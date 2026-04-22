import test from "node:test";
import assert from "node:assert/strict";
import { buildPaletteItems } from "./catalog.js";

test("buildPaletteItems includes the major durable destinations and detail pages", () => {
  const items = buildPaletteItems({
    isAdmin: true,
    channels: [
      {
        id: "channel-1",
        name: "quality-assurance",
        integration: "slack",
        bot_id: "bot-1",
        private: false,
        last_message_at: "2026-04-22T16:00:00Z",
      },
    ],
    bots: [
      { id: "bot-1", name: "Rolland" },
    ],
    providers: [
      { id: "provider-1", display_name: "OpenAI" },
    ],
    mcpServers: [
      { id: "mcp-1", display_name: "Filesystem" },
    ],
    tools: [
      { id: "tool-1", tool_name: "web.search" },
    ],
    promptTemplates: [
      { id: "tpl-1", name: "Incident summary" },
    ],
    webhooks: [
      { id: "wh-1", name: "PagerDuty" },
    ],
    apiKeys: [
      { id: "key-1", name: "Automation key" },
    ],
    toolPolicies: [
      { id: "rule-1", tool_name: "web.search" },
    ],
    dockerStacks: [
      { id: "stack-1", name: "sandbox-stack" },
    ],
    workflows: [
      { id: "workflow-1", name: "Nightly digest" },
    ],
    workspaces: [
      { id: "workspace-1", name: "Agent docs" },
    ],
    dashboards: [
      { slug: "ops", name: "Ops board" },
      { slug: "channel:channel-1", name: "quality-assurance" },
    ],
    integrations: [
      { id: "integration-1", name: "Slack", lifecycle_status: "enabled" },
    ],
    sidebarSections: [
      {
        id: "slack-settings",
        title: "Slack",
        items: [{ href: "/integration/integration-1/settings", label: "Settings" }],
      },
    ],
    traces: [
      { correlation_id: "trace-1", title: "Slack sync failed" },
    ],
  });

  const hrefs = new Set(items.map((item) => item.href));

  assert.ok(hrefs.has("/"));
  assert.ok(hrefs.has("/channels/new"));
  assert.ok(hrefs.has("/channels/channel-1"));
  assert.ok(hrefs.has("/channels/channel-1/settings"));
  assert.ok(hrefs.has("/widgets/channel/channel-1"));
  assert.ok(hrefs.has("/widgets/ops"));
  assert.ok(hrefs.has("/widgets/dev"));
  assert.ok(hrefs.has("/admin/providers/provider-1"));
  assert.ok(hrefs.has("/admin/mcp-servers/mcp-1"));
  assert.ok(hrefs.has("/admin/tools/tool-1"));
  assert.ok(hrefs.has("/admin/prompt-templates/tpl-1"));
  assert.ok(hrefs.has("/admin/webhooks/wh-1"));
  assert.ok(hrefs.has("/admin/api-keys/key-1"));
  assert.ok(hrefs.has("/admin/tool-policies/rule-1"));
  assert.ok(hrefs.has("/admin/docker-stacks/stack-1"));
  assert.ok(hrefs.has("/admin/workflows/workflow-1"));
  assert.ok(hrefs.has("/admin/workspaces/workspace-1"));
  assert.ok(hrefs.has("/admin/workspaces/workspace-1/files"));
  assert.ok(hrefs.has("/admin/logs/trace-1"));
  assert.ok(hrefs.has("/integration/integration-1/settings"));
});
