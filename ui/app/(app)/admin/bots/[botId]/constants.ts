export const BOT_GROUPS = [
  { key: "overview", label: "Overview" },
  { key: "identity", label: "Identity & Model" },
  { key: "prompt", label: "Prompt & Persona" },
  { key: "tools", label: "Tools & Skills" },
  { key: "memory", label: "Memory & Learning" },
  { key: "workspace", label: "Workspace & Files" },
  { key: "access", label: "Access & Automation" },
  { key: "advanced", label: "Advanced" },
] as const;

export type BotGroupKey = (typeof BOT_GROUPS)[number]["key"];

export const BOT_GROUP_KEYS = BOT_GROUPS.map((s) => s.key) as unknown as readonly BotGroupKey[];

export const LEGACY_SECTION_TO_GROUP: Record<string, BotGroupKey> = {
  overview: "overview",
  identity: "identity",
  prompt: "prompt",
  persona: "prompt",
  tools: "tools",
  skills: "tools",
  delegation: "tools",
  learning: "memory",
  memory: "memory",
  workspace: "workspace",
  attachments: "workspace",
  permissions: "access",
  grants: "access",
  tool_policies: "access",
  hooks: "access",
  display: "advanced",
  advanced: "advanced",
};

export const MOBILE_NAV_BREAKPOINT = 768;
