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

export interface AgentCapabilityAction {
  id: string;
  finding_code: string;
  kind: string;
  title: string;
  description: string;
  impact: string;
  required_actor_scopes?: string[];
  grants_scopes?: string[];
  apply:
    | { type: "bot_patch"; patch: Record<string, unknown> }
    | { type: "navigate"; href: string };
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

export interface AgentIntegrationGlobal {
  id: string;
  name: string;
  lifecycle_status: string;
  status: string;
  missing_required_settings?: string[];
  dependency_gaps?: {
    python?: string[];
    npm?: string[];
    system?: string[];
  };
  process?: {
    declared?: boolean;
    running?: boolean;
    exit_code?: number | null;
    restart_count?: number | null;
  };
  webhook_declared?: boolean;
  oauth_declared?: boolean;
  api_permissions_declared?: boolean;
  capabilities?: string[];
  rich_tool_results?: boolean;
  href?: string;
}

export interface AgentIntegrationBinding {
  id: string;
  integration_type: string;
  client_id: string;
  display_name?: string | null;
  activated?: boolean;
  stub_binding?: boolean;
  dispatch_config_keys?: string[];
  href?: string | null;
}

export interface AgentIntegrationActivationOption {
  integration_type: string;
  activated?: boolean;
  tools?: string[];
  includes?: string[];
  requires_workspace?: boolean;
  missing_config_fields?: string[];
  href?: string | null;
}

export interface AgentIntegrationReadiness {
  summary?: {
    enabled_count?: number;
    needs_setup_count?: number;
    dependency_gap_count?: number;
    process_gap_count?: number;
    channel_binding_count?: number;
    channel_activation_count?: number;
    channel_stub_binding_count?: number;
  };
  global?: AgentIntegrationGlobal[];
  channel?: {
    channel_id?: string;
    bindings?: AgentIntegrationBinding[];
    activation_options?: AgentIntegrationActivationOption[];
  } | null;
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
    required_authoring_tools?: string[];
    missing_authoring_tools?: string[];
    recommended_skills?: string[];
    available_skills?: string[];
    missing_skills?: string[];
    health_loop?: string | null;
    html_authoring_check?: string | null;
    tool_widget_authoring_check?: string | null;
    authoring_flow?: string[];
    readiness?: string | null;
    findings?: AgentDoctorFinding[];
  };
  integrations?: AgentIntegrationReadiness;
  doctor: {
    status: AgentReadinessStatus;
    findings: AgentDoctorFinding[];
    proposed_actions?: AgentCapabilityAction[];
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
