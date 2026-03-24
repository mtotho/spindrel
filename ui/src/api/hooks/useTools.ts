import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

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
