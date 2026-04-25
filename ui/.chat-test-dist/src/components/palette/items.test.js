import test from "node:test";
import assert from "node:assert/strict";
import { buildPaletteItems } from "./catalog.js";
import { getCollapsiblePaletteBrowseSection, scorePaletteSearchItems, shouldIncludePaletteBrowseItem, shouldIncludePaletteSearchItem, } from "./search.js";
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
test("buildPaletteItems keeps channel settings searchable but hidden from browse defaults", () => {
    const items = buildPaletteItems({
        isAdmin: false,
        channels: [
            { id: "channel-1", name: "quality-assurance" },
        ],
    });
    const chat = items.find((item) => item.href === "/channels/channel-1");
    const settings = items.find((item) => item.href === "/channels/channel-1/settings");
    assert.equal(chat?.hideFromBrowse, undefined);
    assert.equal(settings?.hideFromBrowse, true);
    assert.equal(chat ? shouldIncludePaletteBrowseItem(chat) : null, true);
    assert.equal(settings ? shouldIncludePaletteBrowseItem(settings) : null, false);
});
test("palette browse collapse classifier targets noisy detail families only", () => {
    const items = buildPaletteItems({
        isAdmin: true,
        tools: [{ id: "tool-1", tool_name: "web.search" }],
        toolPolicies: [{ id: "policy-1", tool_name: "web.search" }],
        traces: [{ correlation_id: "trace-1", title: "Slack sync failed" }],
    });
    const navTools = items.find((item) => item.id === "nav-tools");
    const toolDetail = items.find((item) => item.id === "tool-tool-1");
    const navPolicies = items.find((item) => item.id === "nav-policies");
    const policyDetail = items.find((item) => item.id === "policy-policy-1");
    const traceDetail = items.find((item) => item.id === "trace-trace-1");
    assert.equal(navTools ? getCollapsiblePaletteBrowseSection(navTools) : null, null);
    assert.equal(toolDetail ? getCollapsiblePaletteBrowseSection(toolDetail) : null, "tools");
    assert.equal(navPolicies ? getCollapsiblePaletteBrowseSection(navPolicies) : null, null);
    assert.equal(policyDetail ? getCollapsiblePaletteBrowseSection(policyDetail) : null, "policies");
    assert.equal(traceDetail ? getCollapsiblePaletteBrowseSection(traceDetail) : null, "traces");
});
test("tool detail rows stay out of typed search while the tools page matches tool names", () => {
    const items = buildPaletteItems({
        isAdmin: true,
        channels: [
            { id: "channel-jellyfin", name: "jellyfin-support" },
        ],
        tools: [
            { id: "tool-users", tool_name: "jellyfin_users" },
            { id: "tool-library", tool_name: "jellyfin_library" },
            { id: "tool-manage", tool_name: "jellyseerr_manage" },
            { id: "tool-search", tool_name: "jellyseerr_search" },
        ],
    });
    const navTools = items.find((item) => item.id === "nav-tools");
    const toolDetails = items.filter((item) => item.id.startsWith("tool-"));
    const searchable = items.filter(shouldIncludePaletteSearchItem);
    const results = scorePaletteSearchItems(searchable, "jell", new Map(), 10);
    assert.ok(navTools?.searchText?.includes("jellyfin_users"));
    assert.equal(toolDetails.length, 4);
    assert.deepEqual(toolDetails.map((item) => shouldIncludePaletteSearchItem(item)), [false, false, false, false]);
    assert.equal(results[0]?.item.href, "/channels/channel-jellyfin");
    assert.ok(results.some((result) => result.item.href === "/admin/tools"));
    assert.equal(results.some((result) => result.item.href?.startsWith("/admin/tools/")), false);
});
