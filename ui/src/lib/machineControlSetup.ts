import { getApiBase } from "@/src/api/client";

export function resolveMachineControlServerUrl(origin?: string | null): string {
  const trimmed = String(origin || "").trim();
  if (!trimmed) return "";
  return trimmed.replace(/\/+$/, "");
}

function shellSingleQuote(value: string): string {
  return `'${value.replace(/'/g, `'\"'\"'`)}'`;
}

export function buildRemoteEnrollCommand(args: {
  serverUrl: string;
  providerId: string;
  apiKey: string;
  label?: string | null;
  config?: Record<string, unknown> | null;
}): string {
  const serverUrl = resolveMachineControlServerUrl(args.serverUrl);
  const providerId = encodeURIComponent(args.providerId);
  const label = (args.label || "").trim();
  const payload: Record<string, unknown> = {};
  if (label) payload.label = label;
  if (args.config && Object.keys(args.config).length > 0) payload.config = args.config;
  const body = JSON.stringify(payload);
  return [
    "curl -sS -X POST",
    `  -H ${shellSingleQuote(`Authorization: Bearer ${args.apiKey}`)}`,
    `  -H ${shellSingleQuote("Content-Type: application/json")}`,
    `  ${shellSingleQuote(`${getApiBase()}/api/v1/admin/machines/providers/${providerId}/enroll`)}`,
    `  -d ${shellSingleQuote(body)}`,
  ].join(" \\\n");
}
