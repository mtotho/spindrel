import {
  Activity,
  BookOpen,
  Bot,
  Boxes,
  Cable,
  ClipboardList,
  Clock,
  Code2,
  FileCode,
  FileText,
  FolderKanban,
  HardDrive,
  Hash,
  Home,
  Key,
  LayoutDashboard,
  Layers,
  Lock,
  MessageCircle,
  Network,
  Paperclip,
  Plug,
  ScrollText,
  Search,
  Server,
  Settings,
  Shield,
  ShieldCheck,
  Users,
  Webhook,
  Wrench,
  Zap,
  Brain,
  BarChart3,
} from "lucide-react";
import type { ComponentType } from "react";

type IconComponent = ComponentType<{ size: number; color: string }>;

export interface PaletteRouteOptions {
  channelNameById?: ReadonlyMap<string, string>;
  dashboardNameBySlug?: ReadonlyMap<string, string>;
  recentLabel?: string | null;
  itemHint?: string | null;
}

export interface PaletteRoute {
  routeKind: string;
  canonicalHref: string;
  pageType: string;
  category: string;
  icon: IconComponent;
  label: string;
  hint?: string;
  recordable: boolean;
}

interface StaticRouteMeta {
  pageType: string;
  category: string;
  icon: IconComponent;
  label: string;
  hint?: string;
}

