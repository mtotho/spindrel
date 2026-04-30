import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export type AgentReadinessStatus = "ok" | "needs_attention" | "error" | string;
export type AgentFindingSeverity = "info" | "warning" | "error" | string;

export interface AgentDoctorFinding {
  severity: AgentFindingSeverity;
  code: string;
  message: string;
  next_action?: string;
}

export interface AgentToolDetail {
  name: string;
  profile?: string | null;
  description?: string | null;
  safety_tier?: string | null;
  execution_policy?: string | null;
  source_integration?: string | null;
  source_file?: string | null;
  requires_bot_context?: boolean;
  requires_channel_context?: boolean;
  enrolled?: boolean;
  pinned?: boolean;
  configured?: boolean;
  has_return_schema?: boolean;
}

export interface AgentCapabilityManifest {
  schema_version: string;
  context: {
    bot_id?: string | null;
    bot_name?: string | null;
    channel_id?: string | null;
    channel_name?: string | null;
    session_id?: string | null;
  };
  api: {
    scopes?: string[];
    endpoint_count?: number;
    endpoints?: unknown[];
  };
  tools: {
    catalog_count?: number;
    working_set_count?: number;
    configured?: string[];
    pinned?: string[];
    enrolled?: Array<{ name: string; source?: string; enrolled_at?: string | null; fetch_count?: number }>;
    profiles?: Record<string, number>;
    safety_tiers?: Record<string, number>;
    recommended_core?: string[];
    details?: AgentToolDetail[];
    details_truncated?: boolean;
  };
  skills: {
    working_set_count?: number;
    bot_enrolled?: Array<{ id: string; name?: string | null; source?: string; scope?: string }>;
    channel_enrolled?: Array<{ id: string; name?: string | null; source?: string; scope?: string }>;
  };
  project: {
    attached?: boolean;
    id?: string;
    name?: string | null;
    root_path?: string | null;
    runtime_env?: { ready?: boolean; missing_secrets?: string[]; invalid_env_keys?: string[]; reserved_env_keys?: string[]; error?: string };
  };
  harness: {
    runtime?: string | null;
    workdir?: string | null;
    bridge_status?: string | null;
  };
  widgets: {
    authoring_tools?: string[];
    health_loop?: string | null;
  };
  doctor: {
    status: AgentReadinessStatus;
    findings: AgentDoctorFinding[];
  };
}

export interface AgentCapabilitiesArgs {
  botId?: string | null;
  channelId?: string | null;
  sessionId?: string | null;
  includeSchemas?: boolean;
  includeEndpoints?: boolean;
  maxTools?: number;
  enabled?: boolean;
}

export function useAgentCapabilities({
  botId,
  channelId,
  sessionId,
  includeSchemas = false,
  includeEndpoints = false,
  maxTools = 40,
  enabled = true,
}: AgentCapabilitiesArgs) {
  return useQuery({
    queryKey: [
      "agent-capabilities",
      botId ?? "",
      channelId ?? "",
      sessionId ?? "",
      includeSchemas,
      includeEndpoints,
      maxTools,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (botId) params.set("bot_id", botId);
      if (channelId) params.set("channel_id", channelId);
      if (sessionId) params.set("session_id", sessionId);
      params.set("include_schemas", includeSchemas ? "true" : "false");
      params.set("include_endpoints", includeEndpoints ? "true" : "false");
      params.set("max_tools", String(maxTools));
      return apiFetch<AgentCapabilityManifest>(`/api/v1/agent-capabilities?${params.toString()}`);
    },
    enabled: enabled && Boolean(botId || channelId || sessionId),
    staleTime: 30_000,
  });
}
