import type { ToolItem } from "@/src/api/hooks/useTools";

export function scaffoldArgsFromSchema(tool: ToolItem): Record<string, any> {
  const params = tool.parameters ?? tool.schema_?.parameters;
  if (!params || typeof params !== "object") return {};
  const properties = params.properties ?? params;
  if (!properties || typeof properties !== "object") return {};
  const scaffold: Record<string, any> = {};
  for (const [key, def] of Object.entries(properties)) {
    const d = def as any;
    if (d.default !== undefined) {
      scaffold[key] = d.default;
    } else if (d.type === "string") {
      scaffold[key] = "";
    } else if (d.type === "number" || d.type === "integer") {
      scaffold[key] = 0;
    } else if (d.type === "boolean") {
      scaffold[key] = false;
    } else if (d.type === "array") {
      scaffold[key] = [];
    } else if (d.type === "object") {
      scaffold[key] = {};
    } else {
      scaffold[key] = null;
    }
  }
  return scaffold;
}

export function getParamDescriptions(tool: ToolItem): Map<string, string> {
  const descs = new Map<string, string>();
  const params = tool.parameters ?? tool.schema_?.parameters;
  if (!params || typeof params !== "object") return descs;
  const properties = params.properties ?? params;
  if (!properties || typeof properties !== "object") return descs;
  const required = new Set<string>(params.required ?? []);
  for (const [key, def] of Object.entries(properties)) {
    const d = def as any;
    const parts: string[] = [];
    if (d.type) parts.push(d.type);
    if (required.has(key)) parts.push("required");
    if (d.description) parts.push(`— ${d.description}`);
    descs.set(key, parts.join(" "));
  }
  return descs;
}
