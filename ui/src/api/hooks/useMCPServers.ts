import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface MCPServerItem {
  id: string;
  display_name: string;
  url: string;
  is_enabled: boolean;
  has_api_key: boolean;
  config: Record<string, any>;
  source: string;
  source_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MCPServerCreatePayload {
  id: string;
  display_name: string;
  url: string;
  api_key?: string;
  is_enabled?: boolean;
  config?: Record<string, any>;
}

export interface MCPServerUpdatePayload {
  display_name?: string;
  url?: string;
  api_key?: string;
  is_enabled?: boolean;
  config?: Record<string, any>;
}

export interface MCPServerTestResult {
  ok: boolean;
  message: string;
  tool_count: number;
  tools: string[];
}

export function useMCPServers() {
  return useQuery({
    queryKey: ["admin-mcp-servers"],
    queryFn: () => apiFetch<MCPServerItem[]>("/api/v1/admin/mcp-servers"),
  });
}

export function useMCPServer(serverId: string | undefined) {
  return useQuery({
    queryKey: ["admin-mcp-server", serverId],
    queryFn: () => apiFetch<MCPServerItem>(`/api/v1/admin/mcp-servers/${serverId}`),
    enabled: !!serverId && serverId !== "new",
  });
}

export function useCreateMCPServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MCPServerCreatePayload) =>
      apiFetch<MCPServerItem>("/api/v1/admin/mcp-servers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-mcp-servers"] });
      qc.invalidateQueries({ queryKey: ["admin-tools"] });
    },
  });
}

export function useUpdateMCPServer(serverId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MCPServerUpdatePayload) =>
      apiFetch<MCPServerItem>(`/api/v1/admin/mcp-servers/${serverId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-mcp-servers"] });
      qc.invalidateQueries({ queryKey: ["admin-mcp-server", serverId] });
      qc.invalidateQueries({ queryKey: ["admin-tools"] });
    },
  });
}

export function useDeleteMCPServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) =>
      apiFetch(`/api/v1/admin/mcp-servers/${serverId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-mcp-servers"] });
      qc.invalidateQueries({ queryKey: ["admin-tools"] });
    },
  });
}

export function useTestMCPServer() {
  return useMutation({
    mutationFn: (serverId: string) =>
      apiFetch<MCPServerTestResult>(`/api/v1/admin/mcp-servers/${serverId}/test`, {
        method: "POST",
      }),
  });
}

export interface MCPServerTestInlinePayload {
  url: string;
  api_key?: string;
}

export function useTestMCPServerInline() {
  return useMutation({
    mutationFn: (data: MCPServerTestInlinePayload) =>
      apiFetch<MCPServerTestResult>("/api/v1/admin/mcp-servers/test-inline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
  });
}
