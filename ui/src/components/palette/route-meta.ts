import {
  Bot,
  Plug,
  Server,
  Cable,
  Wrench,
  BookOpen,
  FileText,
  Boxes,
  ClipboardList,
  Zap,
  Shield,
  Key,
  Webhook,
  ScrollText,
  HardDrive,
  Clock,
  Hash,
} from "lucide-react";
import type { ComponentType } from "react";

type IconComponent = ComponentType<{ size: number; color: string }>;

export interface RouteMeta {
  icon: IconComponent;
  category: string;
  fallbackLabel: string;
}

const ROUTE_PREFIX_MAP: { prefix: string; meta: RouteMeta }[] = [
  { prefix: "/admin/tasks/", meta: { icon: ClipboardList, category: "Automate", fallbackLabel: "Task" } },
  { prefix: "/admin/bots/", meta: { icon: Bot, category: "Bots", fallbackLabel: "Edit Bot" } },
  { prefix: "/admin/skills/", meta: { icon: BookOpen, category: "Configure", fallbackLabel: "Skill" } },
  { prefix: "/admin/tools/", meta: { icon: Wrench, category: "Configure", fallbackLabel: "Tool" } },
  { prefix: "/admin/integrations/", meta: { icon: Plug, category: "Integrations", fallbackLabel: "Integration" } },
  { prefix: "/admin/providers/", meta: { icon: Server, category: "Configure", fallbackLabel: "Provider" } },
  { prefix: "/admin/mcp-servers/", meta: { icon: Cable, category: "Configure", fallbackLabel: "MCP Server" } },
  { prefix: "/admin/prompt-templates/", meta: { icon: FileText, category: "Configure", fallbackLabel: "Template" } },
  { prefix: "/admin/webhooks/", meta: { icon: Webhook, category: "Developer", fallbackLabel: "Webhook" } },
  { prefix: "/admin/workflows/", meta: { icon: Zap, category: "Automate", fallbackLabel: "Workflow" } },
  { prefix: "/admin/docker-stacks/", meta: { icon: Boxes, category: "Configure", fallbackLabel: "Docker Stack" } },
  { prefix: "/admin/tool-policies/", meta: { icon: Shield, category: "Security", fallbackLabel: "Policy" } },
  { prefix: "/admin/logs/", meta: { icon: ScrollText, category: "Monitor", fallbackLabel: "Log Trace" } },
  { prefix: "/admin/api-keys/", meta: { icon: Key, category: "Developer", fallbackLabel: "API Key" } },
  { prefix: "/admin/workspaces/", meta: { icon: HardDrive, category: "Configure", fallbackLabel: "Workspace" } },
  { prefix: "/channels/", meta: { icon: Hash, category: "Channels", fallbackLabel: "Channel" } },
];

export function resolveRouteMetadata(href: string): RouteMeta | null {
  for (const { prefix, meta } of ROUTE_PREFIX_MAP) {
    if (href.startsWith(prefix) && href.length > prefix.length) {
      const idPart = href.slice(prefix.length).split("/")[0].split("#")[0];
      const shortId = idPart.length > 8 ? idPart.slice(0, 7) + "\u2026" : idPart;
      return { ...meta, fallbackLabel: `${meta.fallbackLabel}: ${shortId}` };
    }
  }
  if (href.startsWith("/")) {
    return { icon: Clock, category: "Recent", fallbackLabel: href.split("/").pop() ?? "Page" };
  }
  return null;
}
