export const SECTIONS = [
  { key: "identity", label: "Identity" },
  { key: "prompt", label: "System Prompt" },
  { key: "persona", label: "Persona" },
  { key: "tools", label: "Tools" },
  { key: "skills", label: "Skills" },
  { key: "learning", label: "Learning" },
  { key: "carapaces", label: "Capabilities" },
  { key: "memory", label: "Memory" },
  { key: "attachments", label: "Attachments" },
  { key: "workspace", label: "Workspace" },
  { key: "delegation", label: "Delegation" },
  { key: "permissions", label: "Permissions" },
  { key: "grants", label: "Grants" },
  { key: "tool_policies", label: "Tool Policies" },
  { key: "hooks", label: "Hooks" },
  { key: "display", label: "Display" },
  { key: "advanced", label: "Advanced" },
] as const;

export type SectionKey = (typeof SECTIONS)[number]["key"];

export const SECTION_KEYS = SECTIONS.map((s) => s.key) as unknown as readonly SectionKey[];

export const MOBILE_NAV_BREAKPOINT = 768;
