import type { ConfigField } from "@/src/types/api";

/** Build initial config values from config_fields defaults, overlaid with existing config. */
export function initConfigValues(
  fields: ConfigField[] | undefined,
  existingConfig: Record<string, any> | undefined,
): Record<string, any> {
  const values: Record<string, any> = {};
  if (!fields) return values;
  for (const f of fields) {
    values[f.key] = existingConfig?.[f.key] ?? f.default;
  }
  return values;
}

/** Collect non-default, non-empty config values for submission. */
export function collectConfigValues(
  fields: ConfigField[] | undefined,
  values: Record<string, any>,
): Record<string, any> {
  const result: Record<string, any> = {};
  if (!fields) return result;
  for (const f of fields) {
    const v = values[f.key];
    if (v === undefined || v === null) continue;
    if (Array.isArray(v) && v.length === 0) continue;
    if (v === f.default) continue;
    result[f.key] = v;
  }
  return result;
}

/** Produce a compact text summary of config values for display in binding cards. */
export function configSummaryText(
  dc: Record<string, any>,
  fields: ConfigField[] | undefined,
): string | null {
  if (!fields || fields.length === 0) {
    const userKeys = Object.keys(dc).filter(
      (k) => !["type", "chat_guid", "server_url", "password"].includes(k),
    );
    if (userKeys.length === 0) return null;
    return userKeys
      .map((k) => {
        const v = dc[k];
        if (Array.isArray(v)) return `${k}: ${v.join(", ")}`;
        return `${k}: ${v}`;
      })
      .join(" \u00b7 ");
  }
  const parts: string[] = [];
  for (const f of fields) {
    const v = dc[f.key];
    if (v === undefined || v === null) continue;
    if (v === f.default) continue;
    if (Array.isArray(v)) {
      if (v.length > 0) parts.push(`${f.label}: ${v.join(", ")}`);
    } else if (typeof v === "boolean") {
      parts.push(`${f.label}: ${v ? "on" : "off"}`);
    } else if (v !== "") {
      parts.push(`${f.label}: ${v}`);
    }
  }
  return parts.length > 0 ? parts.join(" \u00b7 ") : null;
}
