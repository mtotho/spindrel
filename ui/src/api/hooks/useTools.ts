import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface ActiveWidgetPackage {
  id: string;
  name: string;
  source: "seed" | "user";
}

export interface ToolItem {
  id: string;
  tool_key: string;
  tool_name: string;
  server_name?: string | null;
  source_dir?: string | null;
  source_integration?: string | null;
  source_file?: string | null;
  description?: string | null;
  parameters?: Record<string, any> | null;
  schema_?: Record<string, any> | null;
  indexed_at: string;
  active_widget_package?: ActiveWidgetPackage | null;
  widget_package_count?: number;
  requires_bot_context?: boolean;
  requires_channel_context?: boolean;
}

export function useTools() {
  return useQuery({
    queryKey: ["admin-tools"],
    queryFn: () => apiFetch<ToolItem[]>("/api/v1/admin/tools"),
  });
}

export function useTool(toolId: string | undefined) {
  return useQuery({
    queryKey: ["admin-tool", toolId],
    queryFn: () => apiFetch<ToolItem>(`/api/v1/admin/tools/${toolId}`),
    enabled: !!toolId,
  });
}

export interface ToolExecuteResponse {
  tool_name: string;
  result: unknown;
  error?: string | null;
}

export function executeTool(
  toolName: string,
  args: Record<string, unknown>,
  opts?: { bot_id?: string | null; channel_id?: string | null },
): Promise<ToolExecuteResponse> {
  const body: Record<string, unknown> = { arguments: args };
  if (opts?.bot_id) body.bot_id = opts.bot_id;
  if (opts?.channel_id) body.channel_id = opts.channel_id;
  return apiFetch<ToolExecuteResponse>(
    `/api/v1/admin/tools/${encodeURIComponent(toolName)}/execute`,
    { method: "POST", body: JSON.stringify(body) },
  );
}
