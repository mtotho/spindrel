import { Bot, Cable, FileText, HardDrive, Hash, Home, Key, LayoutDashboard, Layers, Plus, Plug, FolderKanban, ScrollText, Server, Settings, Shield, Webhook, Wrench, Boxes, Zap, } from "lucide-react";
import { ADMIN_ITEMS, SETTINGS_ITEMS } from "./admin-items.js";
const CHANNEL_SLUG_PREFIX = "channel:";
function isChannelSlug(slug) {
    return slug.startsWith(CHANNEL_SLUG_PREFIX);
}
function channelIdFromSlug(slug) {
    if (!isChannelSlug(slug))
        return null;
    return slug.slice(CHANNEL_SLUG_PREFIX.length) || null;
}
function tagChannel(name) {
    return name.startsWith("#") ? name : `#${name}`;
}
function pushUnique(items, next) {
    if (items.some((item) => item.href === next.href))
        return;
    items.push(next);
}
export function buildPaletteItems(input) {
    const items = [];
    const botNameById = new Map((input.bots ?? []).map((bot) => [bot.id, bot.name]));
    pushUnique(items, {
        id: "nav-home",
        label: "Home",
        hint: "All channels",
        href: "/",
        icon: Home,
        category: "Channels",
    });
    pushUnique(items, {
        id: "nav-new-channel",
        label: "New channel",
        hint: "Create a channel",
        href: "/channels/new",
        icon: Plus,
        category: "Channels",
    });
    pushUnique(items, {
        id: "nav-widgets",
        label: "Widget dashboards",
        hint: "Pinned artifacts",
        href: "/widgets",
        icon: LayoutDashboard,
        category: "Widgets",
    });
    pushUnique(items, {
        id: "nav-widgets-dev",
        label: "Widget developer panel",
        hint: "Artifacts",
        href: "/widgets/dev",
        icon: Wrench,
        category: "Widgets",
    });
    for (const item of SETTINGS_ITEMS) {
        pushUnique(items, item);
    }
    for (const channel of input.channels ?? []) {
        const channelLabel = tagChannel(channel.name);
        const botName = channel.bot_id ? botNameById.get(channel.bot_id) : null;
        const hint = [channel.integration, botName].filter(Boolean).join(" · ") || "Channels";
        pushUnique(items, {
            id: `channel-chat-${channel.id}`,
            label: channelLabel,
            hint,
            href: `/channels/${channel.id}`,
            icon: Hash,
            category: "Channels",
            lastMessageAt: channel.last_message_at ?? null,
            searchText: `chat ${channelLabel} ${channel.name}`,
        });
        pushUnique(items, {
            id: `channel-settings-${channel.id}`,
            label: `Settings · ${channelLabel}`,
            hint: "Channels",
            href: `/channels/${channel.id}/settings`,
            icon: Settings,
            category: "Channels",
            hideFromBrowse: true,
        });
        pushUnique(items, {
            id: `channel-dashboard-${channel.id}`,
            label: `Workbench · ${channelLabel}`,
            hint: "Pinned artifacts",
            href: `/widgets/channel/${channel.id}`,
            icon: LayoutDashboard,
            category: "Widgets",
        });
    }
    if (!input.isAdmin) {
        return items;
    }
    for (const item of ADMIN_ITEMS) {
        pushUnique(items, { ...item });
    }
    const navTools = items.find((item) => item.id === "nav-tools");
    if (navTools && input.tools?.length) {
        navTools.searchText = input.tools.map((tool) => tool.tool_name).join(" ");
    }
    for (const bot of input.bots ?? []) {
        pushUnique(items, {
            id: `bot-${bot.id}`,
            label: `Bot · ${bot.name}`,
            hint: "Configure",
            href: `/admin/bots/${bot.id}`,
            icon: Bot,
            category: "Bots",
        });
    }
    for (const provider of input.providers ?? []) {
        pushUnique(items, {
            id: `provider-${provider.id}`,
            label: `Provider · ${provider.display_name}`,
            hint: "Configure",
            href: `/admin/providers/${provider.id}`,
            icon: Server,
            category: "Configure",
        });
    }
    for (const server of input.mcpServers ?? []) {
        pushUnique(items, {
            id: `mcp-${server.id}`,
            label: `MCP Server · ${server.display_name}`,
            hint: "Configure",
            href: `/admin/mcp-servers/${server.id}`,
            icon: Cable,
            category: "Configure",
        });
    }
    for (const tool of input.tools ?? []) {
        pushUnique(items, {
            id: `tool-${tool.id}`,
            label: `Tool · ${tool.tool_name}`,
            hint: "Configure",
            href: `/admin/tools/${tool.id}`,
            icon: Wrench,
            category: "Configure",
            hideFromSearch: true,
        });
    }
    for (const template of input.promptTemplates ?? []) {
        pushUnique(items, {
            id: `template-${template.id}`,
            label: `Template · ${template.name}`,
            hint: "Configure",
            href: `/admin/prompt-templates/${template.id}`,
            icon: FileText,
            category: "Configure",
        });
    }
    for (const stack of input.dockerStacks ?? []) {
        const name = stack.name?.trim() || stack.id;
        pushUnique(items, {
            id: `docker-${stack.id}`,
            label: `Docker Stack · ${name}`,
            hint: "Configure",
            href: `/admin/docker-stacks/${stack.id}`,
            icon: Boxes,
            category: "Configure",
        });
    }
    for (const integration of input.integrations ?? []) {
        if (integration.lifecycle_status === "available")
            continue;
        pushUnique(items, {
            id: `integration-${integration.id}`,
            label: `Integration · ${integration.name}`,
            hint: "Integrations",
            href: `/admin/integrations/${integration.id}`,
            icon: Plug,
            category: "Integrations",
        });
    }
    for (const section of input.sidebarSections ?? []) {
        for (const item of section.items) {
            pushUnique(items, {
                id: `sidebar-${section.id}-${item.href}`,
                label: `${section.title} · ${item.label}`,
                hint: "Integrations",
                href: item.href,
                icon: Plug,
                category: "Integrations",
            });
        }
    }
    for (const webhook of input.webhooks ?? []) {
        pushUnique(items, {
            id: `webhook-${webhook.id}`,
            label: `Webhook · ${webhook.name}`,
            hint: "Developer",
            href: `/admin/webhooks/${webhook.id}`,
            icon: Webhook,
            category: "Developer",
        });
    }
    for (const key of input.apiKeys ?? []) {
        pushUnique(items, {
            id: `api-key-${key.id}`,
            label: `API Key · ${key.name}`,
            hint: "Developer",
            href: `/admin/api-keys/${key.id}`,
            icon: Key,
            category: "Developer",
        });
    }
    for (const policy of input.toolPolicies ?? []) {
        pushUnique(items, {
            id: `policy-${policy.id}`,
            label: `Policy · ${policy.tool_name}`,
            hint: "Security",
            href: `/admin/tool-policies/${policy.id}`,
            icon: Shield,
            category: "Security",
        });
    }
    for (const workflow of input.workflows ?? []) {
        pushUnique(items, {
            id: `workflow-${workflow.id}`,
            label: `Workflow · ${workflow.name}`,
            hint: "Automate",
            href: `/admin/workflows/${workflow.id}`,
            icon: Zap,
            category: "Automate",
        });
    }
    for (const workspace of input.workspaces ?? []) {
        pushUnique(items, {
            id: `workspace-${workspace.id}`,
            label: `Workspace · ${workspace.name}`,
            hint: "Configure",
            href: `/admin/workspaces/${workspace.id}`,
            icon: HardDrive,
            category: "Configure",
        });
        pushUnique(items, {
            id: `workspace-files-${workspace.id}`,
            label: `Files · ${workspace.name}`,
            hint: "Configure",
            href: `/admin/workspaces/${workspace.id}/files`,
            icon: HardDrive,
            category: "Configure",
        });
    }
    pushUnique(items, {
        id: "nav-projects",
        label: "Projects",
        hint: "Configure",
        href: "/admin/projects",
        icon: FolderKanban,
        category: "Projects",
    });
    pushUnique(items, {
        id: "nav-project-blueprints",
        label: "Project Blueprints",
        hint: "Projects",
        href: "/admin/projects/blueprints",
        icon: Layers,
        category: "Projects",
    });
    for (const project of input.projects ?? []) {
        pushUnique(items, {
            id: `project-${project.id}`,
            label: `Project · ${project.name}`,
            hint: project.root_path ? `/${project.root_path.replace(/^\/+/, "")}` : "Projects",
            href: `/admin/projects/${project.id}`,
            icon: FolderKanban,
            category: "Projects",
            searchText: [project.name, project.slug, project.root_path].filter(Boolean).join(" "),
        });
    }
    for (const blueprint of input.projectBlueprints ?? []) {
        pushUnique(items, {
            id: `project-blueprint-${blueprint.id}`,
            label: `Blueprint · ${blueprint.name}`,
            hint: "Projects",
            href: `/admin/projects/blueprints/${blueprint.id}`,
            icon: Layers,
            category: "Projects",
            searchText: [blueprint.name, blueprint.slug].filter(Boolean).join(" "),
        });
    }
    for (const dashboard of input.dashboards ?? []) {
        if (isChannelSlug(dashboard.slug)) {
            const channelId = channelIdFromSlug(dashboard.slug);
            if (!channelId)
                continue;
            pushUnique(items, {
                id: `dashboard-channel-${channelId}`,
                label: `Workbench · ${tagChannel(dashboard.name)}`,
                hint: "Pinned artifacts",
                href: `/widgets/channel/${channelId}`,
                icon: LayoutDashboard,
                category: "Widgets",
            });
            continue;
        }
        pushUnique(items, {
            id: `dashboard-${dashboard.slug}`,
            label: `Dashboard · ${dashboard.name}`,
            hint: "Pinned artifacts",
            href: `/widgets/${dashboard.slug}`,
            icon: LayoutDashboard,
            category: "Widgets",
        });
    }
    for (const trace of input.traces ?? []) {
        pushUnique(items, {
            id: `trace-${trace.correlation_id}`,
            label: `Trace · ${trace.title?.trim() || trace.channel_name?.trim() || trace.correlation_id.slice(0, 8)}`,
            hint: "Monitor",
            href: `/admin/logs/${trace.correlation_id}`,
            icon: ScrollText,
            category: "Monitor",
        });
    }
    return items;
}