const STATIC_ROUTES = new Map<string, StaticRouteMeta>([
  ["/", { pageType: "Home", category: "Channels", icon: Home, label: "Home", hint: "Workspace overview" }],
  ["/spatial", { pageType: "Spatial Canvas", category: "Channels", icon: Network, label: "Spatial canvas", hint: "Workspace map" }],
  ["/canvas", { pageType: "Spatial Canvas", category: "Channels", icon: Network, label: "Spatial canvas", hint: "Workspace map" }],
  ["/channels/new", { pageType: "New channel", category: "Channels", icon: Hash, label: "New channel", hint: "Create a channel" }],
  ["/settings", { pageType: "Settings", category: "Settings", icon: Settings, label: "Settings", hint: "Settings" }],
  ["/settings/account", { pageType: "Settings", category: "Settings", icon: Settings, label: "Settings · Account", hint: "Settings" }],
  ["/settings/channels", { pageType: "Settings", category: "Settings", icon: Settings, label: "Settings · Channels", hint: "Settings" }],
  ["/settings/bots", { pageType: "Settings", category: "Settings", icon: Settings, label: "Settings · Bots", hint: "Settings" }],
  ["/widgets", { pageType: "Widgets", category: "Widgets", icon: LayoutDashboard, label: "Widgets", hint: "Pinned widgets dashboard" }],
  ["/widgets/dev", { pageType: "Dashboard", category: "Widgets", icon: Wrench, label: "Widget developer panel", hint: "Widgets" }],
  ["/admin/api-docs", { pageType: "API Docs", category: "Developer", icon: FileCode, label: "API Docs", hint: "Developer" }],
  ["/admin/api-keys", { pageType: "API Keys", category: "Developer", icon: Key, label: "API Keys", hint: "Developer" }],
  ["/admin/approvals", { pageType: "Approvals", category: "Security", icon: ShieldCheck, label: "Approvals", hint: "Security" }],
  ["/admin/attachments", { pageType: "Attachments", category: "Configure", icon: Paperclip, label: "Attachments", hint: "Configure" }],
  ["/admin/bots", { pageType: "Bots", category: "Configure", icon: Bot, label: "Bots", hint: "Configure" }],
  ["/admin/config-state", { pageType: "Config State", category: "Monitor", icon: Code2, label: "Config State", hint: "Monitor" }],
  ["/admin/delegations", { pageType: "Delegations", category: "Monitor", icon: Users, label: "Delegations", hint: "Monitor" }],
  ["/admin/diagnostics", { pageType: "Diagnostics", category: "Monitor", icon: HardDrive, label: "Diagnostics", hint: "Monitor" }],
  ["/admin/docker-stacks", { pageType: "Docker Stacks", category: "Configure", icon: Boxes, label: "Docker Stacks", hint: "Configure" }],
  ["/admin/integrations", { pageType: "Integrations", category: "Configure", icon: Plug, label: "Integrations", hint: "Configure" }],
  ["/admin/learning", { pageType: "Memory & Knowledge", category: "Automate", icon: Brain, label: "Memory & Knowledge", hint: "Automate" }],
  ["/admin/logs", { pageType: "Logs", category: "Monitor", icon: ScrollText, label: "Logs", hint: "Monitor" }],
  ["/admin/logs/fallbacks", { pageType: "Logs", category: "Monitor", icon: ScrollText, label: "Logs · Fallbacks", hint: "Monitor" }],
  ["/admin/logs/server", { pageType: "Logs", category: "Monitor", icon: ScrollText, label: "Logs · Server", hint: "Monitor" }],
  ["/admin/logs/traces", { pageType: "Logs", category: "Monitor", icon: ScrollText, label: "Logs · Traces", hint: "Monitor" }],
  ["/admin/mcp-servers", { pageType: "MCP Servers", category: "Configure", icon: Cable, label: "MCP Servers", hint: "Configure" }],
  ["/admin/memories", { pageType: "Memories", category: "Monitor", icon: Brain, label: "Memories", hint: "Monitor" }],
  ["/admin/prompt-templates", { pageType: "Templates", category: "Configure", icon: FileText, label: "Templates", hint: "Configure" }],
  ["/admin/projects", { pageType: "Projects", category: "Projects", icon: FolderKanban, label: "Projects", hint: "Projects" }],
  ["/admin/projects/blueprints", { pageType: "Blueprints", category: "Projects", icon: Layers, label: "Project Blueprints", hint: "Projects" }],
  ["/admin/providers", { pageType: "Providers", category: "Configure", icon: Server, label: "Providers", hint: "Configure" }],
  ["/admin/sandboxes", { pageType: "Sandboxes", category: "Monitor", icon: Boxes, label: "Sandboxes", hint: "Monitor" }],
  ["/admin/secret-values", { pageType: "Secrets", category: "Security", icon: Lock, label: "Secrets", hint: "Security" }],
  ["/admin/sessions", { pageType: "Sessions", category: "Monitor", icon: MessageCircle, label: "Sessions", hint: "Monitor" }],
  ["/admin/skills", { pageType: "Skills", category: "Configure", icon: BookOpen, label: "Skills", hint: "Configure" }],
  ["/admin/automations", { pageType: "Automations", category: "Automate", icon: ClipboardList, label: "Automations", hint: "Automate" }],
  ["/admin/tool-calls", { pageType: "Tool Calls", category: "Monitor", icon: Activity, label: "Tool Calls", hint: "Monitor" }],
  ["/admin/tool-policies", { pageType: "Policies", category: "Security", icon: Shield, label: "Policies", hint: "Security" }],
  ["/admin/tools", { pageType: "Tools", category: "Configure", icon: Wrench, label: "Tools", hint: "Configure" }],
  ["/admin/usage", { pageType: "Usage", category: "Monitor", icon: BarChart3, label: "Usage", hint: "Monitor" }],
  ["/admin/users", { pageType: "Users", category: "Monitor", icon: Users, label: "Users", hint: "Monitor" }],
  ["/admin/webhooks", { pageType: "Webhooks", category: "Developer", icon: Webhook, label: "Webhooks", hint: "Developer" }],
  ["/admin/workflows", { pageType: "Workflows", category: "Automate", icon: Zap, label: "Workflows", hint: "Automate" }],
  ["/admin/workspaces", { pageType: "Workspaces", category: "Configure", icon: HardDrive, label: "Workspaces", hint: "Configure" }],
]);

