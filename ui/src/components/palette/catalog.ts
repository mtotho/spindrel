import {
  Bot,
  Cable,
  FileText,
  HardDrive,
  Hash,
  Home,
  Key,
  LayoutDashboard,
  Plus,
  Plug,
  ScrollText,
  Server,
  Settings,
  Shield,
  Webhook,
  Wrench,
  Boxes,
  Zap,
} from "lucide-react";
import type { PaletteItem } from "./types";
import { ADMIN_ITEMS, SETTINGS_ITEMS } from "./admin-items.js";

export interface PaletteCatalogInput {
  isAdmin: boolean;
  channels?: Array<{
    id: string;
    name: string;
    integration?: string | null;
    bot_id?: string | null;
    private?: boolean;
    last_message_at?: string | null;
  }>;
  bots?: Array<{ id: string; name: string }>;
  providers?: Array<{ id: string; display_name: string }>;
  mcpServers?: Array<{ id: string; display_name: string }>;
  tools?: Array<{ id: string; tool_name: string }>;
  promptTemplates?: Array<{ id: string; name: string }>;
  webhooks?: Array<{ id: string; name: string }>;
  apiKeys?: Array<{ id: string; name: string }>;
  toolPolicies?: Array<{ id: string; tool_name: string }>;
  dockerStacks?: Array<{ id: string; name?: string | null }>;
  workflows?: Array<{ id: string; name: string }>;
  workspaces?: Array<{ id: string; name: string }>;
  dashboards?: Array<{ slug: string; name: string }>;
  integrations?: Array<{ id: string; name: string; lifecycle_status?: string }>;
  sidebarSections?: Array<{
    id: string;
    title: string;
    items: Array<{ href: string; label: string }>;
  }>;
  traces?: Array<{ correlation_id: string; title?: string | null; channel_name?: string | null }>;
}

const CHANNEL_SLUG_PREFIX = "channel:";

function isChannelSlug(slug: string): boolean {
  return slug.startsWith(CHANNEL_SLUG_PREFIX);
}

function channelIdFromSlug(slug: string): string | null {
  if (!isChannelSlug(slug)) return null;
  return slug.slice(CHANNEL_SLUG_PREFIX.length) || null;
}

function tagChannel(name: string): string {
  return name.startsWith("#") ? name : `#${name}`;
}

function pushUnique(items: PaletteItem[], next: PaletteItem) {
  if (items.some((item) => item.href === next.href)) return;
  items.push(next);
}

export function buildPaletteItems(input: PaletteCatalogInput): PaletteItem[] {
  const items: PaletteItem[] = [];
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
    label: "Widgets",
    hint: "Pinned widgets dashboard",
    href: "/widgets",
    icon: LayoutDashboard,
    category: "Widgets",
  });
  pushUnique(items, {
    id: "nav-widgets-dev",
    label: "Widget developer panel",
    hint: "Widgets",
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
      label: `Chat · ${channelLabel}`,
      hint,
      href: `/channels/${channel.id}`,
      icon: Hash,
      category: "Channels",
      lastMessageAt: channel.last_message_at ?? null,
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
      label: `Dashboard · ${channelLabel}`,
      hint: "Widgets",
      href: `/widgets/channel/${channel.id}`,
      icon: LayoutDashboard,
      category: "Widgets",
    });
  }

  if (!input.isAdmin) {
    return items;
  }

  for (const item of ADMIN_ITEMS) {
    pushUnique(items, item);
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
    if (integration.lifecycle_status === "available") continue;
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

  for (const dashboard of input.dashboards ?? []) {
    if (isChannelSlug(dashboard.slug)) {
      const channelId = channelIdFromSlug(dashboard.slug);
      if (!channelId) continue;
      pushUnique(items, {
        id: `dashboard-channel-${channelId}`,
        label: `Dashboard · ${tagChannel(dashboard.name)}`,
        hint: "Widgets",
        href: `/widgets/channel/${channelId}`,
        icon: LayoutDashboard,
        category: "Widgets",
      });
      continue;
    }
    pushUnique(items, {
      id: `dashboard-${dashboard.slug}`,
      label: `Dashboard · ${dashboard.name}`,
      hint: "Widgets",
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
