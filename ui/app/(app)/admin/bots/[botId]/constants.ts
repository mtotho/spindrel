export const SECTIONS = [
  { key: "identity", label: "Identity" },
  { key: "prompt", label: "System Prompt" },
  { key: "persona", label: "Persona" },
  { key: "tools", label: "Tools" },
  { key: "skills", label: "Skills" },
  { key: "memory", label: "Memory" },
  { key: "knowledge", label: "Knowledge" },
  { key: "elevation", label: "Elevation" },
  { key: "attachments", label: "Attachments" },
  { key: "workspace", label: "Workspace" },
  { key: "delegation", label: "Delegation" },
  { key: "permissions", label: "Permissions" },
  { key: "tool_policies", label: "Tool Policies" },
  { key: "display", label: "Display" },
  { key: "advanced", label: "Advanced" },
] as const;

export type SectionKey = (typeof SECTIONS)[number]["key"];

export const MOBILE_NAV_BREAKPOINT = 768;