const ADMIN_DETAIL_ROUTES = [
  { prefix: "/admin/api-keys/", routeKind: "admin-api-key", pageType: "API Key", category: "Developer", icon: Key },
  { prefix: "/admin/bots/", routeKind: "admin-bot", pageType: "Bot", category: "Configure", icon: Bot },
  { prefix: "/admin/docker-stacks/", routeKind: "admin-docker-stack", pageType: "Docker Stack", category: "Configure", icon: Boxes },
  { prefix: "/admin/integrations/", routeKind: "admin-integration", pageType: "Integration", category: "Configure", icon: Plug },
  { prefix: "/admin/logs/", routeKind: "admin-trace", pageType: "Trace", category: "Monitor", icon: ScrollText },
  { prefix: "/admin/mcp-servers/", routeKind: "admin-mcp-server", pageType: "MCP Server", category: "Configure", icon: Cable },
  { prefix: "/admin/prompt-templates/", routeKind: "admin-prompt-template", pageType: "Template", category: "Configure", icon: FileText },
  { prefix: "/admin/projects/blueprints/", routeKind: "admin-project-blueprint", pageType: "Blueprint", category: "Projects", icon: Layers },
  { prefix: "/admin/projects/", routeKind: "admin-project", pageType: "Project", category: "Projects", icon: FolderKanban },
  { prefix: "/admin/providers/", routeKind: "admin-provider", pageType: "Provider", category: "Configure", icon: Server },
  { prefix: "/admin/skills/", routeKind: "admin-skill", pageType: "Skill", category: "Configure", icon: BookOpen },
  { prefix: "/admin/automations/", routeKind: "admin-task", pageType: "Automation", category: "Automate", icon: ClipboardList },
  { prefix: "/admin/tool-policies/", routeKind: "admin-tool-policy", pageType: "Policy", category: "Security", icon: Shield },
  { prefix: "/admin/tools/", routeKind: "admin-tool", pageType: "Tool", category: "Configure", icon: Wrench },
  { prefix: "/admin/webhooks/", routeKind: "admin-webhook", pageType: "Webhook", category: "Developer", icon: Webhook },
  { prefix: "/admin/workflows/", routeKind: "admin-workflow", pageType: "Workflow", category: "Automate", icon: Zap },
  { prefix: "/admin/workspaces/", routeKind: "admin-workspace", pageType: "Workspace", category: "Configure", icon: HardDrive },
];

function splitHref(href: string): { pathname: string; search: string; hash: string } {
  const hashIndex = href.indexOf("#");
  const hash = hashIndex === -1 ? "" : href.slice(hashIndex);
  const pathAndSearch = hashIndex === -1 ? href : href.slice(0, hashIndex);
  const searchIndex = pathAndSearch.indexOf("?");
  if (searchIndex === -1) {
    return { pathname: pathAndSearch, search: "", hash };
  }
  return {
    pathname: pathAndSearch.slice(0, searchIndex),
    search: pathAndSearch.slice(searchIndex),
    hash,
  };
}

function composeHref(pathname: string, search = "", hash = ""): string {
  return `${pathname}${search}${hash}`;
}

