export function inlinePreviewValue(value: unknown): string {
  if (value == null) return "null";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (typeof value === "object") {
    const count = Object.keys(value as Record<string, unknown>).length;
    return `${count} field${count === 1 ? "" : "s"}`;
  }
  return typeof value;
}