function shortToken(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "item";
  const first = trimmed.split(/[/?#]/)[0];
  const dash = first.indexOf("-");
  if (dash > 0) {
    return `${first.slice(0, dash)}…`;
  }
  if (first.length <= 8) return first;
  return `${first.slice(0, 8)}…`;
}

function normalizeChannelName(name: string | undefined): string | null {
  if (!name) return null;
  return name.startsWith("#") ? name : `#${name}`;
}

function parseRecentLabel(recentLabel: string | null | undefined): { title: string | null; context: string | null } {
  const trimmed = recentLabel?.trim();
  if (!trimmed) return { title: null, context: null };
  const divider = trimmed.lastIndexOf(" · #");
  if (divider === -1) {
    return { title: trimmed, context: null };
  }
  return {
    title: trimmed.slice(0, divider).trim() || null,
    context: trimmed.slice(divider + 3).trim() || null,
  };
}

function matchChannelName(channelId: string, options?: PaletteRouteOptions): string | null {
  const channelName = options?.channelNameById?.get(channelId);
  return normalizeChannelName(channelName ?? undefined);
}

function buildTypedLabel(pageType: string, title: string | null, fallback: string): string {
  return `${pageType} · ${title?.trim() || fallback}`;
}

function buildChannelChatLabel(channelLabel: string): string {
  return channelLabel;
}

function resolveStaticRoute(canonicalHref: string): PaletteRoute | null {
  const { pathname } = splitHref(canonicalHref);
  const meta = STATIC_ROUTES.get(pathname);
  if (!meta) return null;
  return {
    routeKind: pathname === "/" ? "home" : pathname.slice(1).replaceAll("/", "-"),
    canonicalHref,
    pageType: meta.pageType,
    category: meta.category,
    icon: meta.icon,
    label: meta.label,
    hint: meta.hint,
    recordable: true,
  };
}

function resolveChannelRoute(canonicalHref: string, options?: PaletteRouteOptions): PaletteRoute | null {
  const { pathname } = splitHref(canonicalHref);
  let match = pathname.match(/^\/channels\/([^/]+)$/);
  if (match) {
    const channelLabel = matchChannelName(match[1], options) ?? `#${shortToken(match[1])}`;
    return {
      routeKind: "channel-chat",
      canonicalHref,
      pageType: "Chat",
      category: "Channels",
      icon: Hash,
      label: buildChannelChatLabel(channelLabel),
      hint: options?.itemHint?.trim() || "Channels",
      recordable: true,
    };
  }

  match = pathname.match(/^\/channels\/([^/]+)\/settings$/);
  if (match) {
    const channelLabel = matchChannelName(match[1], options) ?? `#${shortToken(match[1])}`;
    return {
      routeKind: "channel-settings",
      canonicalHref,
      pageType: "Settings",
      category: "Channels",
      icon: Settings,
      label: buildTypedLabel("Settings", null, channelLabel),
      hint: "Channels",
      recordable: true,
    };
  }

  match = pathname.match(/^\/channels\/([^/]+)\/session\/([^/?#]+)$/);
  if (match) {
    const channelLabel = matchChannelName(match[1], options) ?? `#${shortToken(match[1])}`;
    const { title } = parseRecentLabel(options?.recentLabel);
    const cleanTitle = title && title !== "Session" ? title : null;
    return {
      routeKind: "channel-session",
      canonicalHref,
      pageType: "Session",
      category: "Channels",
      icon: Hash,
      label: buildTypedLabel("Session", cleanTitle, channelLabel),
      hint: channelLabel,
      recordable: true,
    };
  }

  match = pathname.match(/^\/channels\/([^/]+)\/threads\/([^/?#]+)$/);
  if (match) {
    const channelLabel = matchChannelName(match[1], options) ?? `#${shortToken(match[1])}`;
    const { title } = parseRecentLabel(options?.recentLabel);
    return {
      routeKind: "channel-thread",
      canonicalHref,
      pageType: "Thread",
      category: "Channels",
      icon: MessageCircle,
      label: buildTypedLabel("Thread", title, channelLabel),
      hint: channelLabel,
      recordable: true,
    };
  }

  match = pathname.match(/^\/channels\/([^/]+)\/pipelines\/([^/?#]+)$/);
  if (match) {
    const channelLabel = matchChannelName(match[1], options) ?? `#${shortToken(match[1])}`;
    return {
      routeKind: "channel-pipeline",
      canonicalHref,
      pageType: "Pipeline",
      category: "Channels",
      icon: Zap,
      label: buildTypedLabel("Pipeline", null, shortToken(match[2])),
      hint: channelLabel,
      recordable: false,
    };
  }

  match = pathname.match(/^\/channels\/([^/]+)\/runs\/([^/?#]+)$/);
  if (match) {
    const channelLabel = matchChannelName(match[1], options) ?? `#${shortToken(match[1])}`;
    return {
      routeKind: "channel-run",
      canonicalHref,
      pageType: "Run",
      category: "Channels",
      icon: Activity,
      label: buildTypedLabel("Run", null, shortToken(match[2])),
      hint: channelLabel,
      recordable: false,
    };
  }

  return null;
}

function resolveWidgetRoute(canonicalHref: string, options?: PaletteRouteOptions): PaletteRoute | null {
  const { pathname } = splitHref(canonicalHref);
  let match = pathname.match(/^\/widgets\/channel\/([^/?#]+)$/);
  if (match) {
    const channelLabel = matchChannelName(match[1], options) ?? `#${shortToken(match[1])}`;
    return {
      routeKind: "widget-channel-dashboard",
      canonicalHref,
      pageType: "Dashboard",
      category: "Widgets",
      icon: LayoutDashboard,
      label: buildTypedLabel("Dashboard", null, channelLabel),
      hint: "Widgets",
      recordable: true,
    };
  }

  match = pathname.match(/^\/widgets\/([^/?#]+)$/);
  if (match && match[1] !== "dev" && match[1] !== "channel") {
    const dashboardName = options?.dashboardNameBySlug?.get(match[1]) ?? options?.recentLabel?.trim() ?? shortToken(match[1]);
    return {
      routeKind: "widget-dashboard",
      canonicalHref,
      pageType: "Dashboard",
      category: "Widgets",
      icon: LayoutDashboard,
      label: buildTypedLabel("Dashboard", dashboardName, shortToken(match[1])),
      hint: "Widgets",
      recordable: true,
    };
  }

  return null;
}

function resolveIntegrationRoute(canonicalHref: string, options?: PaletteRouteOptions): PaletteRoute | null {
  const { pathname } = splitHref(canonicalHref);
  const match = pathname.match(/^\/integration\/([^/]+)(?:\/(.*))?$/);
  if (!match) return null;
  const tail = match[2]?.trim();
  const title = options?.recentLabel?.trim() || null;
  return {
    routeKind: "integration-page",
    canonicalHref,
    pageType: "Integration",
    category: "Integrations",
    icon: Plug,
    label: buildTypedLabel("Integration", title, shortToken(match[1])),
    hint: tail ? tail.replaceAll("/", " / ") : "Integrations",
    recordable: true,
  };
}

function resolveAdminDetailRoute(canonicalHref: string, options?: PaletteRouteOptions): PaletteRoute | null {
  const { pathname } = splitHref(canonicalHref);
  if (pathname.match(/^\/admin\/workspaces\/[^/]+\/files$/)) {
    const workspaceId = pathname.split("/")[3];
    const title = options?.recentLabel?.trim() || null;
    return {
      routeKind: "admin-workspace-files",
      canonicalHref,
      pageType: "Files",
      category: "Configure",
      icon: HardDrive,
      label: buildTypedLabel("Files", title, shortToken(workspaceId)),
      hint: "Configure",
      recordable: true,
    };
  }

  for (const route of ADMIN_DETAIL_ROUTES) {
    if (!pathname.startsWith(route.prefix) || pathname === route.prefix.slice(0, -1)) continue;
    const id = pathname.slice(route.prefix.length).split("/")[0];
    const title = options?.recentLabel?.trim() || null;
    return {
      routeKind: route.routeKind,
      canonicalHref,
      pageType: route.pageType,
      category: route.category,
      icon: route.icon,
      label: buildTypedLabel(route.pageType, title, shortToken(id)),
      hint: route.category,
      recordable: true,
    };
  }
  return null;
}

export function canonicalizePaletteHref(href: string): string {
  const trimmed = href.trim();
  if (!trimmed) return trimmed;
  const { pathname, search, hash } = splitHref(trimmed);

  if (pathname === "/profile") return composeHref("/settings/account", search, hash);
  if (pathname === "/channels") return composeHref("/", search, hash);
  if (pathname === "/canvas") return composeHref("/spatial", search, hash);
  if (pathname === "/") {
    const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
    if (params.has("channel") || params.has("node")) return composeHref("/spatial", search, hash);
  }
  if (pathname === "/admin/widget-packages") return "/widgets/dev#library";
  if (pathname.startsWith("/admin/widget-packages/")) {
    const packageId = pathname.slice("/admin/widget-packages/".length).split("/")[0];
    if (!packageId) return "/widgets/dev#library";
    return `/widgets/dev?id=${encodeURIComponent(packageId)}#templates`;
  }
  if (pathname === "/admin/upcoming") return "/admin/automations?view=list";

  return composeHref(pathname, search, hash);
}

export function normalizePalettePathInput(input: string): string | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("/")) return canonicalizePaletteHref(trimmed);
  try {
    const url = new URL(trimmed);
    if (!url.pathname.startsWith("/")) return null;
    return canonicalizePaletteHref(`${url.pathname}${url.search}${url.hash}`);
  } catch {
    return null;
  }
}

export function resolvePaletteRoute(href: string, options?: PaletteRouteOptions): PaletteRoute | null {
  const canonicalHref = canonicalizePaletteHref(href);
  return (
    resolveStaticRoute(canonicalHref)
    ?? resolveChannelRoute(canonicalHref, options)
    ?? resolveWidgetRoute(canonicalHref, options)
    ?? resolveIntegrationRoute(canonicalHref, options)
    ?? resolveAdminDetailRoute(canonicalHref, options)
    ?? null
  );
}

export function isRecordablePaletteHref(href: string): boolean {
  const route = resolvePaletteRoute(href);
  return route?.recordable ?? true;
}
